"""Conformité RGPD : version des conditions acceptées, export des données, durées de conservation.

Cadre retenu (2026-09-28) : Fidni est édité par un particulier résidant en France, donc
soumis au RGPD (autorité : CNIL), même si les élèves visés sont au Maroc. La loi
marocaine 09-08 ne s'applique qu'à un responsable établi au Maroc ou qui y traite des
données : à revoir si l'hébergement ou l'éditeur change de pays.
"""
from datetime import timedelta

from django.apps import apps
from django.contrib.auth.models import User
from django.core import serializers
from django.utils import timezone

# À changer à chaque modification des CGU ou de la politique de confidentialité :
# les comptes existants devront les accepter de nouveau.
TERMS_VERSION = '2026-09-29.2'  # 09-28 .2 : AdSense ; .3 : annonces personnalisées ; 09-29 : hébergeur OVH au lieu d'AWS ; .2 : date de naissance

# Journaux techniques (adresses IP, requêtes) : la CNIL recommande 6 mois à 1 an.
LOG_RETENTION = timedelta(days=180)
# Comptes sans connexion depuis ce délai : supprimés (contributions conservées).
INACTIVE_ACCOUNT_RETENTION = timedelta(days=3 * 365)

# Relations exclues de l'export : jetons de session (secrets) et journal de l'admin Django.
_EXPORT_SKIP = {'token_blacklist.OutstandingToken', 'admin.LogEntry'}


def accept_terms(profile):
    profile.terms_accepted_at = timezone.now()
    profile.terms_version = TERMS_VERSION
    profile.save(update_fields=['terms_accepted_at', 'terms_version'])


def export_user_data(user):
    """Toutes les données rattachées au compte (droit d'accès et de portabilité, art. 15 et 20)."""
    data = {
        'export': {'date': timezone.now().isoformat(), 'site': 'https://fidni.fr'},
        'compte': {
            'nom_utilisateur': user.username, 'email': user.email,
            'prenom': user.first_name, 'nom': user.last_name,
            'inscription': user.date_joined.isoformat(),
            'derniere_connexion': user.last_login.isoformat() if user.last_login else None,
        },
    }
    for model in apps.get_models():
        label = model._meta.label
        if label in _EXPORT_SKIP or model is User:
            continue
        for field in model._meta.get_fields():
            if getattr(field, 'related_model', None) is User and field.concrete and (field.many_to_one or field.one_to_one):
                qs = model.objects.filter(**{field.name: user})
                if qs.exists():
                    rows = serializers.serialize('python', qs)
                    data.setdefault(label, []).extend(
                        {'id': r['pk'], **{k: v for k, v in r['fields'].items() if k != 'password'}} for r in rows
                    )
    return data


def purge_old_logs():
    """Supprime les journaux techniques plus anciens que LOG_RETENTION. Renvoie le nombre supprimé."""
    from apps.logging.models import APILog, ErrorLog, PageView, SystemEvent, UserInteraction, UserSession
    cutoff = timezone.now() - LOG_RETENTION
    total = 0
    for model, field in ((APILog, 'timestamp'), (ErrorLog, 'last_seen'), (PageView, 'timestamp'),
                         (SystemEvent, 'timestamp'), (UserInteraction, 'timestamp'), (UserSession, 'started_at')):
        if field in {f.name for f in model._meta.get_fields()}:
            total += model.objects.filter(**{f'{field}__lt': cutoff}).delete()[0]
    return total
