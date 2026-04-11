import logging
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Content
from .content_store import delete_structure, model_type, display_id_for

logger = logging.getLogger('django')


def _delete(sender, instance, **kwargs):
    did = display_id_for(instance)
    if did is None:
        return
    try:
        delete_structure(model_type(instance), did)
    except Exception as e:
        logger.error(f"MongoDB delete failed for {model_type(instance)} {did}: {e}")


post_delete.connect(_delete, sender=Content)
