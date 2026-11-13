"""Messagerie et appels (13/11/2026), sur une base SQLite jetable : seulement entre abonnés mutuels (conversation
directe, groupe, invitation à travailler), lecture seule quand on ne se suit plus, non-lus, suppression, signalement,
blocage (départ des groupes communs), identifiants TURN, ticket du WebSocket, puis le WebSocket lui-même : messages en
direct, « en train d'écrire », mise en relation d'un appel (offre relayée seulement dans le même appel), fin d'appel
et compte rendu, purge des messages de plus de 12 mois, suppression de compte."""
import asyncio
import base64
import hashlib
import hmac
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-messagerie.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
os.environ.pop('REDIS_URL', None)
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
import json  # noqa: E402
from asgiref.testing import ApplicationCommunicator  # noqa: E402  (channels.testing importe daphne)
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.test import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Subject  # noqa: E402
from apps.communaute import services as communaute  # noqa: E402
from apps.communaute.models import Abonnement  # noqa: E402
from apps.messagerie import consumers  # noqa: E402
from apps.messagerie.models import Appel, Conversation, Message, Participant, SignalementMessage  # noqa: E402
from apps.messagerie.routing import websocket_urlpatterns  # noqa: E402
from apps.messagerie.views import lire_ticket  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users.account_deletion import delete_account  # noqa: E402
from channels.routing import URLRouter  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(u)
    return c


def membre(nom, **kw):
    return User.objects.create_user(nom, f'{nom}@x.fr', 'Motdepasse-solide-42', **kw)


def amis(a, b):
    for x, y in ((a, b), (b, a)):
        Abonnement.objects.update_or_create(abonne=x, suivi=y, defaults={'statut': Abonnement.ACCEPTE})


cache.clear()
equipe = membre('equipe_m', is_staff=True)
ali, badr, chama, dina, emma, farid, ghita, hind = (membre(n) for n in (
    'ali', 'badr', 'chama', 'dina', 'emma', 'farid', 'ghita', 'hind'))
amis(ali, badr)
amis(ali, emma)
amis(badr, emma)
Abonnement.objects.create(abonne=ali, suivi=chama, statut=Abonnement.ACCEPTE)  # ali suit chama, pas l'inverse
Abonnement.objects.create(abonne=dina, suivi=ali, statut=Abonnement.EN_ATTENTE)
Abonnement.objects.create(abonne=ali, suivi=dina, statut=Abonnement.ACCEPTE)  # dina : demande encore en attente
maths = Subject.objects.create(name='Maths M')
sujet = Content.objects.create(type='exam', title='Devoir surveillé n° 1', author=equipe, subject=maths, json_content={})

print('--- Qui peut écrire à qui')
r = client(ali).post('/api/messagerie/conversations/', {'membres': ['badr']}, format='json')
check('Abonnés mutuels : conversation directe créée', r.status_code == 201, r.content[:200])
directe = r.json()['id']
r2 = client(badr).post('/api/messagerie/conversations/', {'membres': ['ali']}, format='json')
check('Une seule conversation directe par paire', r2.status_code == 201 and r2.json()['id'] == directe)
check('Abonnement à sens unique : refusé', client(ali).post(
    '/api/messagerie/conversations/', {'membres': ['chama']}, format='json').status_code == 403)
check('Demande en attente : refusé', client(ali).post(
    '/api/messagerie/conversations/', {'membres': ['dina']}, format='json').status_code == 403)
check('Visiteur : refusé', client().get('/api/messagerie/conversations/').status_code in (401, 403))
check('Membre inconnu : 404', client(ali).post(
    '/api/messagerie/conversations/', {'membres': ['personne']}, format='json').status_code == 404)
profil = client(ali).get('/api/communaute/profils/badr/').json()
check('Profil : peut_ecrire vrai entre mutuels', profil.get('relation', {}).get('peut_ecrire') is True, profil.get('relation'))
check('Profil : peut_ecrire faux sinon',
      client(ali).get('/api/communaute/profils/chama/').json().get('relation', {}).get('peut_ecrire') is False)
