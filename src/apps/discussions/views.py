"""API de l'espace Discussions (08/11/2026).

GET  /api/discussions/                     liste (salon, niveau, chapitre, contenu, recherche, tri, page)
POST /api/discussions/                     nouvelle discussion {title, body, salon, class_level, content_ids, file_ids}
GET|PATCH|DELETE /api/discussions/<id>/    détail (avec les réponses) ; modifier, supprimer : auteur ou équipe
POST /api/discussions/<id>/repondre/       {body, reply_to, file_ids}
POST /api/discussions/<id>/utile/          vote « utile » (bascule)
POST /api/discussions/<id>/suivre/         suivre / ne plus suivre (bascule)
PATCH|DELETE /api/discussions/reponses/<id>/      auteur ou équipe
POST /api/discussions/reponses/<id>/utile/
GET  /api/discussions/panneau/             salons, contenus les plus discutés, membres les plus utiles
GET  /api/discussions/compteur/            discussions sans réponse à son niveau (barre de navigation)
GET  /api/discussions/contenus/?q=         contenus à taguer (recherche par titre, ou n° du contenu)
Lecture ouverte à tous (limitée par IP pour les visiteurs) ; écrire demande un compte.
"""
from collections import Counter
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.caracteristics.models import ClassLevel
from apps.interactions.models import Vote
from apps.things.models import Content
from apps.things.search_text import normalize
from config.throttling import (ApiMembreThrottle, ApiVisiteurThrottle, ContenuVisiteurMinute, DiscussionReponseThrottle,
                               DiscussionThrottle)

from . import presenters
from .models import SALON_KEYS, SALONS, Discussion, Follow, Reply, plain_text
from .services import later, notify_new_discussion, notify_new_reply

PAGE = 20
TRIS = ('recentes', 'populaires', 'sans_reponse', 'suivies')
TITLE_MIN, TITLE_MAX = 6, 160
BODY_MAX = 20000
MAX_TAGS = 5
MAX_FILES = 6
LECTURE = [ApiVisiteurThrottle, ApiMembreThrottle, ContenuVisiteurMinute]


def _id(value):
    """Identifiant envoyé par le navigateur (texte ou nombre), None s'il est illisible."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _default_level(user):
    profile = getattr(user, 'profile', None) if user and user.is_authenticated else None
    if profile is None or profile.user_type == 'teacher':
        return None
    return profile.class_level_id


def _level_filter(request):
    """?niveau=<id>|tous ; absent : le niveau de l'élève. Les discussions sans niveau sont de tous les niveaux."""
    raw = request.query_params.get('niveau')
    if raw == 'tous':
        return None
    if raw is not None:
        return _id(raw) or -1
    return _default_level(request.user)


def _scope(request):
    """Discussions du niveau et du salon demandés (sans tri ni recherche)."""
    qs = Discussion.objects.all()
    level = _level_filter(request)
    if level is not None:
        qs = qs.filter(Q(class_level_id=level) | Q(class_level__isnull=True))
    return qs, level


def _others_replies():
    return Count('replies', filter=~Q(replies__author_id=F('author_id')), distinct=True)


def _unanswered(qs):
    return qs.annotate(autres=_others_replies()).filter(autres=0)


def _member(request):
    """Le membre connecté, ou None (visiteur : `request.user` vaut None ici, UNAUTHENTICATED_USER)."""
    user = getattr(request, 'user', None)
    return user if user is not None and user.is_authenticated else None


def _owner_or_staff(request, obj):
    user = _member(request)
    return bool(user and (obj.author_id == user.id or user.is_staff or user.is_superuser))


def _delete_files(objs):
    """Fichiers rattachés à des messages supprimés : effacés du stockage avec eux."""
    from apps.uploads.models import FileAttachment
    for model, ids in objs:
        if not ids:
            continue
        ct = ContentType.objects.get_for_model(model)
        for attachment in FileAttachment.objects.filter(content_type=ct, object_id__in=ids):
            attachment.delete_file()  # gardé s'il sert encore au commentaire repris (FileAttachment.delete_file)
            attachment.delete()


def _attach(obj, file_ids, user):
    from apps.things.views import attach_own_files
    if isinstance(file_ids, list):
        attach_own_files(obj, [i for i in file_ids if _id(i)][:MAX_FILES], user)


