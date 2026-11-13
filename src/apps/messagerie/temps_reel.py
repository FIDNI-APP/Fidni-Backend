"""Envoi d'un événement aux navigateurs ouverts des membres (WebSocket, consumers.py), depuis une vue (synchrone).

Chaque connexion WebSocket d'un membre rejoint le groupe « u<id> » ; un événement est un dict JSON avec `type`.
Si Redis ne répond pas, l'action (message enregistré…) n'échoue pas : le navigateur le verra à sa prochaine lecture.
"""
import logging

from asgiref.sync import async_to_sync
from django.db import transaction

logger = logging.getLogger('django')


def groupe(user_id):
    return f'u{user_id}'


def _couche():
    from channels.layers import get_channel_layer
    return get_channel_layer()


def envoyer(user_ids, donnees):
    """Envoie `donnees` à chaque membre (toutes ses connexions), après validation de la transaction."""
    ids = sorted({int(i) for i in user_ids})
    if not ids:
        return

    def run():
        try:
            couche = _couche()
            if couche is None:
                return
            for uid in ids:
                async_to_sync(couche.group_send)(groupe(uid), {'type': 'evenement', 'donnees': donnees})
        except Exception:
            logger.warning('Messagerie : envoi en temps réel impossible (%s)', donnees.get('type'), exc_info=True)

    transaction.on_commit(run)