contacts = [u['username'] for u in client(ali).get('/api/messagerie/contacts/').json()['results']]
check('Contacts = abonnés mutuels seulement', sorted(contacts) == ['badr', 'emma'], contacts)

print('--- Messages')
r = client(ali).post(f'/api/messagerie/conversations/{directe}/messages/', {'texte': 'Salut, on fait le DS ?', 'client_id': 'x1'},
                     format='json')
check('Message envoyé', r.status_code == 201 and r.json()['client_id'] == 'x1', r.content[:200])
mid = r.json()['id']
check('Message vide refusé', client(ali).post(f'/api/messagerie/conversations/{directe}/messages/', {'texte': '  '},
                                             format='json').status_code == 400)
check('Message trop long refusé', client(ali).post(f'/api/messagerie/conversations/{directe}/messages/',
                                                  {'texte': 'x' * 2001}, format='json').status_code == 400)
check('Badr a 1 conversation non lue', client(badr).get('/api/messagerie/non-lus/').json()['count'] == 1)
liste = client(badr).get('/api/messagerie/conversations/').json()['results']
check('Liste : non-lus et dernier message', liste and liste[0]['non_lus'] == 1
      and liste[0]['dernier_message']['texte'] == 'Salut, on fait le DS ?', liste)
check('Ali n’a rien de non lu (ses propres messages)', client(ali).get('/api/messagerie/non-lus/').json()['count'] == 0)
client(badr).post(f'/api/messagerie/conversations/{directe}/lu/')
check('Après lecture : 0 non lu', client(badr).get('/api/messagerie/non-lus/').json()['count'] == 0)
check('Chama ne lit pas la conversation des autres', client(chama).get(
    f'/api/messagerie/conversations/{directe}/messages/').status_code == 404)
msgs = client(badr).get(f'/api/messagerie/conversations/{directe}/messages/').json()
check('Historique lisible par Badr', [m['texte'] for m in msgs['results']] == ['Salut, on fait le DS ?'])
check('Badr ne supprime pas le message d’Ali', client(badr).delete(f'/api/messagerie/messages/{mid}/').status_code == 403)
r = client(badr).post(f'/api/messagerie/messages/{mid}/signaler/', {'motif': 'test'}, format='json')
check('Signalement par Badr', r.status_code == 201 and SignalementMessage.objects.filter(message_id=mid).count() == 1)
check('Signalements visibles par l’équipe seulement', client(equipe).get('/api/messagerie/signalements/').json()['count'] == 1
      and client(ali).get('/api/messagerie/signalements/').status_code == 403)
check('Ali supprime son message', client(ali).delete(f'/api/messagerie/messages/{mid}/').status_code == 204)
m = client(badr).get(f'/api/messagerie/conversations/{directe}/messages/').json()['results'][0]
check('Message supprimé : texte effacé', m['supprime'] and m['texte'] == '')
check('Le signalement garde une copie du texte', SignalementMessage.objects.get(message_id=mid).texte == 'Salut, on fait le DS ?')

print('--- Lecture seule quand on ne se suit plus')
communaute.ne_plus_suivre(badr, ali)
r = client(ali).post(f'/api/messagerie/conversations/{directe}/messages/', {'texte': 'Tu es là ?'}, format='json')
check('Plus mutuels : envoi refusé', r.status_code == 403)
conv = client(ali).get(f'/api/messagerie/conversations/{directe}/').json()
check('Plus mutuels : conversation en lecture seule', bool(conv['lecture_seule']))
amis(ali, badr)
check('De nouveau mutuels : envoi possible', client(ali).post(
    f'/api/messagerie/conversations/{directe}/messages/', {'texte': 'Re'}, format='json').status_code == 201)

