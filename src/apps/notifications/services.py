"""Qui prévenir quand quelqu'un commente, et comment.

« A interagi avec le contenu » = l'a publié, commenté, aimé (ou pas), enregistré, marqué réussi ou à
revoir, a évalué une de ses questions, proposé une solution, ou y a travaillé au moins 2 minutes. Un
simple passage sur la page ne suffit pas : sinon chaque commentaire préviendrait tous les visiteurs.
L'auteur du commentaire n'est jamais prévenu ; l'auteur du commentaire auquel on répond reçoit une
« réponse » plutôt qu'un « nouveau commentaire ».
"""
import logging

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone

from .models import Notification

logger = logging.getLogger('django')
EXCERPT = 140
MIN_STUDY_SECONDS = 120
TYPE_PATH = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}


def excerpt(text):
    text = ' '.join((text or '').split())
    return text if len(text) <= EXCERPT else text[:EXCERPT - 1].rstrip() + '…'


def content_participants(content):
    """Membres qui ont interagi avec un exercice, une leçon ou un examen."""
    from apps.interactions.models import Complete, QuestionProgress, Save, StudyTimeDay, Vote
    from apps.things.models import Comment, Content, ProposedSolution

    ct = ContentType.objects.get_for_model(Content)
    sid = str(content.id)  # object_id des votes, favoris et résultats : CharField (CLAUDE.md)
    ids = {content.author_id}
    ids |= set(Comment.objects.filter(content_item=content).values_list('author_id', flat=True))
    ids |= set(Vote.objects.filter(content_type=ct, object_id=sid).exclude(value=0).values_list('user_id', flat=True))
    ids |= set(Save.objects.filter(content_type=ct, object_id=sid).values_list('user_id', flat=True))
    ids |= set(Complete.objects.filter(content_type=ct, object_id=sid).values_list('user_id', flat=True))
    ids |= set(QuestionProgress.objects.filter(content_type=ct, object_id=content.id).values_list('user_id', flat=True))
    ids |= set(ProposedSolution.objects.filter(content_item=content).values_list('author_id', flat=True))
    ids |= set(StudyTimeDay.objects.filter(object_id=content.id).values('user_id').annotate(s=Sum('seconds'))
               .filter(s__gte=MIN_STUDY_SECONDS).values_list('user_id', flat=True))
    return ids


def concours_participants(target_type, obj):
    """Membres qui ont interagi avec un sujet de concours (ou une fiche méthode)."""
    from apps.concours.models import ConcoursComment, ConcoursExam, SimulationSession
    from apps.interactions.models import Save, Vote

    ct = ContentType.objects.get_for_model(type(obj))
    sid = str(obj.id)
    ids = set(ConcoursComment.objects.filter(target_type=target_type, target_id=obj.id).values_list('author_id', flat=True))
    ids |= set(Save.objects.filter(content_type=ct, object_id=sid).values_list('user_id', flat=True))
    if isinstance(obj, ConcoursExam):
        ids.add(obj.created_by_id)
        ids |= set(SimulationSession.objects.filter(exam=obj).values_list('user_id', flat=True))
    else:
        ids |= set(Vote.objects.filter(content_type=ct, object_id=sid).exclude(value=0).values_list('user_id', flat=True))
    return ids


def notify(*, target, title, link, comment_id, author_id, text, participants, reply_to=None):
    """Prévient les participants (regroupé par contenu tant que ce n'est pas lu). Renvoie le nombre de membres prévenus."""
    from apps.users.account_deletion import DELETED_USERNAME

    reply_to = reply_to if reply_to and reply_to != author_id else None
    wanted = (set(participants) | ({reply_to} if reply_to else set())) - {author_id, None}
    active = set(User.objects.filter(id__in=wanted, is_active=True).exclude(username=DELETED_USERNAME)
                 .values_list('id', flat=True))
    groups = {Notification.KIND_COMMENT: active - {reply_to}}
    if reply_to in active:
        groups[Notification.KIND_REPLY] = {reply_to}
    now, short = timezone.now(), excerpt(text)
    for kind, ids in groups.items():
        if not ids:
            continue
        unread = {n.recipient_id: n for n in Notification.objects.filter(
            recipient_id__in=ids, target=target, kind=kind, read_at__isnull=True)}
        for n in unread.values():
            n.count += 1
            n.comment_id, n.actor_id, n.excerpt, n.title, n.updated_at = comment_id, author_id, short, title[:200], now
        Notification.objects.bulk_update(list(unread.values()), ['count', 'comment_id', 'actor', 'excerpt', 'title', 'updated_at'])
        Notification.objects.bulk_create([
            Notification(recipient_id=i, kind=kind, target=target, title=title[:200], link=link, comment_id=comment_id,
                         actor_id=author_id, excerpt=short, updated_at=now)
            for i in ids - set(unread)
        ])
    return len(active)


def notify_content_comment(comment):
    content = comment.content_item
    parent_author = comment.parent.author_id if comment.parent_id else None
    return notify(
        target=f'content:{content.id}', title=content.title, link=f'/{TYPE_PATH.get(content.type, "exercises")}/{content.id}',
        comment_id=comment.id, author_id=comment.author_id, text=comment.content,
        participants=content_participants(content), reply_to=parent_author,
    )


def notify_concours_comment(comment):
    from apps.concours.models import ConcoursComment, ConcoursExam, ConcoursTip

    is_exam = comment.target_type == ConcoursComment.TARGET_EXAM
    obj = (ConcoursExam if is_exam else ConcoursTip).objects.filter(id=comment.target_id).first()
    if obj is None:
        return 0
    parent_author = comment.parent.author_id if comment.parent_id else None
    return notify(
        target=f'concours-{comment.target_type}:{obj.id}',
        title=obj.display_title if is_exam else obj.title,
        link=f'/concours/{"exams" if is_exam else "tips"}/{obj.id}',
        comment_id=comment.id, author_id=comment.author_id, text=comment.content,
        participants=concours_participants(comment.target_type, obj), reply_to=parent_author,
    )
