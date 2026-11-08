"""Discussion ou réponse supprimée : ses notifications ne mèneraient plus nulle part."""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.notifications.models import Notification

from .models import Discussion, Reply


@receiver(post_delete, sender=Discussion, dispatch_uid='discussions_discussion_deleted')
def on_discussion_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'discussion:{instance.pk}').delete()


@receiver(post_delete, sender=Reply, dispatch_uid='discussions_reply_deleted')
def on_reply_deleted(sender, instance, **kwargs):
    Notification.objects.filter(target=f'discussion:{instance.discussion_id}', comment_id=instance.pk, count=1).delete()
