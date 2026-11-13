"""Règles de la communauté : réglages du profil public, protection des mineurs, abonnements, blocages, notifications.

Protection des mineurs (décidé le 08/11/2026) :
- un élève mineur, ou dont la date de naissance est inconnue, valide ses abonnés par défaut ;
- les autres ne voient ni sa ville, ni ses listes d'abonnés tant qu'ils ne sont pas abonnés acceptés ;
- s'abonner seul ne donne pas le droit d'écrire : il faut être abonnés mutuels (apps/messagerie, 13/11/2026) ; le nom complet et l'établissement restent privés pour
  tous (users/serializers.py).
"""
import logging

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.notifications.models import Notification
from apps.users.identity import est_mineur

from .models import BANNIERES, Abonnement, Blocage, ProfilPublic

logger = logging.getLogger('django')


def role(user):
    profile = getattr(user, 'profile', None)
    if user.is_staff or user.is_superuser:
        return 'equipe'
    if profile is not None and profile.user_type == 'teacher':
        return 'prof'
    return 'eleve'


def banniere_par_defaut(user):
    return BANNIERES[sum(map(ord, user.username)) % len(BANNIERES)]


def defauts(user):
    return {'abonnes_a_valider': est_mineur(user)}


def profil_public(user, creer=False):
    """Réglages du profil public. Sans ligne en base : valeurs par défaut du compte (pas enregistrées, sauf creer).

    L'objet par défaut est construit avec `user_id` : avec `user=`, Django le mettrait en cache sur `user.profil_public`
    et un appel suivant avec creer=True recevrait cette copie jamais enregistrée."""
    try:
        obj = user.profil_public
        if obj.pk is not None:
            return obj
    except ProfilPublic.DoesNotExist:
        pass
    if not creer:
        return ProfilPublic(user_id=user.id, **defauts(user))
    try:
        with transaction.atomic():
            obj, _ = ProfilPublic.objects.get_or_create(user=user, defaults=defauts(user))
    except IntegrityError:
        obj = ProfilPublic.objects.get(user=user)
    return obj


def bloque(a, b):
    """L'un a-t-il bloqué l'autre ? (on ne peut pas se bloquer soi-même : a et b sont deux membres différents)"""
    return Blocage.objects.filter(auteur__in=(a, b), bloque__in=(a, b)).exists()


def relation(viewer, user):
    """Ce que le visiteur connecté est pour ce membre : lui-même, abonné (accepté ou en attente), abonné à lui, bloqué."""
    connecte = bool(viewer and viewer.is_authenticated)
    if not connecte:
        return {'moi': False, 'abonne': None, 'me_suit': False, 'bloque': False, 'connecte': False}
    if viewer.id == user.id:
        return {'moi': True, 'abonne': None, 'me_suit': False, 'bloque': False, 'connecte': True}
    from apps.messagerie.regles import peut_ecrire
    liens = dict(Abonnement.objects.filter(abonne=viewer, suivi=user).values_list('suivi_id', 'statut'))
    me_suit = Abonnement.objects.filter(abonne=user, suivi=viewer, statut=Abonnement.ACCEPTE).exists()
    # Messages, appels, travail à plusieurs : seulement entre abonnés mutuels (apps/messagerie/regles.py).
    return {'moi': False, 'abonne': liens.get(user.id), 'me_suit': me_suit,
            'bloque': Blocage.objects.filter(auteur=viewer, bloque=user).exists(), 'connecte': True,
            'peut_ecrire': peut_ecrire(viewer, user)}


def voit_listes(viewer, user, reglages):
    """Listes d'abonnés et d'abonnements : publiques, sauf pour un profil qui valide ses abonnés (le propriétaire et ses
    abonnés acceptés les voient)."""
    if viewer and viewer.is_authenticated and (viewer.id == user.id or viewer.is_staff):
        return True
    if not reglages.abonnes_a_valider:
        return True
    return bool(viewer and viewer.is_authenticated and Abonnement.objects.filter(
        abonne=viewer, suivi=user, statut=Abonnement.ACCEPTE).exists())


