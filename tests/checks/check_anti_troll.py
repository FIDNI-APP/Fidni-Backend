"""Protection contre les comptes créés pour troller (20/11/2026) : délai de 24 h avant d'écrire, premiers messages à
valider (discussions/moderation.py, Pilotage › Messages à valider) et bannissement de l'appareil (users/bans.py)."""
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-anti-troll.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
os.environ.pop('FIDNI_ANTI_TROLL', None)
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Subject  # noqa: E402
from apps.discussions.models import Discussion, Reply  # noqa: E402
from apps.notifications.models import Notification  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users.bans import ban_user  # noqa: E402
from apps.users.models import Bannissement  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(u=None, **headers):
    cache.clear()  # limites de requêtes
    c = APIClient(**headers)
    if u:
        c.force_authenticate(u)
    return c


def vieux(user, jours=3):
    User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=jours))
    user.refresh_from_db()
    return user


check('réglage actif par défaut', settings.ANTI_TROLL is True)
check('en-tête de l’appareil autorisé par CORS', 'x-fidni-appareil' in settings.CORS_ALLOW_HEADERS)

maths = Subject.objects.filter(name='Mathématiques').first() or Subject.objects.create(name='Mathématiques')
equipe = User.objects.create_user('equipe_at', is_staff=True, is_superuser=True)
contenu = Content.objects.create(type='exercise', title='Exercice test', author=equipe, subject=maths)
ancien = vieux(User.objects.create_user('ancien_at'), 30)
neuf = User.objects.create_user('neuf_at')
nouveau = vieux(User.objects.create_user('nouveau_at'))
autre = vieux(User.objects.create_user('autre_at'), 30)

# Trois messages validés pour « ancien » (pas soumis à la validation ensuite)
for i in range(3):
    Discussion.objects.create(author=ancien, title=f'Ancienne discussion {i}', body='<p>texte</p>')
fil = Discussion.objects.create(author=ancien, title='Discussion ouverte', body='<p>Question</p>')

# ── Délai de 24 h
FORUM = {'title': 'Une question de troll', 'body': '<p>…</p>', 'salon': 'entraide'}
r = client(neuf).post('/api/discussions/', FORUM, format='json')
check('compte de moins de 24 h : discussion refusée', r.status_code == 403 and r.data.get('code') == 'compte_recent'
      and r.data.get('heures') == 24, (r.status_code, r.data))
r = client(neuf).post('/api/discussions/', {'genre': 'commentaire', 'body': '<p>nul</p>', 'content_ids': [contenu.id]},
                      format='json')
check('compte de moins de 24 h : commentaire refusé', r.status_code == 403, r.status_code)
r = client(neuf).post(f'/api/discussions/{fil.id}/repondre/', {'body': '<p>réponse</p>'}, format='json')
check('compte de moins de 24 h : réponse refusée', r.status_code == 403, r.status_code)
r = client(neuf).post('/api/proposed-solutions/', {'content': contenu.id, 'text': 'Ma solution'}, format='json')
check('compte de moins de 24 h : solution proposée refusée', r.status_code == 403
      and r.data.get('code') == 'compte_recent', (r.status_code, getattr(r, 'data', None)))
r = client(equipe).post('/api/discussions/', FORUM, format='json')
check('équipe : pas de délai ni de validation', r.status_code == 201 and r.data.get('en_attente') is False, r.data)

# ── Premiers messages à valider
r = client(nouveau).post('/api/discussions/', {**FORUM, 'title': 'Ma première question'}, format='json')
check('premier message : enregistré en attente', r.status_code == 201 and r.data.get('en_attente') is True, r.data)
d1 = Discussion.objects.get(pk=r.data['id'])
mes = {x['id'] for x in client(nouveau).get('/api/discussions/?niveau=tous').data['results']}
autres = {x['id'] for x in client(autre).get('/api/discussions/?niveau=tous').data['results']}
visiteur = {x['id'] for x in client().get('/api/discussions/?niveau=tous').data['results']}
check('en attente : visible de son auteur seulement', d1.id in mes and d1.id not in autres and d1.id not in visiteur)
check('en attente : détail introuvable pour les autres', client(autre).get(f'/api/discussions/{d1.id}/').status_code == 404
      and client(nouveau).get(f'/api/discussions/{d1.id}/').status_code == 200)
check('en attente : aucune notification', not Notification.objects.filter(target=f'discussion:{d1.id}').exists())
avant = Discussion.objects.get(pk=fil.id).reply_count
r = client(nouveau).post(f'/api/discussions/{fil.id}/repondre/', {'body': '<p>Ma réponse</p>'}, format='json')
check('réponse en attente', r.status_code == 201 and r.data.get('en_attente') is True, r.data)
rep = Reply.objects.get(pk=r.data['id'])
check('réponse en attente : pas comptée', Discussion.objects.get(pk=fil.id).reply_count == avant)
vue_autre = [x['id'] for x in client(autre).get(f'/api/discussions/{fil.id}/').data['replies']]
vue_moi = [x['id'] for x in client(nouveau).get(f'/api/discussions/{fil.id}/').data['replies']]
check('réponse en attente : cachée aux autres, montrée à son auteur', rep.id not in vue_autre and rep.id in vue_moi)
check('« utile » impossible sur un message en attente',
      client(autre).post(f'/api/discussions/{d1.id}/utile/').status_code == 404)