print('--- Groupe et salle de travail')
r = client(ali).post('/api/messagerie/conversations/', {'membres': ['badr', 'emma'], 'contenu': sujet.id}, format='json')
check('Salle de travail sur un sujet', r.status_code == 201 and r.json()['contenu']['id'] == sujet.id, r.content[:300])
salle = r.json()['id']
check('Invitation postée dans la salle', Message.objects.filter(conversation_id=salle, type=Message.INVITATION).exists())
check('Groupe avec un non-mutuel refusé', client(ali).post(
    '/api/messagerie/conversations/', {'membres': ['badr', 'chama']}, format='json').status_code == 403)
for n in ('farid', 'ghita', 'hind', 'dina'):
    amis(ali, User.objects.get(username=n))
r = client(ali).post(f'/api/messagerie/conversations/{salle}/membres/', {'membres': ['farid', 'ghita', 'hind', 'dina']},
                     format='json')
check('7 personnes refusées (6 au plus, la visio est en maillage)', r.status_code == 400)
r = client(ali).post(f'/api/messagerie/conversations/{salle}/membres/', {'membres': ['farid']}, format='json')
check('Ajout d’un mutuel d’Ali', r.status_code == 200 and len(r.json()['membres']) == 4)
check('Badr ne peut pas ajouter quelqu’un qu’il ne suit pas', client(badr).post(
    f'/api/messagerie/conversations/{salle}/membres/', {'membres': ['ghita']}, format='json').status_code == 403)
communaute.bloquer(emma, farid)
check('Blocage : Farid quitte la salle qu’il partage avec Emma',
      Participant.objects.get(conversation_id=salle, user=farid).parti_le is not None)
check('Farid ne lit plus la salle', client(farid).get(f'/api/messagerie/conversations/{salle}/').status_code == 404)
check('Quitter un groupe', client(badr).post(f'/api/messagerie/conversations/{salle}/quitter/').status_code == 200
      and client(badr).get(f'/api/messagerie/conversations/{salle}/').status_code == 404)
check('On ne quitte pas une conversation directe', client(ali).post(
    f'/api/messagerie/conversations/{directe}/quitter/').status_code == 400)
r = client(ali).post(f'/api/messagerie/conversations/{directe}/inviter/', {'contenu': sujet.id}, format='json')
check('Inviter à travailler dans une conversation directe', r.status_code == 201 and r.json()['type'] == 'invitation')

print('--- Appels : identifiants et ticket')
with override_settings(TURN_HOST='', TURN_SECRET=''):
    check('Sans relais configuré : aucun serveur (jamais Google)', client(ali).get('/api/messagerie/ice/').json() == {'iceServers': []})
with override_settings(TURN_HOST='203.0.113.7', TURN_SECRET='secret-de-test'):
    ice = client(ali).get('/api/messagerie/ice/').json()['iceServers']
    turn = [s for s in ice if 'username' in s][0]
    attendu = base64.b64encode(hmac.new(b'secret-de-test', turn['username'].encode(), hashlib.sha1).digest()).decode()
    check('TURN : identifiants temporaires de coturn (use-auth-secret)', turn['credential'] == attendu
          and turn['username'].endswith(f':{ali.id}') and all('203.0.113.7' in u for s in ice for u in s['urls']))
t = client(ali).post('/api/messagerie/ticket/').json()['ticket']
check('Ticket du WebSocket lisible', lire_ticket(t) == ali.id)
check('Ticket falsifié refusé', lire_ticket(t[:-2] + 'xx') is None)
with override_settings(DEBUG=False, CORS_ALLOWED_ORIGINS=['https://fidni.fr']):
    check('Origine du site acceptée', consumers.origine_ok({'headers': [(b'origin', b'https://fidni.fr')]}))
    check('Autre origine refusée', not consumers.origine_ok({'headers': [(b'origin', b'https://evil.example')]}))

print('--- WebSocket : direct et appel')
app = URLRouter(websocket_urlpatterns)


