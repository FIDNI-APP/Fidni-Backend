# Content structures live on the Content row itself (json_content JSONB),
# so nothing needs cleaning up on delete anymore.
from django.db import transaction
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from apps.things.models import Content
from config import indexnow


def _renumeroter(sender, instance, action, reverse, pk_set, **kwargs):
    """Niveaux ou chapitres d'un contenu changés : ses numéros par chapitre suivent (things/numeros.py), une fois la
    transaction validée (l'import pose d'abord les niveaux, puis les chapitres)."""
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return
    from apps.things.numeros import numeroter
    ids = [instance.pk] if not reverse else list(pk_set or [])
    for cid in ids:
        transaction.on_commit(lambda cid=cid: numeroter(cid))


m2m_changed.connect(_renumeroter, sender=Content.chapters.through, dispatch_uid='things_numeros_chapitres')
m2m_changed.connect(_renumeroter, sender=Content.class_levels.through, dispatch_uid='things_numeros_niveaux')


@receiver(post_save, sender=Content, dispatch_uid='things_numeros_examen')
def _renumeroter_examen(sender, instance, created, update_fields=None, **kwargs):
    """Un devoir passé en « Bac national » (ou l'inverse) perd (ou gagne) ses numéros ; à la création, ce sont les
    niveaux et chapitres posés ensuite qui numérotent."""
    if created or instance.type != Content.TYPE_EXAM:
        return
    if update_fields is not None and 'is_national_exam' not in update_fields:
        return
    from apps.things.numeros import numeroter
    transaction.on_commit(lambda: numeroter(instance.pk))


@receiver(post_save, sender=Content, dispatch_uid='things_indexnow')
def announce_to_search_engines(sender, instance, **kwargs):
    """Contenu créé ou modifié : on prévient les moteurs IndexNow (Bing…), une fois la transaction validée."""
    url = indexnow.content_url(instance)
    if url:
        transaction.on_commit(lambda: indexnow.queue(url))
