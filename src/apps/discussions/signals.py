"""Discussion ou réponse supprimée : ses notifications ne mèneraient plus nulle part. Contenu supprimé : ses commentaires
partent avec lui (comme things.Comment) ; une discussion du forum reste, sans ce tag."""
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from apps.notifications.models import Notification
from apps.things.models import Content

from .models import COMMENTAIRE, Discussion, Reply
from .services import delete_files


@receiver(post_delete, sender=Discussion, dispatch_uid='discussions_discussion_deleted')
def on_discussion_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'discussion:{instance.pk}').delete()


@receiver(post_delete, sender=Reply, dispatch_uid='discussions_reply_deleted')
def on_reply_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'discussion:{instance.discussion_id}', comment_id=instance.pk, count=1).delete()


@receiver(pre_delete, sender=Content, dispatch_uid='discussions_content_deleted')
def on_content_deleted(sender, instance, **kwargs):
    comments = list(Discussion.objects.filter(genre=COMMENTAIRE, contents=instance))
    delete_files([(Discussion, [d.id for d in comments]),
                  (Reply, list(Reply.objects.filter(discussion__in=comments).values_list('id', flat=True)))])
    for d in comments:
        d.delete()