class Refus(Exception):
    def __init__(self, message, code, status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def suivre(viewer, user):
    """S'abonner (ou le demander) → statut. Prévient le membre suivi."""
    if viewer.id == user.id:
        raise Refus('Tu ne peux pas t’abonner à toi-même.', 'soi-meme')
    if bloque(viewer, user):
        raise Refus('Abonnement impossible.', 'bloque', 403)
    reglages = profil_public(user)
    statut = Abonnement.EN_ATTENTE if reglages.abonnes_a_valider else Abonnement.ACCEPTE
    try:
        with transaction.atomic():
            abo, cree = Abonnement.objects.get_or_create(abonne=viewer, suivi=user, defaults={'statut': statut})
    except IntegrityError:
        abo, cree = Abonnement.objects.get(abonne=viewer, suivi=user), False
    if cree:
        kind = Notification.KIND_DEMANDE if abo.statut == Abonnement.EN_ATTENTE else Notification.KIND_ABONNE
        _notifier_abonnement(user, viewer, kind)
    return abo.statut


def ne_plus_suivre(viewer, user):
    n, _ = Abonnement.objects.filter(abonne=viewer, suivi=user).delete()
    if n:
        # Demande annulée avant d'être vue : la notification de demande disparaît aussi.
        Notification.objects.filter(recipient=user, kind=Notification.KIND_DEMANDE, actor=viewer,
                                    read_at__isnull=True).delete()
    return bool(n)


def accepter(owner, demandeur):
    n = Abonnement.objects.filter(abonne=demandeur, suivi=owner, statut=Abonnement.EN_ATTENTE).update(
        statut=Abonnement.ACCEPTE)
    if n:
        _notifier_abonnement(demandeur, owner, Notification.KIND_ACCEPTE)
    return bool(n)


def refuser(owner, demandeur):
    n, _ = Abonnement.objects.filter(abonne=demandeur, suivi=owner, statut=Abonnement.EN_ATTENTE).delete()
    return bool(n)


def retirer(owner, abonne):
    n, _ = Abonnement.objects.filter(abonne=abonne, suivi=owner).delete()
    return bool(n)


def bloquer(owner, user):
    if owner.id == user.id:
        raise Refus('Tu ne peux pas te bloquer toi-même.', 'soi-meme')
    Blocage.objects.get_or_create(auteur=owner, bloque=user)
    Abonnement.objects.filter(abonne__in=(owner, user), suivi__in=(owner, user)).delete()


def debloquer(owner, user):
    Blocage.objects.filter(auteur=owner, bloque=user).delete()


def accepter_tout(owner):
    """Le membre ne valide plus ses abonnés : les demandes en attente sont acceptées."""
    demandeurs = list(Abonnement.objects.filter(suivi=owner, statut=Abonnement.EN_ATTENTE).values_list('abonne_id', flat=True))
    Abonnement.objects.filter(suivi=owner, statut=Abonnement.EN_ATTENTE).update(statut=Abonnement.ACCEPTE)
    for d in User.objects.filter(id__in=demandeurs):
        _notifier_abonnement(d, owner, Notification.KIND_ACCEPTE)


def _actif(user):
    from apps.users.account_deletion import DELETED_USERNAME
    return user.is_active and user.username != DELETED_USERNAME


def _notifier_abonnement(destinataire, acteur, kind):
    """« X te suit », « X demande à te suivre », « X a accepté ta demande ». Plusieurs nouveaux abonnés avant lecture :
    une seule notification (« et N autres »)."""
    if not _actif(destinataire):
        return
    now = timezone.now()
    titres = {Notification.KIND_ABONNE: 'Nouvel abonné', Notification.KIND_DEMANDE: 'Demande d’abonnement',
              Notification.KIND_ACCEPTE: 'Demande acceptée'}
    lien = '/membres?onglet=abonnes' if kind != Notification.KIND_ACCEPTE else f'/profile/{acteur.username}'
    target = f'abonnes:{destinataire.id}' if kind != Notification.KIND_ACCEPTE else f'profil:{acteur.id}'
    n = Notification.objects.filter(recipient=destinataire, kind=kind, target=target, read_at__isnull=True).first()
    if n and kind != Notification.KIND_ACCEPTE:
        n.count += 1
        n.actor, n.updated_at = acteur, now
        n.save(update_fields=['count', 'actor', 'updated_at'])
        return
    Notification.objects.create(recipient=destinataire, kind=kind, target=target, title=titres[kind], link=lien,
                                actor=acteur, excerpt='', updated_at=now)


def notifier_badges(user, gagnes):
    """Une notification par palier gagné, vers les badges du profil."""
    from .badges import PALIERS, PAR_ID, texte_seuil
    if not _actif(user):
        return
    now = timezone.now()
    Notification.objects.bulk_create([
        Notification(recipient=user, kind=Notification.KIND_BADGE, target=f'badge:{badge}:{palier}',
                     title=f'{PAR_ID[badge]["nom"]} · {PALIERS[palier]}'[:200], link=f'/profile/{user.username}#badges',
                     excerpt=texte_seuil(badge, PAR_ID[badge]['paliers'][palier - 1]), updated_at=now)
        for badge, palier in gagnes
    ])


def later(fn, *args):
    """Après validation de la transaction, sans jamais faire échouer l'action qui l'a déclenché."""
    def run():
        try:
            fn(*args)
        except Exception:
            logger.exception('Communauté : %s en échec', getattr(fn, '__name__', fn))
    transaction.on_commit(run)
