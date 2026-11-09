"""Où mène un message du forum ou un commentaire, et qui prévenir (notifications/services.notify : regroupé par
discussion tant que ce n'est pas lu, réglage « Notifications de commentaires » respecté).

- Nouvelle discussion du forum (« discussion ») : l'équipe, les professeurs de l'auteur (pour la matière des contenus
  tagués), et des élèves qui ont réussi un contenu tagué — au plus MAX_AIDANTS élèves, MAX_PAR_JOUR sollicitations par
  élève et par jour. Sans contenu tagué : l'équipe et les professeurs.
- Nouveau commentaire (« comment ») : l'équipe, les professeurs de l'auteur et ceux qui ont interagi avec le contenu.
  Personne n'est sollicité pour aider : un commentaire n'est pas forcément une question.
- Nouvelle réponse (« reponse ») : ceux qui suivent la discussion (l'auteur et ceux qui ont répondu, d'office) et
  l'auteur du message auquel on répond. Sous un contenu, celui à qui l'on répond reçoit « reply ».
- Mention @pseudo (« mention ») : le membre cité, au plus MAX_MENTIONS par message.
L'auteur du message n'est jamais prévenu.
"""
import logging
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import TYPE_PATH, content_participants, notify

from .models import COMMENTAIRE, Follow, plain_text

logger = logging.getLogger('django')

MAX_AIDANTS = 8
MAX_PAR_JOUR = 3
MAX_MENTIONS = 5
MENTION_RE = re.compile(r'(?<![\w@])@([\w.+-]{2,150})')


def contenu_de(discussion):
    """Le contenu sous lequel un commentaire est écrit (préchargé si possible) ; None pour le forum."""
    if discussion.genre != COMMENTAIRE:
        return None
    return next(iter(discussion.contents.all()), None)


def link(discussion):
    """Où mène un message : sa page (forum), ou l'onglet Commentaires de son contenu, sur ce commentaire."""
    content = contenu_de(discussion)
    if content is None:
        return f'/discussions/{discussion.id}'
    return f'/{TYPE_PATH.get(content.type, "exercises")}/{content.id}?onglet=discussions&fil={discussion.id}'


def reply_link(reply):
    return f'{link(reply.discussion)}#reponse-{reply.id}'


def titre(discussion):
    """Nom à montrer ailleurs que dans le fil (profil, fil d'activité, cloche) : le titre, ou le contenu d'un commentaire."""
    content = contenu_de(discussion)
    return discussion.title if content is None else content.title


def target(discussion):
    return f'discussion:{discussion.id}'


def delete_files(objs):
    """Fichiers rattachés à des messages supprimés : effacés du stockage avec eux."""
    from apps.uploads.models import FileAttachment
    for model, ids in objs:
        if not ids:
            continue
        ct = ContentType.objects.get_for_model(model)
        for attachment in FileAttachment.objects.filter(content_type=ct, object_id__in=ids):
            attachment.delete_file()  # gardé s'il sert encore au commentaire repris (FileAttachment.delete_file)
            attachment.delete()


def mentioned_ids(body, author_id):
    """Membres cités (@pseudo) dans un message, sans l'auteur ni les comptes désactivés."""
    names = list(dict.fromkeys(m.lower() for m in MENTION_RE.findall(plain_text(body))))[:MAX_MENTIONS]
    if not names:
        return set()
    query = Q()
    for name in names:
        query |= Q(username__iexact=name)
    return set(User.objects.filter(query, is_active=True).exclude(id=author_id).values_list('id', flat=True))


def encadrants(discussion):
    """L'équipe et les professeurs de l'auteur (pour la matière des contenus tagués)."""
    from apps.classrooms.models import Classroom, ClassroomMembership, ClassroomSubject

    ids = set(User.objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True))
              .values_list('id', flat=True))
    classes = ClassroomMembership.objects.filter(student_id=discussion.author_id).values('classroom_id')
    ids |= set(Classroom.objects.filter(id__in=classes).values_list('owner_id', flat=True))
    enseignants = ClassroomSubject.objects.filter(classroom_id__in=classes)
    subjects = {s for s in discussion.contents.values_list('subject_id', flat=True) if s}
    if subjects:
        enseignants = enseignants.filter(subject_id__in=subjects)
    return ids | set(enseignants.values_list('teacher_id', flat=True))