def _content_ids(raw):
    """Contenus tagués : identifiants existants, MAX_TAGS au plus, dans l'ordre donné ; None si illisible."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    ids = list(dict.fromkeys(_id(x) for x in raw))
    if None in ids or len(ids) > MAX_TAGS:
        return None
    found = set(Content.objects.filter(id__in=ids).values_list('id', flat=True))
    return [i for i in ids if i in found] if len(found) == len(ids) else None


def _validate(data, partial=False):
    """Champs d'une discussion ; renvoie (valeurs, erreurs)."""
    values, errors = {}, {}
    if not partial or 'title' in data:
        title = data.get('title')
        title = ' '.join(title.split()) if isinstance(title, str) else ''
        if not TITLE_MIN <= len(title) <= TITLE_MAX:
            errors['title'] = f'Un titre de {TITLE_MIN} à {TITLE_MAX} caractères.'
        values['title'] = title
    if not partial or 'body' in data:
        body = data.get('body') if isinstance(data.get('body'), str) else ''
        if len(body) > BODY_MAX:
            errors['body'] = f'{BODY_MAX} caractères au maximum.'
        values['body'] = body
    if not partial or 'salon' in data:
        salon = data.get('salon') or 'entraide'
        if salon not in SALON_KEYS:
            errors['salon'] = 'Salon inconnu.'
        values['salon'] = salon
    if 'class_level' in data:
        raw = data.get('class_level')
        if raw in (None, '', 'tous'):
            values['class_level_id'] = None
        else:
            level = _id(raw)
            if not level or not ClassLevel.objects.filter(id=level).exists():
                errors['class_level'] = 'Niveau inconnu.'
            values['class_level_id'] = level
    if not partial or 'content_ids' in data:
        ids = _content_ids(data.get('content_ids'))
        if ids is None:
            errors['content_ids'] = f'{MAX_TAGS} contenus au plus, parmi ceux du site.'
        values['content_ids'] = ids or []
    return values, errors


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
@throttle_classes(LECTURE)
def discussions(request):
    if request.method == 'POST':
        return _create(request)
    qs, level = _scope(request)
    salon = request.query_params.get('salon')
    if salon:
        qs = qs.filter(salon=salon if salon in SALON_KEYS else '-')
    chapter = request.query_params.get('chapitre')
    if chapter:
        qs = qs.filter(id__in=Discussion.objects.filter(contents__chapters__id=_id(chapter) or -1).values('id'))
    content = request.query_params.get('contenu')
    if content:
        qs = qs.filter(id__in=Discussion.objects.filter(contents__id=_id(content) or -1).values('id'))
    author = request.query_params.get('auteur')
    if author:
        qs = qs.filter(author__username=author)
    for word in normalize(request.query_params.get('q') or '').split()[:8]:
        qs = qs.filter(search_text__contains=word)
    tri = request.query_params.get('tri') or 'recentes'
    if tri not in TRIS:
        return Response({'error': 'tri inconnu'}, status=400)
    if tri == 'sans_reponse':
        qs = _unanswered(qs).order_by('-created_at', '-id')
    elif tri == 'populaires':
        qs = qs.annotate(u=Count('votes', filter=Q(votes__value=Vote.UP), distinct=True)) \
            .order_by('-u', '-reply_count', '-last_activity_at', '-id')
    elif tri == 'suivies':
        if not _member(request):
            return Response({'error': 'connexion requise'}, status=401)
        qs = qs.filter(follows__user=request.user).order_by('-last_activity_at', '-id')
    else:
        qs = qs.order_by('-last_activity_at', '-id')
    try:
        page = max(1, int(request.query_params.get('page') or 1))
    except ValueError:
        page = 1
    total = qs.count()
    rows = presenters.card_queryset(qs)[(page - 1) * PAGE: page * PAGE]
    return Response({
        'count': total, 'page': page, 'pages': max(1, -(-total // PAGE)), 'niveau': level,
        'results': presenters.cards(rows, request),
    })


def _create(request):
    if not _member(request):
        return Response({'error': 'connexion requise'}, status=401)
    if not DiscussionThrottle().allow_request(request, None):
        return Response({'error': 'Trop de discussions d’un coup. Réessaie dans un moment.'}, status=429)
    values, errors = _validate(request.data)
    if errors:
        return Response(errors, status=400)
    level = values.pop('class_level_id', _default_level(request.user))
    content_ids = values.pop('content_ids')
    with transaction.atomic():
        d = Discussion.objects.create(author=request.user, class_level_id=level, **values)
        d.contents.set(content_ids)
        Follow.objects.get_or_create(discussion=d, user=request.user)
        _attach(d, request.data.get('file_ids'), request.user)
    later(notify_new_discussion, d)
    d = presenters.card_queryset(Discussion.objects.filter(pk=d.pk)).get()
    return Response(presenters.detail(d, request), status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
@throttle_classes(LECTURE)
def discussion(request, pk):
    d = get_object_or_404(presenters.card_queryset(Discussion.objects.all()), pk=pk)
    if request.method == 'GET':
        return Response(presenters.detail(d, request))
    if not _owner_or_staff(request, d):
        return Response({'error': 'Réservé à son auteur.'}, status=403)
    if request.method == 'DELETE':
        _delete_files([(Discussion, [d.id]), (Reply, list(d.replies.values_list('id', flat=True)))])
        d.delete()
        return Response(status=204)
    values, errors = _validate(request.data, partial=True)
    if errors:
        return Response(errors, status=400)
    content_ids = values.pop('content_ids', None)
    for field, value in values.items():
        setattr(d, field, value)
    d.edited_at = timezone.now()
    with transaction.atomic():
        d.save()
        if content_ids is not None:
            d.contents.set(content_ids)
    d = presenters.card_queryset(Discussion.objects.filter(pk=d.pk)).get()
    return Response(presenters.detail(d, request))


def _reply_body(request):
    body = request.data.get('body')
    body = body if isinstance(body, str) else ''
    has_files = isinstance(request.data.get('file_ids'), list) and bool(request.data.get('file_ids'))
    if not plain_text(body) and not has_files:
        return None, {'body': 'Écris ta réponse.'}
    if len(body) > BODY_MAX:
        return None, {'body': f'{BODY_MAX} caractères au maximum.'}
    return body, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([ApiMembreThrottle, DiscussionReponseThrottle])
def repondre(request, pk):
    d = get_object_or_404(Discussion, pk=pk)
    body, error = _reply_body(request)
    if error:
        return Response(error, status=400)
    reply_to = None
    if request.data.get('reply_to') not in (None, ''):
        reply_to = Reply.objects.filter(pk=_id(request.data.get('reply_to')) or -1, discussion=d).first()
        if reply_to is None:
            return Response({'reply_to': 'Réponse introuvable dans cette discussion.'}, status=400)
    with transaction.atomic():
        r = Reply.objects.create(discussion=d, author=request.user, body=body, reply_to=reply_to)
        _attach(r, request.data.get('file_ids'), request.user)
        Discussion.objects.filter(pk=d.pk).update(reply_count=F('reply_count') + 1, last_activity_at=r.created_at)
        Follow.objects.get_or_create(discussion=d, user=request.user)
    later(notify_new_reply, r)
    r = Reply.objects.select_related('author__profile__class_level', 'reply_to__author').get(pk=r.pk)
    return Response(presenters.reply_data(r, request, {}, set()), status=201)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def reponse(request, pk):
    r = get_object_or_404(Reply.objects.select_related('author__profile__class_level', 'reply_to__author'), pk=pk)
    if not _owner_or_staff(request, r):
        return Response({'error': 'Réservé à son auteur.'}, status=403)
    if request.method == 'DELETE':
        did = r.discussion_id
        _delete_files([(Reply, [r.id])])
        r.delete()
        last = Reply.objects.filter(discussion_id=did).aggregate(m=Max('created_at'))['m']
        d = Discussion.objects.get(pk=did)
        Discussion.objects.filter(pk=did).update(reply_count=Reply.objects.filter(discussion_id=did).count(),
                                                 last_activity_at=last or d.created_at)
        return Response(status=204)
    body, error = _reply_body(request)
    if error:
        return Response(error, status=400)
    r.body, r.edited_at = body, timezone.now()
    r.save(update_fields=['body', 'edited_at'])
    utiles, mine = presenters.utile_counts(Reply, [r.id], request.user)
    return Response(presenters.reply_data(r, request, utiles, mine))


def _toggle_utile(request, obj):
    if obj.author_id == request.user.id:
        return Response({'error': 'Pas sur ses propres messages.'}, status=400)
    vote = obj.votes.filter(user=request.user).first()
    if vote and vote.value == Vote.UP:
        vote.delete()
        mine = False
    else:
        if vote:
            vote.value = Vote.UP
            vote.save(update_fields=['value', 'updated_at'])
        else:
            obj.votes.create(user=request.user, value=Vote.UP)
        mine = True
    return Response({'utile': obj.votes.filter(value=Vote.UP).count(), 'user_utile': mine})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([ApiMembreThrottle])
def utile(request, pk):
    return _toggle_utile(request, get_object_or_404(Discussion, pk=pk))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([ApiMembreThrottle])
def reponse_utile(request, pk):
    return _toggle_utile(request, get_object_or_404(Reply, pk=pk))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([ApiMembreThrottle])
def suivre(request, pk):
    d = get_object_or_404(Discussion, pk=pk)
    follow, created = Follow.objects.get_or_create(discussion=d, user=request.user)
    if not created:
        follow.delete()
    return Response({'followed': created, 'followers': d.follows.count()})


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes(LECTURE)
def panneau(request):
    """Colonne de l'espace : salons (nombre de discussions), contenus les plus discutés et membres les plus utiles
    sur 30 jours, discussions sans réponse — au niveau demandé (?niveau=, défaut : celui de l'élève)."""
    qs, level = _scope(request)
    counts = dict(qs.values('salon').annotate(n=Count('id')).values_list('salon', 'n'))
    since = timezone.now() - timedelta(days=30)
    recent = qs.filter(last_activity_at__gte=since)
    top = list(Content.objects.filter(discussions__in=recent).annotate(n=Count('discussions', distinct=True))
               .order_by('-n', 'title')[:5])
    tops = {c.id: c.n for c in top}
    tagged = presenters.tags_queryset().filter(id__in=tops)
    statuses = presenters.content_statuses(request.user, list(tops))
    tendances = sorted(({'content': presenters.content_tag(c, statuses), 'discussions': tops[c.id]} for c in tagged),
                       key=lambda x: (-x['discussions'], x['content']['title']))
    # Membres les plus utiles : votes « utile » reçus sur leurs discussions et leurs réponses, 30 derniers jours.
    received = Counter()
    for model in (Discussion, Reply):
        ct = ContentType.objects.get_for_model(model)
        votes = Counter(Vote.objects.filter(content_type=ct, value=Vote.UP, created_at__gte=since)
                        .values_list('object_id', flat=True))
        authors = dict(model.objects.filter(id__in=[int(i) for i in votes]).values_list('id', 'author_id'))
        for oid, n in votes.items():
            if int(oid) in authors:
                received[authors[int(oid)]] += n
    users = {u.id: u for u in User.objects.filter(id__in=[u for u, _ in received.most_common(5)], is_active=True)
             .select_related('profile__class_level')}
    utiles = [{'author': presenters.author(users[u], request), 'utile': n}
              for u, n in received.most_common(5) if u in users]
    return Response({
        'niveau': level,
        'salons': [{'key': k, 'label': label, 'count': counts.get(k, 0)} for k, label in SALONS],
        'total': sum(counts.values()),
        'sans_reponse': _unanswered(qs).count(),
        'tendances': tendances,
        'utiles': utiles,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def compteur(request):
    """Discussions sans réponse à son niveau, hors les siennes (entrée « Discussions » du menu)."""
    qs, _ = _scope(request)
    return Response({'sans_reponse': _unanswered(qs.exclude(author=request.user)).count()})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([ApiMembreThrottle])
def contenus(request):
    """Contenus à taguer : recherche dans le titre et le texte (sans accents), ou n° du contenu (« 123 »)."""
    q = (request.query_params.get('q') or '').strip()
    if len(q) < 2 and not q.isdigit():
        return Response({'results': []})
    qs = presenters.tags_queryset()
    if q.lstrip('#').isdigit():
        qs = qs.filter(Q(id=int(q.lstrip('#'))) | Q(display_id=int(q.lstrip('#'))))
    else:
        for word in normalize(q).split()[:6]:
            qs = qs.filter(search_text__contains=word)
        # Le titre qui contient la recherche d'abord, puis les plus lus.
        qs = qs.annotate(dans_titre=Count('id', filter=Q(title__icontains=q))).order_by('-dans_titre', '-view_count', 'id')
    rows = list(qs[:8])
    statuses = presenters.content_statuses(request.user, [c.id for c in rows])
    return Response({'results': [presenters.content_tag(c, statuses) for c in rows]})
