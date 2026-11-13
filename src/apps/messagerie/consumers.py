"""WebSocket /ws/?ticket=… : une connexion par onglet ouvert d'un membre connecté.

Reçoit les événements de ses conversations (groupe « u<id> », temps_reel.envoyer) et porte ce qui doit aller vite :
« en train d'écrire », où on en est dans une salle de travail, et la mise en relation des appels (WebRTC) :

  client → serveur                                   serveur → client
  {type: 'tape', conversation}                       {type: 'tape', conversation, user}
  {type: 'salle.question', conversation, question}   {type: 'salle.question', conversation, user, question}
  {type: 'appel.rejoindre', conversation, video}     {type: 'appel.rejoint', conversation, appel, moi, pairs}
  {type: 'appel.signal', appel, vers, donnees}       {type: 'appel.signal', appel, de, user, donnees}
  {type: 'appel.quitter', appel}                     {type: 'appel.maj', conversation, appel} (à tous les membres)
  {type: 'appel.refuser', conversation}              {type: 'appel.refus', conversation, user}
  {type: 'ping'}                                     {type: 'pong'}

Les signaux (offres, réponses, candidats ICE) ne vont que d'une présence à une autre du MÊME appel en cours ; chaque
présence est une connexion (un membre peut être sur deux appareils). À la déconnexion, ses présences sont retirées.
"""
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import User

from . import regles, services
from .models import Participant, PresenceAppel
from .temps_reel import envoyer, groupe

SIGNAL_MAX = 64 * 1024     # une offre SDP fait quelques Ko
DEBIT = 80                 # messages reçus par 10 s et par connexion (les candidats ICE arrivent par rafales)


def origine_ok(scope):
    """Le navigateur annonce la page qui ouvre la connexion : seulement le site (et le local en développement)."""
    if getattr(settings, 'DEBUG', False):
        return True
    origines = set(getattr(settings, 'CORS_ALLOWED_ORIGINS', []))
    origine = dict(scope.get('headers') or []).get(b'origin', b'').decode()
    return origine in origines


@database_sync_to_async
def _user(uid):
    from apps.users.account_deletion import DELETED_USERNAME
    return User.objects.filter(pk=uid, is_active=True).exclude(username=DELETED_USERNAME).first()


@database_sync_to_async
def _autres_participants(user, conversation_id):
    """Ids des autres membres actifs, si le membre fait partie de la conversation ; sinon None."""
    if regles.participation(user, conversation_id) is None:
        return None
    return list(Participant.objects.filter(conversation_id=conversation_id, parti_le__isnull=True)
                .exclude(user_id=user.id).values_list('user_id', flat=True))


@database_sync_to_async
def _question(user, conversation_id, question):
    p = regles.participation(user, conversation_id)
    if p is None or p.conversation.contenu_id is None:
        return None
    p.question = question
    p.save(update_fields=['question'])
    return list(Participant.objects.filter(conversation_id=conversation_id, parti_le__isnull=True)
                .exclude(user_id=user.id).values_list('user_id', flat=True))


@database_sync_to_async
def _rejoindre(user, conversation_id, canal, video):
    p = regles.participation(user, conversation_id)
    if p is None:
        raise services.Refus('Conversation introuvable.', 'introuvable', 404)
    presence, appel, autres = services.rejoindre_appel(p.conversation, user, canal, video)
    return presence, appel, [(a.id, a.user_id, a.canal) for a in autres]


@database_sync_to_async
def _quitter(canal, appel_id=None):
    services.quitter_appel(canal, appel_id)


@database_sync_to_async
def _cible(canal, appel_id, vers):
    """Canal de la présence visée, si l'émetteur et elle sont dans le même appel en cours."""
    moi = PresenceAppel.objects.filter(canal=canal, appel_id=appel_id, parti_le__isnull=True,
                                       appel__fin__isnull=True).first()
    if moi is None:
        return None, None
    cible = services.presence_dans_appel(vers, appel_id)
    if cible is None or cible.pk == moi.pk:
        return None, None
    return moi, cible.canal


@database_sync_to_async
def _refuser(user, conversation_id):
    p = regles.participation(user, conversation_id)
    if p is None:
        return
    envoyer([i for i in Participant.objects.filter(conversation_id=conversation_id, parti_le__isnull=True)
             .exclude(user_id=user.id).values_list('user_id', flat=True)],
            {'type': 'appel.refus', 'conversation': conversation_id, 'user': user.id})