class WebsocketCommunicator(ApplicationCommunicator):
    """Navigateur simulé : lit la file de sortie sans jamais annuler l'application sur un délai dépassé."""

    def __init__(self, application, chemin):
        p, _, q = chemin.partition('?')
        super().__init__(application, {'type': 'websocket', 'path': p, 'query_string': q.encode(), 'headers': [],
                                       'subprotocols': []})

    async def _sortie(self, timeout):
        return await asyncio.wait_for(self.output_queue.get(), timeout)

    async def connect(self):
        await self.send_input({'type': 'websocket.connect'})
        r = await self._sortie(5)
        return r['type'] == 'websocket.accept', r

    async def send_json_to(self, d):
        await self.send_input({'type': 'websocket.receive', 'text': json.dumps(d)})

    async def receive_json_from(self, timeout=2):
        r = await self._sortie(timeout)
        return json.loads(r['text']) if r.get('type') == 'websocket.send' else {'type': r.get('type')}

    async def disconnect(self):
        await self.send_input({'type': 'websocket.disconnect', 'code': 1000})
        try:
            await asyncio.wait_for(asyncio.shield(self.future), 5)
        except asyncio.TimeoutError:
            pass


async def ouvrir(u):
    ticket = await asyncio.to_thread(lambda: client(u).post('/api/messagerie/ticket/').json()['ticket'])
    ws = WebsocketCommunicator(app, f'/ws/?ticket={ticket}')
    ok, _ = await ws.connect()
    return ws if ok else None


async def attendre(ws, type_, essais=8, si=lambda m: True):
    for _ in range(essais):
        try:
            m = await ws.receive_json_from(timeout=2)
        except asyncio.TimeoutError:
            return None
        if m.get('type') == type_ and si(m):
            return m
    return None


async def scenario():
    sans = WebsocketCommunicator(app, '/ws/?ticket=faux')
    ok, _ = await sans.connect()
    check('WebSocket sans ticket valide : refusé', not ok)
    wa, wb, wc = await ouvrir(ali), await ouvrir(badr), await ouvrir(chama)
    check('WebSocket ouvert avec un ticket', wa is not None and wb is not None)
    await asyncio.to_thread(lambda: client(ali).post(f'/api/messagerie/conversations/{directe}/messages/',
                                                      {'texte': 'En direct'}, format='json'))
    m = await attendre(wb, 'message.nouveau')
    check('Message reçu en direct par Badr', m and m['message']['texte'] == 'En direct', m)
    await wa.send_json_to({'type': 'tape', 'conversation': directe})
    m = await attendre(wb, 'tape')
    check('« En train d’écrire » relayé', m and m['user'] == ali.id)
    await wc.send_json_to({'type': 'tape', 'conversation': directe})
    check('Chama ne peut rien envoyer dans la conversation des autres', await attendre(wb, 'tape', 1) is None)

    await wa.send_json_to({'type': 'appel.rejoindre', 'conversation': directe, 'video': True})
    ra = await attendre(wa, 'appel.rejoint')
    check('Ali lance l’appel (aucun pair encore)', ra and ra['pairs'] == [] and ra['video'] is True, ra)
    maj = await attendre(wb, 'appel.maj')
    check('Badr voit l’appel en cours (sonnerie)', maj and maj['appel'] and len(maj['appel']['presences']) == 1)
    await wc.send_json_to({'type': 'appel.rejoindre', 'conversation': directe})
    err = await attendre(wc, 'appel.erreur')
    check('Chama ne rejoint pas l’appel des autres', err is not None)
    await wb.send_json_to({'type': 'appel.rejoindre', 'conversation': directe})
    rb = await attendre(wb, 'appel.rejoint')
    check('Badr rejoint : Ali est son pair', rb and [p['user'] for p in rb['pairs']] == [ali.id], rb)
    arr = await attendre(wa, 'appel.arrivee')
    check('Ali est prévenu de l’arrivée de Badr', arr and arr['pair']['user'] == badr.id)
    await wb.send_json_to({'type': 'appel.signal', 'appel': rb['appel'], 'vers': ra['moi'],
                           'donnees': {'description': {'type': 'offer', 'sdp': 'v=0', 'pirate': 1}}})
    s = await attendre(wa, 'appel.signal')
    check('Offre relayée à Ali, nettoyée', s and s['de'] == rb['moi'] and s['donnees'] == {
        'description': {'type': 'offer', 'sdp': 'v=0'}}, s)
    await wc.send_json_to({'type': 'appel.signal', 'appel': rb['appel'], 'vers': ra['moi'],
                           'donnees': {'candidate': {'candidate': 'x'}}})
    check('Un intrus ne peut pas envoyer de signal dans l’appel', await attendre(wa, 'appel.signal', 1) is None)
    await wa.disconnect()
    maj = await attendre(wb, 'appel.maj', si=lambda m: m['appel'] and len(m['appel']['presences']) == 1)
    check('Ali parti : Badr reste seul dans l’appel', maj and len(maj['appel']['presences']) == 1, maj)
    await wb.send_json_to({'type': 'appel.quitter', 'appel': rb['appel']})
    fin = await attendre(wb, 'message.nouveau')
    check('Fin d’appel : compte rendu dans la conversation', fin and fin['message']['type'] == 'appel', fin)
    await wb.disconnect()
    await wc.disconnect()

