"""Un blocage fait quitter au membre bloqué les groupes qu'il partage avec celui qui l'a bloqué (regles.py)."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.communaute.models import Blocage


@receiver(post_save, sender=Blocage)
def blocage_quitte_groupes(sender, instance, created, **kwargs):
    if not created:
        return
    from . import services
    from .models import Conversation, Participant
    communs = (Participant.objects.filter(user_id=instance.auteur_id, parti_le__isnull=True,
                                          conversation__type=Conversation.GROUPE)
               .values_list('conversation_id', flat=True))
    for conv in Conversation.objects.filter(id__in=list(communs), participants__user_id=instance.bloque_id,
                                            participants__parti_le__isnull=True).distinct():
        services.quitter(conv, instance.bloque)
