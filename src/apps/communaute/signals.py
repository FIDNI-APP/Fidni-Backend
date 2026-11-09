"""Badges recalculés après les actions qui font bouger leurs chiffres (badges.py), une fois la transaction validée et
sans jamais faire échouer l'action elle-même (services.later)."""
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.defis.models import TentativeDefi
from apps.interactions.models import Complete, Vote
from apps.skilliq.models import SkillAssessment
from apps.things.models import Content

from .services import later


def _badges(user_id, familles):
    from .badges import actualiser
    user = User.objects.filter(id=user_id, is_active=True).select_related('profile').first()
    if user:
        # Sans calculer « Ma progression » : remplir son cache ici le figerait avant la suite de l'action.
        actualiser(user, familles, calculer=False)


@receiver(post_save, sender=TentativeDefi)
def defi_trouve(sender, instance, **kwargs):
    if instance.statut == TentativeDefi.TROUVE:
        later(_badges, instance.user_id, ['serie', 'defis'])


@receiver(post_save, sender=Complete)
def contenu_reussi(sender, instance, **kwargs):
    if instance.status == 'success':
        later(_badges, instance.user_id, ['exercices'])


@receiver(post_save, sender=SkillAssessment)
def quiz_passe(sender, instance, **kwargs):
    later(_badges, instance.user_id, ['quiz', 'approfondi'])


@receiver(post_save, sender=Content)
def contenu_publie(sender, instance, created, **kwargs):
    if created and instance.author_id:
        later(_badges, instance.author_id, ['auteur'])


@receiver(post_save, sender=Vote)
def vote_utile(sender, instance, **kwargs):
    """« Utile » reçu sur une discussion ou une réponse : badge « Entraide » de son auteur."""
    if instance.value != Vote.UP:
        return
    from apps.discussions.models import Discussion, Reply
    models = {ContentType.objects.get_for_model(m).id: m for m in (Discussion, Reply)}
    model = models.get(instance.content_type_id)
    if model is None or not str(instance.object_id).isdigit():
        return
    auteur = model.objects.filter(id=int(instance.object_id)).values_list('author_id', flat=True).first()
    if auteur and auteur != instance.user_id:
        later(_badges, auteur, ['entraide'])
