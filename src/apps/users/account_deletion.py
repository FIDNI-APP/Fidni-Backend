"""Suppression d'un compte.

Deux cas, décidés avec Natsu (2026-09-28) :
- l'utilisateur supprime lui-même son compte : ses contributions publiques (exercices,
  leçons, examens, corrections, commentaires, solutions proposées et leurs images)
  restent en ligne, attribuées à « Compte supprimé » ; tout le reste est effacé ;
- un administrateur supprime le compte (contenu inapproprié) : tout est effacé,
  contributions comprises.
"""
import logging

from django.contrib.auth.models import User
from django.db import transaction

logger = logging.getLogger('django')

# Espace et accent : impossible à choisir à l'inscription (USERNAME_RE), donc aucun
# risque de collision avec un vrai compte.
DELETED_USERNAME = 'Compte supprimé'


def deleted_account_user():
    """Compte fantôme qui reçoit les contributions des comptes supprimés (jamais connectable)."""
    user, created = User.objects.get_or_create(username=DELETED_USERNAME, defaults={'is_active': False})
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user


def is_deleted_account(user):
    return getattr(user, 'username', None) == DELETED_USERNAME


def _public_contributions():
    """(modèle, champ auteur) des contenus publics d'un compte."""
    from apps.concours.models import ConcoursComment, ConcoursExam, ConcoursTip
    from apps.things.models import Comment, Content, ProposedSolution, Solution
    return [
        (Content, 'author'), (Solution, 'author'), (Comment, 'author'), (ProposedSolution, 'author'),
        (ConcoursExam, 'created_by'), (ConcoursTip, 'created_by'), (ConcoursComment, 'author'),
    ]


def _delete_files(queryset):
    """Supprime des pièces jointes et leurs fichiers (S3 ou disque)."""
    for attachment in queryset:
        try:
            if attachment.file:
                attachment.file.delete(save=False)
        except Exception:  # un fichier déjà absent du stockage ne doit pas bloquer la suppression
            logger.warning('Fichier introuvable lors de la suppression : %s', attachment.pk)
        attachment.delete()


@transaction.atomic
def delete_account(user, *, keep_contributions):
    """Supprime `user`. Renvoie un résumé (nombre d'éléments conservés ou effacés)."""
    from apps.interactions.models import Vote
    from apps.uploads.models import FileAttachment
    from apps.authentication.jwt_revocation import revoke_all_sessions

    if is_deleted_account(user):
        raise ValueError('Le compte « Compte supprimé » ne se supprime pas.')

    summary = {}
    contributions = _public_contributions()
    if keep_contributions:
        placeholder = deleted_account_user()
        for model, field in contributions:
            summary[model.__name__] = model.objects.filter(**{field: user}).update(**{field: placeholder})
        # Images rattachées à une contribution conservée : elles restent avec elle.
        summary['fichiers conservés'] = FileAttachment.objects.filter(
            uploaded_by=user, object_id__isnull=False).update(uploaded_by=placeholder)
    else:
        # Modération : contributions supprimées. Les commentaires d'abord (leurs réponses
        # partent avec eux), puis le reste ; les fichiers de ces objets sont effacés plus bas.
        for model, field in contributions:
            qs = model.objects.filter(**{field: user})
            summary[model.__name__] = qs.count()
            qs.delete()

    # Toujours personnel : votes (leur suppression met les compteurs à jour), fichiers
    # restants, avatar, sessions.
    Vote.objects.filter(user=user).delete()
    _delete_files(FileAttachment.objects.filter(uploaded_by=user))
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.avatar_file:
        profile.avatar_file.delete(save=False)
    revoke_all_sessions(user)

    username = user.username
    user.delete()  # le reste (profil, progression, favoris, cahiers, listes…) part en cascade
    logger.info('Compte supprimé : %s (contributions %s)', username,
                'conservées' if keep_contributions else 'supprimées')
    return summary
