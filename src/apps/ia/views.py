"""Pilotage › IA (administrateurs) : import d'un document par l'IA, correction des signalements par l'IA.

Les travaux longs (plusieurs minutes) tournent hors requête web (commande `ia_traiter`) ;
la page interroge leur état toutes les quelques secondes.
"""
import os
import subprocess
import sys

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.things.models import ContentReport
from apps.users.admin_dashboard import IsSuperuser

from . import client, documents, pipeline
from .client import IAErreur
from .models import IAFile, IAJob

MAX_EN_COURS = 3
INSTRUCTION_MAX = 4000
CREDIT_MAX = 120


def lancer(job):
    """Démarre le traitement dans un processus détaché (double fork : pas de processus zombie)."""
    if getattr(settings, 'IA_LANCEMENT', 'processus') != 'processus':
        return  # tests : le traitement est appelé directement
    manage = os.path.join(str(settings.BASE_DIR), 'manage.py')
    subprocess.Popen(['sh', '-c', f'"{sys.executable}" "{manage}" ia_traiter {int(job.pk)} &'],
                     start_new_session=True).wait()


def _occupe():
    pipeline.interrompus().update(status=IAJob.ERREUR, etape='',
                                  error='Travail interrompu (serveur redémarré ?) : le relancer.')
    return IAJob.objects.filter(status__in=[IAJob.EN_ATTENTE, IAJob.EN_COURS]).count() >= MAX_EN_COURS


def _resume(job):
    r = job.result or {}
    out = {
        'id': job.id, 'kind': job.kind, 'status': job.status, 'etape': job.etape, 'error': job.error,
        'created_at': job.created_at.isoformat(), 'updated_at': job.updated_at.isoformat(),
        'created_by': job.created_by.username if job.created_by else None,
        'document': job.options.get('document', ''),
        'usage': job.usage,
    }
    if job.kind == IAJob.IMPORT:
        out['fiches'] = [{'cle': f.get('cle'), 'titre': f.get('titre'), 'type': f.get('type')}
                         for f in r.get('fiches') or [] if isinstance(f, dict)]
        out['publies'] = r.get('publies') or []
        out['nb_doutes'] = len(r.get('doutes') or []) + len(r.get('problemes') or [])
    else:
        rep = job.report
        out['signalement'] = rep.id if rep else None
        out['fonde'] = r.get('fonde')
        out['contenu'] = {'id': rep.content_id, 'titre': rep.content.title} if rep else None
    return out


def _detail(job):
    out = _resume(job)
    r = job.result or {}
    out['options'] = {k: v for k, v in job.options.items() if k != 'instruction'}
    out['history'] = job.history
    if job.kind == IAJob.IMPORT:
        out.update({
            'doutes': r.get('doutes') or [], 'problemes': r.get('problemes') or [],
            'solutions_du_document': bool(r.get('solutions_du_document')),
            'controles': r.get('controles') or [], 'erreurs_figures': r.get('erreurs_figures') or [],
            'avertissements': r.get('avertissements') or [],
            'apercus': pipeline.apercus(job) if r.get('fiches') else [],
            'fichiers': [{'id': f.id, 'nom': f.name, 'mime': f.mime} for f in job.files.all()],
        })
    else:
        out.update({k: r.get(k) for k in ('explication', 'doutes', 'modifications', 'erreurs')})
        rep = job.report
        if rep:
            out['report'] = {'id': rep.id, 'reason': rep.get_reason_display(), 'item_label': rep.item_label,
                             'description': rep.description, 'status': rep.status}
    return out


@api_view(['GET'])
@permission_classes([IsSuperuser])
def jobs(request):
    """Travaux récents, et si l'IA est prête (clé configurée)."""
    _occupe()
    qs = IAJob.objects.select_related('created_by', 'report__content')
    kind = request.query_params.get('kind')
    if kind in (IAJob.IMPORT, IAJob.SIGNALEMENT):
        qs = qs.filter(kind=kind)
    return Response({
        'configuree': client.configuree(),
        'modele': getattr(settings, 'ANTHROPIC_MODEL', ''),
        'results': [_resume(j) for j in qs[:60]],
    })


