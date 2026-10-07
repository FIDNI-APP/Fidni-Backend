"""Un commentaire publié → notifications (une fois la transaction validée, sans jamais bloquer le commentaire)."""
import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.concours.models import ConcoursComment, ConcoursExam, ConcoursTip
from apps.things.models import Comment, Content

from .models import Notification

logger = logging.getLogger('django')


def _later(fn, model, pk):
    def run():
        try:
            obj = model.objects.select_related('parent').filter(pk=pk).first()
            if obj is not None:
                fn(obj)
        except Exception:  # une notification ratée ne doit jamais empêcher de commenter
            logger.exception('Notifications : échec pour %s %s', model.__name__, pk)
    transaction.on_commit(run)


@receiver(post_save, sender=Comment, dispatch_uid='notifications_comment')
def on_comment(sender, instance, created, **kwargs):
    if created:
        from .services import notify_content_comment
        _later(notify_content_comment, Comment, instance.pk)


@receiver(post_save, sender=ConcoursComment, dispatch_uid='notifications_concours_comment')
def on_concours_comment(sender, instance, created, **kwargs):
    if created:
        from .services import notify_concours_comment
        _later(notify_concours_comment, ConcoursComment, instance.pk)


# Contenu ou commentaire supprimé : ses notifications ne mèneraient plus nulle part.
@receiver(post_delete, sender=Content, dispatch_uid='notifications_content_deleted')
def on_content_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'content:{instance.pk}').delete()


@receiver(post_delete, sender=ConcoursExam, dispatch_uid='notifications_concours_exam_deleted')
def on_concours_exam_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'concours-exam:{instance.pk}').delete()


@receiver(post_delete, sender=ConcoursTip, dispatch_uid='notifications_concours_tip_deleted')
def on_concours_tip_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'concours-tip:{instance.pk}').delete()


@receiver(post_delete, sender=Comment, dispatch_uid='notifications_comment_deleted')
def on_comment_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'content:{instance.content_item_id}', comment_id=instance.pk, count=1).delete()


@receiver(post_delete, sender=ConcoursComment, dispatch_uid='notifications_concours_comment_deleted')
def on_concours_comment_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'concours-{instance.target_type}:{instance.target_id}',
                                comment_id=instance.pk, count=1).delete()
