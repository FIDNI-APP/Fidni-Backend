# Content structures live on the Content row itself (json_content JSONB),
# so nothing needs cleaning up on delete anymore.
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.things.models import Content
from config import indexnow


@receiver(post_save, sender=Content, dispatch_uid='things_indexnow')
def announce_to_search_engines(sender, instance, **kwargs):
    """Contenu créé ou modifié : on prévient les moteurs IndexNow (Bing…), une fois la transaction validée."""
    url = indexnow.content_url(instance)
    if url:
        transaction.on_commit(lambda: indexnow.queue(url))