@api_view(['POST'])
@permission_classes([IsSuperuser])
@parser_classes([MultiPartParser, FormParser])
def nouvel_import(request):
    """Envoi d'un document (PDF, Word, ou images) et des options ; l'IA rédige le brouillon."""
    if not client.configuree():
        return Response({'detail': 'IA non configurée sur le serveur.'}, status=status.HTTP_400_BAD_REQUEST)
    if _occupe():
        return Response({'detail': f'{MAX_EN_COURS} travaux sont déjà en cours : attendre qu’ils finissent.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    d = request.data
    origine = d.get('origine')
    if origine not in pipeline.ORIGINES:
        return Response({'origine': 'Préciser les droits du document.'}, status=status.HTTP_400_BAD_REQUEST)
    credit = (d.get('credit') or '').strip()
    if len(credit) > CREDIT_MAX:
        return Response({'credit': f'{CREDIT_MAX} caractères au plus.'}, status=status.HTTP_400_BAD_REQUEST)
    consignes = (d.get('consignes') or '').strip()
    if len(consignes) > INSTRUCTION_MAX:
        return Response({'consignes': f'{INSTRUCTION_MAX} caractères au plus.'}, status=status.HTTP_400_BAD_REQUEST)
    fichiers = request.FILES.getlist('fichiers')
    lus = [(f.name, documents.type_mime(f.name, f.content_type), f.read()) for f in fichiers]
    try:
        documents.controler(lus)
    except IAErreur as exc:
        return Response({'fichiers': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    niveau = (d.get('niveau') or '').strip()
    type_ = d.get('type') if d.get('type') in ('exercice', 'examen', 'lecon') else ''
    job = IAJob.objects.create(
        kind=IAJob.IMPORT, created_by=request.user,
        options={'origine': origine, 'credit': credit, 'consignes': consignes, 'niveau': niveau[:60],
                 'type': type_, 'document': ', '.join(n for n, _, _ in lus)[:250]},
    )
    for nom, mime, data in lus:
        IAFile.objects.create(job=job, name=nom[:255], mime=mime, data=data)
    lancer(job)
    return Response(_resume(job), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsSuperuser])
def corriger_signalement(request, pk):
    """L'IA examine un signalement et propose une correction (rien n'est modifié avant votre accord)."""
    report = get_object_or_404(ContentReport, pk=pk)
    if not client.configuree():
        return Response({'detail': 'IA non configurée sur le serveur.'}, status=status.HTTP_400_BAD_REQUEST)
    if _occupe():
        return Response({'detail': f'{MAX_EN_COURS} travaux sont déjà en cours : attendre qu’ils finissent.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    instruction = (request.data.get('instruction') or '').strip()[:INSTRUCTION_MAX]
    job = IAJob.objects.create(kind=IAJob.SIGNALEMENT, created_by=request.user, report=report,
                               options={'instruction': instruction} if instruction else {})
    lancer(job)
    return Response(_resume(job), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsSuperuser])
def signalement_jobs(request, pk):
    """Dernière proposition de l'IA pour ce signalement (s'il y en a une)."""
    job = IAJob.objects.filter(kind=IAJob.SIGNALEMENT, report_id=pk).first()
    return Response(_detail(job) if job else None)


@api_view(['GET'])
@permission_classes([IsSuperuser])
def job_detail(request, pk):
    _occupe()
    return Response(_detail(get_object_or_404(IAJob, pk=pk)))


def _pret(job):
    if job.status != IAJob.PRET:
        return Response({'detail': 'Ce travail n’est pas prêt (ou a déjà été traité).'}, status=status.HTTP_409_CONFLICT)
    return None


@api_view(['POST'])
@permission_classes([IsSuperuser])
def job_corriger(request, pk):
    """Brouillon d'import : demander une modification à l'IA (« la question 2 est mal recopiée… »)."""
    job = get_object_or_404(IAJob, pk=pk, kind=IAJob.IMPORT)
    if (bloque := _pret(job)):
        return bloque
    instruction = (request.data.get('instruction') or '').strip()
    if not instruction:
        return Response({'instruction': 'Écrire la demande.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(instruction) > INSTRUCTION_MAX:
        return Response({'instruction': f'{INSTRUCTION_MAX} caractères au plus.'}, status=status.HTTP_400_BAD_REQUEST)
    if _occupe():
        return Response({'detail': f'{MAX_EN_COURS} travaux sont déjà en cours : attendre qu’ils finissent.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    job.options['instruction'] = instruction
    job.history.append({'date': timezone.now().isoformat(), 'qui': request.user.username, 'texte': instruction})
    job.status, job.etape, job.error = IAJob.EN_ATTENTE, 'En attente', ''
    job.save()
    lancer(job)
    return Response(_resume(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
def job_relancer(request, pk):
    """Relancer un travail en erreur (crédit rechargé, coupure…)."""
    job = get_object_or_404(IAJob, pk=pk)
    if job.status != IAJob.ERREUR:
        return Response({'detail': 'Seul un travail en erreur se relance.'}, status=status.HTTP_409_CONFLICT)
    if _occupe():
        return Response({'detail': f'{MAX_EN_COURS} travaux sont déjà en cours : attendre qu’ils finissent.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    job.status, job.etape, job.error = IAJob.EN_ATTENTE, 'En attente', ''
    job.save()
    lancer(job)
    return Response(_resume(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
@parser_classes([JSONParser])
def job_publier(request, pk):
    """Publier le brouillon. Corps : {"a_verifier": bool, "doublon_ok": bool}."""
    job = get_object_or_404(IAJob, pk=pk, kind=IAJob.IMPORT)
    if (bloque := _pret(job)):
        return bloque
    a_verifier = request.data.get('a_verifier', True)
    doublon_ok = request.data.get('doublon_ok', False)
    if not isinstance(a_verifier, bool) or not isinstance(doublon_ok, bool):
        return Response({'detail': 'a_verifier et doublon_ok : true ou false'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        publies = pipeline.publier(job, a_verifier=a_verifier, doublon_ok=doublon_ok, auteur=request.user)
    except (IAErreur, Exception) as exc:  # FicheError, contrôle refusé : le brouillon reste intact
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    job.result['publies'] = publies
    job.status = IAJob.PUBLIE
    job.history.append({'date': timezone.now().isoformat(), 'qui': request.user.username,
                        'texte': 'Publié' + (' (correction à vérifier)' if a_verifier else '')})
    job.save()
    return Response(_detail(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
@parser_classes([JSONParser])
def job_appliquer(request, pk):
    """Signalement : appliquer la correction proposée. Corps : {"a_verifier": bool}."""
    job = get_object_or_404(IAJob, pk=pk, kind=IAJob.SIGNALEMENT)
    if (bloque := _pret(job)):
        return bloque
    a_verifier = request.data.get('a_verifier', True)
    if not isinstance(a_verifier, bool):
        return Response({'detail': 'a_verifier : true ou false'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        pipeline.appliquer(job, a_verifier=a_verifier, auteur=request.user)
    except IAErreur as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
    job.status = IAJob.APPLIQUE
    job.save()
    return Response(_detail(job))


@api_view(['POST'])
@permission_classes([IsSuperuser])
def job_rejeter(request, pk):
    job = get_object_or_404(IAJob, pk=pk)
    if job.status not in (IAJob.PRET, IAJob.ERREUR):
        return Response({'detail': 'Ce travail ne peut plus être rejeté.'}, status=status.HTTP_409_CONFLICT)
    job.status = IAJob.REJETE
    job.history.append({'date': timezone.now().isoformat(), 'qui': request.user.username, 'texte': 'Rejeté'})
    job.save()
    job.files.all().delete()  # le document n'est plus utile
    return Response(_resume(job))
