"""Signalements d'erreurs sur les contenus (exercices, examens, leçons).

Un élève connecté signale une erreur : la raison (énoncé, solution, barème…), la question
concernée (facultatif) et un mot d'explication (facultatif). Les administrateurs les traitent
depuis Pilotage (/api/pilotage/signalements/).
"""
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.things.models import Content, ContentReport
from apps.users.admin_dashboard import IsSuperuser
from config.throttling import ContentReportThrottle

DESCRIPTION_MAX = 1000
LABEL_MAX = 160
SECTION_URL = {'exercise': 'exercises', 'lesson': 'lessons', 'exam': 'exams'}


def reportable_paths(content):
    """Endroits désignables d'un contenu : blocs (énoncé, questions, parties) et sous-questions,
    ou parties et sous-parties d'une leçon. Le chemin suit celui de la progression (« q2.sq1 »)."""
    structure = content.json_content or {}
    paths = set()
    for block in structure.get('blocks', []) or []:
        bid = block.get('id')
        if not bid:
            continue
        paths.add(bid)
        for sub in block.get('subQuestions', []) or []:
            if sub.get('id'):
                paths.add(f"{bid}.{sub['id']}")
    for section in structure.get('sections', []) or []:
        sid = section.get('id')
        if not sid:
            continue
        paths.add(sid)
        for sub in section.get('subSections', []) or []:
            if sub.get('id'):
                paths.add(f"{sid}.{sub['id']}")
    return paths


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([ContentReportThrottle])
def report_content(request, content_id):
    content = get_object_or_404(Content, pk=content_id)
    data = request.data

    reason = data.get('reason')
    if reason not in dict(ContentReport.REASON_CHOICES):
        return Response({'reason': 'Choisis une raison.'}, status=status.HTTP_400_BAD_REQUEST)
    if reason == ContentReport.REASON_SCALE and content.type != Content.TYPE_EXAM:
        return Response({'reason': 'Le barème ne concerne que les examens.'}, status=status.HTTP_400_BAD_REQUEST)

    item_path = (data.get('item_path') or '').strip()
    if item_path and item_path not in reportable_paths(content):
        return Response({'item_path': 'Cette question n’existe pas dans ce contenu.'}, status=status.HTTP_400_BAD_REQUEST)
    item_label = (data.get('item_label') or '').strip()[:LABEL_MAX] if item_path else ''

    description = (data.get('description') or '').strip()
    if len(description) > DESCRIPTION_MAX:
        return Response({'description': f'{DESCRIPTION_MAX} caractères au maximum.'}, status=status.HTTP_400_BAD_REQUEST)

    # Même élève, même endroit, même raison, pas encore traité : on complète au lieu de doubler.
    existing = ContentReport.objects.filter(
        content=content, user=request.user, item_path=item_path, reason=reason, status=ContentReport.STATUS_OPEN,
    ).first()
    if existing:
        if description:
            existing.description = description
            existing.save(update_fields=['description'])
        return Response({'id': existing.id, 'duplicate': True}, status=status.HTTP_200_OK)

    report = ContentReport.objects.create(
        content=content, user=request.user, reason=reason,
        item_path=item_path, item_label=item_label, description=description,
    )
    return Response({'id': report.id, 'duplicate': False}, status=status.HTTP_201_CREATED)


def _serialize(report):
    content = report.content
    return {
        'id': report.id,
        'reason': report.reason,
        'reason_label': report.get_reason_display(),
        'item_path': report.item_path,
        'item_label': report.item_label,
        'description': report.description,
        'status': report.status,
        'created_at': report.created_at.isoformat(),
        'handled_at': report.handled_at.isoformat() if report.handled_at else None,
        'handled_by': report.handled_by.username if report.handled_by else None,
        'user': report.user.username if report.user else None,
        'content': {
            'id': content.id, 'type': content.type, 'title': content.title,
            'url': f"/{SECTION_URL.get(content.type, 'exercises')}/{content.id}",
        },
    }


@api_view(['GET'])
@permission_classes([IsSuperuser])
def reports_list(request):
    """Signalements, les plus récents d'abord. ?statut=open|resolved|dismissed|all (open par défaut)."""
    wanted = request.query_params.get('statut', ContentReport.STATUS_OPEN)
    qs = ContentReport.objects.select_related('content', 'user', 'handled_by')
    if wanted != 'all':
        qs = qs.filter(status=wanted)
    counts = dict(ContentReport.objects.values_list('status').annotate(n=Count('id')))
    return Response({
        'counts': {key: counts.get(key, 0) for key, _ in ContentReport.STATUS_CHOICES},
        'results': [_serialize(r) for r in qs.order_by('-created_at')[:200]],
    })


@api_view(['PATCH'])
@permission_classes([IsSuperuser])
def report_update(request, pk):
    """Marquer un signalement corrigé, sans suite, ou le rouvrir."""
    report = get_object_or_404(ContentReport, pk=pk)
    new_status = request.data.get('status')
    if new_status not in dict(ContentReport.STATUS_CHOICES):
        return Response({'status': 'Statut inconnu.'}, status=status.HTTP_400_BAD_REQUEST)
    report.status = new_status
    if new_status == ContentReport.STATUS_OPEN:
        report.handled_at, report.handled_by = None, None
    else:
        report.handled_at, report.handled_by = timezone.now(), request.user
    report.save(update_fields=['status', 'handled_at', 'handled_by'])
    return Response(_serialize(report))