class MessagerieConsumer(AsyncJsonWebsocketConsumer):
    user = None

    async def connect(self):
        from .views import lire_ticket
        if not origine_ok(self.scope):
            await self.close(code=4403)
            return
        params = parse_qs((self.scope.get('query_string') or b'').decode())
        uid = lire_ticket((params.get('ticket') or [''])[0])
        self.user = await _user(uid) if uid else None
        if self.user is None:
            await self.close(code=4401)
            return
        self.recus = []
        await self.channel_layer.group_add(groupe(self.user.id), self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if self.user is None:
            return
        await self.channel_layer.group_discard(groupe(self.user.id), self.channel_name)
        await _quitter(self.channel_name)

    def _trop(self):
        now = time.monotonic()
        self.recus = [t for t in self.recus if now - t < 10] + [now]
        return len(self.recus) > DEBIT

    @staticmethod
    def _entier(valeur):
        try:
            return int(valeur)
        except (TypeError, ValueError):
            return None

    async def receive_json(self, contenu, **kwargs):
        if not isinstance(contenu, dict) or self._trop():
            return
        t = contenu.get('type')
        conv = self._entier(contenu.get('conversation'))
        if t == 'ping':
            await self.send_json({'type': 'pong'})
        elif t == 'tape' and conv:
            autres = await _autres_participants(self.user, conv)
            for uid in autres or []:
                await self.channel_layer.group_send(groupe(uid), {'type': 'evenement', 'donnees': {
                    'type': 'tape', 'conversation': conv, 'user': self.user.id}})
        elif t == 'salle.question' and conv:
            question = str(contenu.get('question') or '')[:40]
            autres = await _question(self.user, conv, question)
            for uid in autres or []:
                await self.channel_layer.group_send(groupe(uid), {'type': 'evenement', 'donnees': {
                    'type': 'salle.question', 'conversation': conv, 'user': self.user.id, 'question': question}})
        elif t == 'appel.rejoindre' and conv:
            await self._rejoindre(conv, bool(contenu.get('video')))
        elif t == 'appel.signal':
            await self._signal(contenu)
        elif t == 'appel.quitter':
            await _quitter(self.channel_name, self._entier(contenu.get('appel')))
        elif t == 'appel.refuser' and conv:
            await _refuser(self.user, conv)

    async def _rejoindre(self, conv, video):
        try:
            presence, appel, autres = await _rejoindre(self.user, conv, self.channel_name, video)
        except services.Refus as e:
            await self.send_json({'type': 'appel.erreur', 'conversation': conv, 'detail': e.message, 'code': e.code})
            return
        # Le nouveau venu fait les offres aux présents (pairs) ; eux attendent son offre.
        await self.send_json({'type': 'appel.rejoint', 'conversation': conv, 'appel': appel.id, 'video': appel.video,
                              'moi': presence.id, 'pairs': [{'id': i, 'user': u} for i, u, _ in autres]})
        for i, u, canal in autres:
            await self.channel_layer.send(canal, {'type': 'evenement', 'donnees': {
                'type': 'appel.arrivee', 'appel': appel.id, 'conversation': conv,
                'pair': {'id': presence.id, 'user': self.user.id}}})

    async def _signal(self, contenu):
        appel, vers = self._entier(contenu.get('appel')), self._entier(contenu.get('vers'))
        donnees = contenu.get('donnees')
        if not (appel and vers and isinstance(donnees, dict)) or len(str(donnees)) > SIGNAL_MAX:
            return
        # Seulement une description de session, un candidat ICE ou l'état du micro et de la caméra : rien d'autre ne
        # passe d'un navigateur à l'autre.
        propre = {}
        if isinstance(donnees.get('description'), dict):
            d = donnees['description']
            if d.get('type') in ('offer', 'answer', 'rollback') and isinstance(d.get('sdp', ''), str):
                propre['description'] = {'type': d['type'], 'sdp': d.get('sdp', '')}
        if 'candidate' in donnees and (donnees['candidate'] is None or isinstance(donnees['candidate'], dict)):
            c = donnees['candidate']
            propre['candidate'] = None if c is None else {
                k: c.get(k) for k in ('candidate', 'sdpMid', 'sdpMLineIndex', 'usernameFragment')}
        # Micro coupé, caméra, écran partagé : pour afficher la photo au lieu d'une image noire.
        if isinstance(donnees.get('etat'), dict):
            propre['etat'] = {k: bool(donnees['etat'].get(k)) for k in ('micro', 'camera', 'ecran')}
        if not propre:
            return
        moi, canal = await _cible(self.channel_name, appel, vers)
        if canal is None:
            return
        await self.channel_layer.send(canal, {'type': 'evenement', 'donnees': {
            'type': 'appel.signal', 'appel': appel, 'de': moi.id, 'user': self.user.id, 'donnees': propre}})

    async def evenement(self, message):
        await self.send_json(message['donnees'])