def aidants(discussion):
    """Membres sollicités pour une nouvelle discussion du forum (jamais son auteur)."""
    from apps.interactions.models import Complete, QuestionProgress
    from apps.things.models import Content

    author_id = discussion.author_id
    ids = encadrants(discussion)
    contents = list(discussion.contents.values_list('id', 'subject_id'))

    if contents:
        ct = ContentType.objects.get_for_model(Content)
        content_ids = [c for c, _ in contents]
        candidats = list(Complete.objects.filter(content_type=ct, object_id__in=[str(c) for c in content_ids],
                                                 status='success')
                         .order_by('-updated_at').values_list('user_id', flat=True)[:300])
        candidats += list(QuestionProgress.objects.filter(content_type=ct, object_id__in=content_ids, status='success')
                          .order_by('-assessed_at').values_list('user_id', flat=True)[:300])
        candidats = list(dict.fromkeys(c for c in candidats if c not in ids and c != author_id))
        if candidats:
            depuis = timezone.now() - timedelta(days=1)
            sollicites = set(Notification.objects.filter(recipient_id__in=candidats,
                                                         kind=Notification.KIND_DISCUSSION, created_at__gte=depuis)
                             .values('recipient_id').annotate(n=Count('id')).filter(n__gte=MAX_PAR_JOUR)
                             .values_list('recipient_id', flat=True))
            ids |= set([c for c in candidats if c not in sollicites][:MAX_AIDANTS])
    ids.discard(author_id)
    return ids


def notify_new_discussion(discussion):
    common = dict(target=target(discussion), title=discussion.title, link=link(discussion), comment_id=None,
                  author_id=discussion.author_id, text=plain_text(discussion.body) or discussion.title)
    mentions = mentioned_ids(discussion.body, discussion.author_id)
    n = notify(**common, participants=aidants(discussion) - mentions, kind=Notification.KIND_DISCUSSION)
    return n + notify(**common, participants=mentions, kind=Notification.KIND_MENTION)


def notify_new_comment(discussion):
    content = contenu_de(discussion)
    common = dict(target=target(discussion), title=content.title, link=link(discussion), comment_id=None,
                  author_id=discussion.author_id, text=plain_text(discussion.body) or content.title)
    mentions = mentioned_ids(discussion.body, discussion.author_id)
    participants = encadrants(discussion) | content_participants(content)
    n = notify(**common, participants=participants - mentions, kind=Notification.KIND_COMMENT)
    return n + notify(**common, participants=mentions, kind=Notification.KIND_MENTION)


def notify_new_reply(reply):
    discussion = reply.discussion
    common = dict(target=target(discussion), title=titre(discussion), link=link(discussion), comment_id=reply.id,
                  author_id=reply.author_id, text=plain_text(reply.body))
    mentions = mentioned_ids(reply.body, reply.author_id)
    followers = set(Follow.objects.filter(discussion=discussion).values_list('user_id', flat=True))
    if reply.reply_to_id:
        followers.add(reply.reply_to.author_id)
    # Sous un contenu : « a répondu à ton commentaire », pour celui à qui s'adresse la réponse.
    vise = None
    if discussion.genre == COMMENTAIRE:
        vise = reply.reply_to.author_id if reply.reply_to_id else discussion.author_id
        vise = None if vise in mentions else vise
    n = notify(**common, participants=followers - mentions, reply_to=vise, kind=Notification.KIND_REPONSE)
    return n + notify(**common, participants=mentions, kind=Notification.KIND_MENTION)


def later(fn, obj):
    """Après validation de la transaction, sans jamais faire échouer la publication du message."""
    def run():
        try:
            fn(obj)
        except Exception:
            logger.exception('Discussions : notifications en échec pour %s %s', type(obj).__name__, obj.pk)
    transaction.on_commit(run)
