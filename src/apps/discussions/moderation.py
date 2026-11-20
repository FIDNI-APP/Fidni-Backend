"""Protection contre les comptes créés pour troller (20/11/2026, Natsu : un troll recrée des comptes avec de vraies
adresses Gmail, la vérification de l'e-mail ne l'arrête pas).

1. Délai : un compte de moins de 24 h ne peut pas écrire (forum, commentaire, réponse, solution proposée) ; il peut
   tout de même faire les exercices.
2. Premiers messages à valider : tant qu'un membre n'a pas 3 messages validés (forum, commentaires, réponses), son
   nouveau message est enregistré `en_attente` : visible de lui seul (« En attente de validation ») et de l'équipe,
   sans notification ; l'équipe l'accepte ou le refuse dans Pilotage › Messages à valider (`pilotage_views.py`).
   Accepté : il apparaît, compte dans les réponses, et les notifications partent à ce moment-là.
Exemptés : l'équipe (staff, superuser) et les professeurs vérifiés (communauté, `ProfilPublic.verifie`).
Les messages en attente sont filtrés explicitement là où les messages sont montrés aux autres (`visibles`) ;
le gestionnaire par défaut ne les cache pas (suppression de compte, administration, migrations).
"""
import math
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

DELAI = timedelta(hours=24)
PREMIERS_A_VALIDER = 3


def exempte(user):
    from django.conf import settings
    if not getattr(settings, 'ANTI_TROLL', True):
        return True
    if user is None or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    from apps.communaute.models import ProfilPublic
    return ProfilPublic.objects.filter(user=user, verifie=True).exists()


def refus_compte_recent(user):
    """Corps de la réponse 403 si le compte a moins de 24 h, sinon None."""
    if exempte(user) or not user.date_joined:
        return None
    reste = user.date_joined + DELAI - timezone.now()
    if reste <= timedelta(0):
        return None
    heures = max(1, math.ceil(reste.total_seconds() / 3600))
    return {'error': f'Ton compte est tout neuf : tu pourras écrire dans {heures} h. '
                     'En attendant, entraîne-toi sur les exercices.',
            'code': 'compte_recent', 'heures': heures}


def doit_valider(user):
    """True si le prochain message de ce membre doit être validé par l'équipe."""
    if exempte(user):
        return False
    from .models import Discussion, Reply
    valides = (Discussion.objects.filter(author=user, en_attente=False).count()
               + Reply.objects.filter(author=user, en_attente=False).count())
    return valides < PREMIERS_A_VALIDER


def visibles(qs, user=None):
    """Messages montrés à `user` : les validés, plus les siens en attente (tous pour l'équipe)."""
    if user is not None and user.is_authenticated:
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(Q(en_attente=False) | Q(author=user))
    return qs.filter(en_attente=False)