asyncio.run(scenario())
check('Appel terminé en base', not Appel.objects.filter(fin__isnull=True).exists())

print('--- Présences : reconnexion et connexion perdue (13/11/2026, un participant apparaissait 5 fois)')
from apps.messagerie import services as S  # noqa: E402
from apps.messagerie.models import PresenceAppel  # noqa: E402
conv_d = Conversation.objects.get(pk=directe)
p1, ap, _ = S.rejoindre_appel(conv_d, ali, 'canal-1', False, 'onglet-a')
p2, ap2, _ = S.rejoindre_appel(conv_d, ali, 'canal-2', False, 'onglet-a')
check('Reconnexion du même onglet : l’ancienne présence est remplacée',
      ap2.id == ap.id and PresenceAppel.objects.get(pk=p1.pk).parti_le is not None
      and [p['user'] for p in S.etat_appel(conv_d)['presences']] == [ali.id])
p3, _, autres = S.rejoindre_appel(conv_d, badr, 'canal-3', False, 'onglet-b')
check('Un autre membre rejoint : il voit Ali', [a.user_id for a in autres] == [ali.id])
PresenceAppel.objects.filter(pk=p2.pk).update(vu_le=timezone.now() - timedelta(seconds=120))
check('Présence muette depuis 2 min : plus affichée', [p['user'] for p in S.etat_appel(conv_d)['presences']] == [badr.id])
S.signe_de_vie('canal-3')
_, _, autres = S.rejoindre_appel(conv_d, ali, 'canal-4', False, 'onglet-c')
check('Rejoindre retire la présence muette', [a.user_id for a in autres] == [badr.id]
      and PresenceAppel.objects.get(pk=p2.pk).parti_le is not None)
S.quitter_appel('canal-3'); S.quitter_appel('canal-4')
check('Appel terminé quand tout le monde est parti', S.appel_en_cours(conv_d) is None)

print('--- Purge et suppression de compte')
vieux = Message.objects.create(conversation_id=directe, auteur=ali, texte='vieux',
                               created_at=timezone.now() - timedelta(days=400))
signale = Message.objects.create(conversation_id=directe, auteur=ali, texte='vieux signalé',
                                 created_at=timezone.now() - timedelta(days=400))
SignalementMessage.objects.create(message=signale, auteur=badr)
call_command('purger_messages', verbosity=0)
check('Purge : message de plus de 12 mois supprimé', not Message.objects.filter(pk=vieux.pk).exists())
check('Purge : message signalé non traité gardé', Message.objects.filter(pk=signale.pk).exists())
n_ali = Message.objects.filter(auteur=ali).count()
delete_account(ali, keep_contributions=True)
check('Compte supprimé : ses messages partent avec lui', n_ali > 0 and not Message.objects.filter(auteur_id=ali.id).exists())
check('Conversation directe gardée pour Badr (lecture seule)', Conversation.objects.filter(pk=directe).exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
