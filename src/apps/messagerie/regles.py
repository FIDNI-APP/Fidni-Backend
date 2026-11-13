"""Qui peut écrire à qui (décision de Natsu, 13/11/2026) : seulement entre **abonnés mutuels** (chacun suit l'autre,
abonnements acceptés), jamais si l'un a bloqué l'autre, jamais avec un compte désactivé ou supprimé.

Une conversation directe dont les deux membres ne sont plus mutuels reste lisible mais n'accepte plus de message ni
d'appel. Dans un groupe : chaque membre ajouté doit être mutuel avec celui qui l'ajoute et n'avoir de blocage avec
personne du groupe ; on y écrit tant qu'on en fait partie. Un blocage apparu ensuite fait quitter au membre bloqué
les groupes qu'il partage avec celui qui l'a bloqué (signals.py).
"""
from django.contrib.auth.models import User
from django.db.models import Q

from apps.communaute.models import Abonnement, Blocage

from .models import Conversation, Participant


def _actif(user):
    from apps.users.account_deletion import DELETED_USERNAME
    return bool(user and user.is_active and user.username != DELETED_USERNAME)


def mutuels_ids(user):
    """Ids des abonnés mutuels du membre (abonnements acceptés dans les deux sens), sans blocage entre eux."""
    suit = set(Abonnement.objects.filter(abonne=user, statut=Abonnement.ACCEPTE).values_list('suivi_id', flat=True))
    suivi_par = set(Abonnement.objects.filter(suivi=user, statut=Abonnement.ACCEPTE).values_list('abonne_id', flat=True))
    ids = suit & suivi_par
    if not ids:
        return set()
    bloques = set(Blocage.objects.filter(auteur=user, bloque_id__in=ids).values_list('bloque_id', flat=True))
    bloques |= set(Blocage.objects.filter(bloque=user, auteur_id__in=ids).values_list('auteur_id', flat=True))
    return ids - bloques


def mutuels(user):
    from apps.users.account_deletion import DELETED_USERNAME
    return User.objects.filter(id__in=mutuels_ids(user), is_active=True).exclude(username=DELETED_USERNAME)


def peut_ecrire(a, b):
    """a peut-il écrire à b (et l'appeler, l'inviter) ?"""
    if not (_actif(a) and _actif(b)) or a.id == b.id:
        return False
    n = Abonnement.objects.filter(
        Q(abonne=a, suivi=b) | Q(abonne=b, suivi=a), statut=Abonnement.ACCEPTE).count()
    if n < 2:
        return False
    return not Blocage.objects.filter(auteur__in=(a, b), bloque__in=(a, b)).exists()


def bloque_entre(user, autres_ids):
    return Blocage.objects.filter(
        Q(auteur=user, bloque_id__in=autres_ids) | Q(bloque=user, auteur_id__in=autres_ids)).exists()


def participation(user, conversation_id):
    """Participation active du membre à cette conversation, sinon None."""
    if not (user and user.is_authenticated):
        return None
    return (Participant.objects.select_related('conversation')
            .filter(conversation_id=conversation_id, user=user, parti_le__isnull=True).first())


def actifs(conversation):
    return list(User.objects.filter(participations_messagerie__conversation=conversation,
                                    participations_messagerie__parti_le__isnull=True))


def peut_parler(user, conversation):
    """Peut-il écrire et appeler dans cette conversation (il en fait partie) ?

    Directe : l'autre doit être encore un abonné mutuel. Groupe : il reste au moins une autre personne active."""
    if not _actif(user):
        return False
    autres = [u for u in actifs(conversation) if u.id != user.id]
    if conversation.type == Conversation.DIRECTE:
        return len(autres) == 1 and peut_ecrire(user, autres[0])
    return any(_actif(u) for u in autres)


def raison_lecture_seule(user, conversation):
    """Pourquoi on ne peut plus écrire ici (texte pour l'interface), ou '' si on peut."""
    if peut_parler(user, conversation):
        return ''
    if conversation.type == Conversation.DIRECTE:
        return 'Vous ne vous suivez plus tous les deux : la conversation est en lecture seule.'
    return 'Plus personne d’autre dans ce groupe.'
