"""Ce que l'API de l'espace Discussions renvoie : cartes de discussion, détail avec réponses, cartes des contenus
tagués. Tout est chargé par lots (une page = une poignée de requêtes, quelle que soit sa taille)."""
from collections import defaultdict

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, F, Prefetch

from apps.interactions.models import Complete, Vote
from apps.notifications.services import sans_formule_coupee
from apps.things.models import Content
from apps.uploads.serializers import FileAttachmentSerializer
from apps.users.serializers import AuthorSerializer

from .models import Discussion, Follow, Reply, plain_text

TYPE_PATH = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}
TYPE_RANK = {'exercise': 0, 'exam': 1, 'lesson': 2}
EXCERPT = 220
REPLIERS = 3


def excerpt(body):
    text = plain_text(body)
    return text if len(text) <= EXCERPT else sans_formule_coupee(text[:EXCERPT - 1]).rstrip() + '…'


def author(user, request):
    """Auteur affiché : pseudo, photo, et un repère public (niveau d'un élève, « prof », « équipe »)."""
    data = AuthorSerializer(user, context={'request': request}).data
    profile = getattr(user, 'profile', None)
    if user.is_staff or user.is_superuser:
        role = 'equipe'
    elif profile is not None and profile.user_type == 'teacher':
        role = 'prof'
    else:
        role = 'eleve'
    data['role'] = role
    data['level'] = profile.class_level.name if role == 'eleve' and profile and profile.class_level_id else None
    return data


def content_statuses(viewer, content_ids):
    """Statut de l'élève connecté sur chaque contenu tagué (réussi, à revoir), pour la carte du contenu."""
    if not (viewer and viewer.is_authenticated and content_ids):
        return {}
    ct = ContentType.objects.get_for_model(Content)
    rows = Complete.objects.filter(user=viewer, content_type=ct, object_id__in=[str(i) for i in content_ids])
    return {int(oid): st for oid, st in rows.values_list('object_id', 'status')}


def content_tag(c, statuses):
    levels = sorted(c.class_levels.all(), key=lambda lv: lv.order)
    chapters = list(c.chapters.all())
    return {
        'id': c.id, 'type': c.type, 'title': c.title, 'url': f'/{TYPE_PATH.get(c.type, "exercises")}/{c.id}',
        'difficulty': c.difficulty, 'level': levels[0].name if levels else None,
        'chapter': chapters[0].name if chapters else None, 'status': statuses.get(c.id),
    }


def tags_queryset():
    return Content.objects.prefetch_related('class_levels', 'chapters')


def utile_counts(model, ids, viewer):
    """Votes « utile » par objet, et ceux de l'élève connecté."""
    if not ids:
        return {}, set()
    ct = ContentType.objects.get_for_model(model)
    sids = [str(i) for i in ids]
    counts = {int(r['object_id']): r['n'] for r in Vote.objects.filter(content_type=ct, object_id__in=sids, value=Vote.UP)
              .values('object_id').annotate(n=Count('id'))}
    mine = set()
    if viewer and viewer.is_authenticated:
        mine = {int(o) for o in Vote.objects.filter(content_type=ct, object_id__in=sids, value=Vote.UP, user=viewer)
                .values_list('object_id', flat=True)}
    return counts, mine


def cards(discussions, request):
    discussions = list(discussions)
    viewer = getattr(request, 'user', None)
    ids = [d.id for d in discussions]
    statuses = content_statuses(viewer, {c.id for d in discussions for c in d.contents.all()})
    utiles, mine = utile_counts(Discussion, ids, viewer)
    followed = set()
    if viewer and viewer.is_authenticated and ids:
        followed = set(Follow.objects.filter(user=viewer, discussion_id__in=ids).values_list('discussion_id', flat=True))
    # Derniers membres qui ont répondu (trois au plus par discussion), sans requête par carte.
    repliers = defaultdict(list)
    rows = Reply.objects.filter(discussion_id__in=ids).order_by('-created_at').values_list('discussion_id', 'author_id')
    for did, uid in rows[:600]:
        if uid not in repliers[did] and len(repliers[did]) < REPLIERS:
            repliers[did].append(uid)
    users = {u.id: u for u in User.objects.filter(id__in={u for lst in repliers.values() for u in lst})
             .select_related('profile')}
    # Répondue = au moins une réponse d'un autre membre que l'auteur (même règle que le tri « sans réponse »).
    answered = set(Reply.objects.filter(discussion_id__in=ids).exclude(author_id=F('discussion__author_id'))
                   .values_list('discussion_id', flat=True).distinct())
    out = []
    for d in discussions:
        out.append({
            'id': d.id,
            'title': d.title,
            'excerpt': excerpt(d.body),
            'salon': d.salon,
            'author': author(d.author, request),
            'class_level': {'id': d.class_level_id, 'name': d.class_level.name} if d.class_level_id else None,
            'created_at': d.created_at,
            'last_activity_at': d.last_activity_at,
            'reply_count': d.reply_count,
            'answered': d.id in answered,
            'utile': utiles.get(d.id, 0),
            'user_utile': d.id in mine,
            'followed': d.id in followed,
            # Ordre stable (la base ne garde pas l'ordre d'ajout) : exercices, examens, leçons, puis le n°.
            'tags': [content_tag(c, statuses) for c in sorted(d.contents.all(), key=lambda c: (TYPE_RANK.get(c.type, 9), c.id))],
            'repliers': [{'username': users[u].username, 'avatar': AuthorSerializer(users[u], context={'request': request}).data['avatar']}
                         for u in repliers.get(d.id, []) if u in users],
            'attachments': len(d.attachments.all()),
        })
    return out


def card_queryset(qs):
    """Tout ce que lisent les cartes, en une fois."""
    return qs.select_related('author', 'author__profile', 'author__profile__class_level', 'class_level') \
        .prefetch_related('attachments', Prefetch('contents', queryset=tags_queryset()))


def reply_data(r, request, utiles, mine):
    return {
        'id': r.id,
        'author': author(r.author, request),
        'body': r.body,
        'created_at': r.created_at,
        'edited_at': r.edited_at,
        'reply_to': {'id': r.reply_to_id, 'username': r.reply_to.author.username} if r.reply_to_id else None,
        'utile': utiles.get(r.id, 0),
        'user_utile': r.id in mine,
        'attachments': FileAttachmentSerializer(r.attachments.all(), many=True, context={'request': request}).data,
        'can_edit': can_edit(request, r),
    }


def can_edit(request, obj):
    user = getattr(request, 'user', None)
    return bool(user and user.is_authenticated and (obj.author_id == user.id or user.is_staff or user.is_superuser))


def detail(d, request):
    data = cards([d], request)[0]
    replies = list(d.replies.select_related('author', 'author__profile', 'author__profile__class_level',
                                            'reply_to__author').prefetch_related('attachments'))
    utiles, mine = utile_counts(Reply, [r.id for r in replies], getattr(request, 'user', None))
    data.update({
        'body': d.body,
        'edited_at': d.edited_at,
        'files': FileAttachmentSerializer(d.attachments.all(), many=True, context={'request': request}).data,
        'replies': [reply_data(r, request, utiles, mine) for r in replies],
        'followers': d.follows.count(),
        'can_edit': can_edit(request, d),
    })
    return data