# ── Pilotage › Messages à valider
r = client(autre).get('/api/pilotage/messages-a-valider/')
check('liste réservée à l’équipe', r.status_code in (401, 403), r.status_code)
r = client(equipe).get('/api/pilotage/messages-a-valider/')
types = sorted((x['type'], x['id']) for x in r.data['results'])
check('liste des messages en attente', r.status_code == 200 and types == sorted([('discussion', d1.id), ('reponse', rep.id)])
      and all(x['auteur']['username'] == 'nouveau_at' for x in r.data['results']), r.data)
d = client(equipe).get('/api/pilotage/direct/').data if client(equipe).get('/api/pilotage/direct/').status_code == 200 else {}
check('moniteur : compteur des messages à valider', (d.get('todo') or {}).get('messages_a_valider') == 2, d.get('todo'))
r = client(equipe).post(f'/api/pilotage/messages-a-valider/reponse/{rep.id}/accepter/')
check('réponse acceptée : visible et comptée', r.status_code == 200 and not Reply.objects.get(pk=rep.id).en_attente
      and Discussion.objects.get(pk=fil.id).reply_count == avant + 1
      and rep.id in [x['id'] for x in client(autre).get(f'/api/discussions/{fil.id}/').data['replies']])
r = client(equipe).post(f'/api/pilotage/messages-a-valider/discussion/{d1.id}/refuser/')
check('discussion refusée : supprimée', r.status_code == 200 and not Discussion.objects.filter(pk=d1.id).exists())
r = client(equipe).post('/api/pilotage/messages-a-valider/inconnu/1/accepter/')
check('type inconnu : 400', r.status_code == 400, r.status_code)

# ── Après 3 messages validés : plus de validation
for i in range(2):
    Discussion.objects.create(author=nouveau, title=f'Validée {i}', body='<p>ok</p>')
r = client(nouveau).post('/api/discussions/', {**FORUM, 'title': 'Quatrième message'}, format='json')
check('3 messages validés : publié directement', r.status_code == 201 and r.data.get('en_attente') is False, r.data)

# ── Bannissement de l'appareil
APP = 'a1b2c3d4-e5f6-4711-8899-aabbccddeeff'
troll = vieux(User.objects.create_user('troll_at', email='troll@gmail.com', password='Motdepasse-solide-42'))
r = client(HTTP_X_FIDNI_APPAREIL=APP).post('/api/auth/login/', {'identifier': 'troll_at', 'password': 'Motdepasse-solide-42'},
                                           format='json')
troll.profile.refresh_from_db()
check('connexion : appareil retenu dans le profil', [e['id'] for e in troll.profile.appareils] == [APP],
      (r.status_code, troll.profile.appareils))
fait = ban_user(troll, motif='test')
check('bannissement : appareil banni pour un an', fait['appareil'] == [APP] and Bannissement.objects.filter(
    kind='appareil', value=APP, expires_at__gt=timezone.now() + timedelta(days=360)).exists(), fait)
INSCRIPTION = {'password': 'Motdepasse-solide-42', 'accept_terms': True, 'age_ok': True}
r = client(HTTP_X_FIDNI_APPAREIL=APP, HTTP_CF_CONNECTING_IP='9.9.9.1').post(
    '/api/auth/register/', {'username': 'troll_bis', 'email': 'autre.adresse@gmail.com', **INSCRIPTION}, format='json')
check('nouvelle adresse depuis l’appareil banni : refusée', r.status_code in (400, 403) and r.data.get('code') == 'banned',
      (r.status_code, r.data))
r = client(HTTP_X_FIDNI_APPAREIL='ffffffff-0000-4000-8000-000000000000', HTTP_CF_CONNECTING_IP='9.9.9.2').post(
    '/api/auth/register/', {'username': 'eleve_ok', 'email': 'eleve.ok@gmail.com', **INSCRIPTION}, format='json')
check('autre appareil : inscription acceptée', r.status_code in (200, 201), (r.status_code, r.data))
r = client(HTTP_X_FIDNI_APPAREIL='<script>', HTTP_CF_CONNECTING_IP='9.9.9.3').post(
    '/api/auth/register/', {'username': 'eleve_ok2', 'email': 'eleve.ok2@gmail.com', **INSCRIPTION}, format='json')
check('identifiant d’appareil invalide : ignoré', r.status_code in (200, 201), (r.status_code, r.data))

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
