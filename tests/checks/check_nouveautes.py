"""Fenêtres « Nouveautés » (14/10/2026) : qui les voit (anciens membres, pas les profs pour Ma progression, tout le
monde pour le mode sombre, pas les nouveaux inscrits), une seule fois par compte (retenu sur le serveur), arrivées avec
la connexion ; gestes par fenêtre et bloc du Pilotage. apps/users/nouveautes.py"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-nouveautes.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.users.nouveautes import NOUVEAUTES, a_voir  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []
PWD = 'Motdepasse-solide-42'
NID = 'progression-2026-10'
NS = 'mode-sombre-2026-10'
AVANT = datetime(2026, 10, 1, 12, 0, tzinfo=dt_timezone.utc)


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None):
    cache.clear()
    c = APIClient(HTTP_CF_CONNECTING_IP='5.5.5.5')
    if user is not None:
        c.force_authenticate(user)
    return c


def membre(username, joined=AVANT, teacher=False, **extra):
    u = User.objects.create_user(username, f'{username}@x.fr', PWD, **extra)
    User.objects.filter(pk=u.pk).update(date_joined=joined)
    u.refresh_from_db()
    if teacher:
        u.profile.user_type = 'teacher'
        u.profile.save(update_fields=['user_type'])
    return u


ancien = membre('ancien')
nouveau = membre('nouveau', joined=NOUVEAUTES[NID]['inscrits_avant'] + timedelta(minutes=5))  # entre les deux
tardif = membre('tardif', joined=NOUVEAUTES[NS]['inscrits_avant'] + timedelta(minutes=5))
prof = membre('prof_ancien', teacher=True)
chef = membre('chef_ancien', is_staff=True, is_superuser=True)

# — Qui la voit —
r = client().post('/api/auth/login/', {'identifier': 'ancien', 'password': PWD}, format='json')
check('connexion : la réponse porte les nouveautés de l’ancien élève', r.status_code == 200 and r.data['user'].get('nouveautes') == [NID, NS], (r.status_code, r.data.get('user', {}).get('nouveautes')))
r = client(ancien).get('/api/auth/user/')
check('GET /auth/user/ : progression puis mode sombre (ordre du registre)', r.status_code == 200 and r.data.get('nouveautes') == [NID, NS], r.data.get('nouveautes'))
r = client(nouveau).get('/api/auth/user/')
check('inscrit entre les deux : le mode sombre seulement', r.data.get('nouveautes') == [NS], r.data.get('nouveautes'))
r = client(tardif).get('/api/auth/user/')
check('inscrit après le mode sombre : rien', r.data.get('nouveautes') == [], r.data.get('nouveautes'))
r = client(prof).get('/api/auth/user/')
check('prof : le mode sombre, pas Ma progression', r.data.get('nouveautes') == [NS], r.data.get('nouveautes'))
r = client(chef).get('/api/auth/user/')
check('équipe inscrite avant : les deux', r.data.get('nouveautes') == [NID, NS], r.data.get('nouveautes'))
r = client(nouveau).get('/api/users/ancien/')
check('profil d’un autre : pas de champ nouveautes', r.status_code == 200 and 'nouveautes' not in r.data, (r.status_code, list(r.data)[:12]))
r = client(chef).get('/api/users/ancien/')
check('profil vu par l’équipe : pas de champ nouveautes', 'nouveautes' not in r.data)

# — Marquée vue —
r = client().post(f'/api/nouveautes/{NID}/vue/')
check('anonyme : 401', r.status_code == 401, r.status_code)
r = client(ancien).post('/api/nouveautes/inconnue/vue/')
check('id inconnu : 404', r.status_code == 404, r.status_code)
r = client(ancien).post(f'/api/nouveautes/{NID}/vue/')
check('vue : 200, reste le mode sombre', r.status_code == 200 and r.data == {'a_voir': [NS]}, (r.status_code, r.data))
ancien.profile.refresh_from_db()
premiere = ancien.profile.nouveautes_vues.get(NID)
check('date de la première vue retenue', bool(premiere), ancien.profile.nouveautes_vues)
r = client(ancien).post(f'/api/nouveautes/{NID}/vue/')
ancien.profile.refresh_from_db()
check('second POST : idempotent (même date)', r.status_code == 200 and ancien.profile.nouveautes_vues.get(NID) == premiere)
r = client(ancien).get('/api/auth/user/')
check('après vue : /auth/user/ ne la propose plus', r.data.get('nouveautes') == [NS], r.data.get('nouveautes'))
r = client().post('/api/auth/login/', {'identifier': 'ancien', 'password': PWD}, format='json')
check('après vue : la connexion ne la propose plus', r.status_code == 200 and r.data['user'].get('nouveautes') == [NS], r.data.get('user', {}).get('nouveautes'))
r = client(chef).get('/api/auth/user/')
check('vue par un compte : pas par les autres', r.data.get('nouveautes') == [NID, NS])
r = client(ancien).post(f'/api/nouveautes/{NS}/vue/')
check('mode sombre vu à son tour : plus rien', r.status_code == 200 and r.data == {'a_voir': []}, r.data)
r = client(prof).post(f'/api/nouveautes/{NS}/vue/')
check('prof : mode sombre marqué vu', r.data == {'a_voir': []}, r.data)

# — Dans le temps —
fin = NOUVEAUTES[NID]['jusqu_au']
dernier = datetime(fin.year, fin.month, fin.day, 20, 0, tzinfo=dt_timezone.utc)
check('encore proposée le dernier jour', a_voir(chef, maintenant=dernier) == [NID, NS])
check('plus proposée après jusqu_au', a_voir(chef, maintenant=dernier + timedelta(days=1)) == [])

# — PATCH /users/me/ ne peut pas l'écrire —
r = client(chef).patch('/api/users/me/', {'profile': {'nouveautes_vues': {NID: 'x'}}}, format='json')
chef.profile.refresh_from_db()
check('PATCH /users/me/ ne marque rien', NID not in (chef.profile.nouveautes_vues or {}), (r.status_code, chef.profile.nouveautes_vues))

# — Gestes par fenêtre (UsageDaily « nouveautes:<id>:<geste> ») et bloc du Pilotage —
UA = {'HTTP_USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0) Chrome/130'}


def usage(user, name, ip='10.1.0.1'):
    cache.clear()
    c = APIClient(REMOTE_ADDR=ip, **UA)
    c.force_authenticate(user)
    return c.post('/api/usage/', {'kind': 'filtre', 'name': name}, format='json')


r = usage(ancien, f'nouveautes:{NS}:vue')
check('geste « vue » du mode sombre accepté', r.status_code in (200, 201) and r.data.get('counted') is not False, (r.status_code, r.data))
usage(ancien, f'nouveautes:{NS}:cta', ip='10.1.0.2')
usage(prof, f'nouveautes:{NS}:vue', ip='10.1.0.3')
usage(prof, f'nouveautes:{NS}:passee', ip='10.1.0.4')
r = usage(ancien, f'nouveautes:{NS}:clic')
check('geste inconnu : 400', r.status_code == 400, r.status_code)
r = usage(ancien, 'nouveautes:Mode Sombre:vue')
check('id mal formé : 400', r.status_code == 400, r.status_code)
cache.clear()
pc = APIClient(**UA)
pc.force_authenticate(chef)
r = pc.get('/api/pilotage/?jours=7')
bloc = {n['id']: n for n in (r.data.get('nouveautes') or [])} if r.status_code == 200 else {}
check('Pilotage : une ligne par fenêtre, la plus récente d’abord',
      [n['id'] for n in r.data.get('nouveautes', [])] == [NS, NID], (r.status_code, r.data.get('nouveautes')))
check('Pilotage : comptes réels qui l’ont vue (équipe exclue)', bloc.get(NS, {}).get('comptes') == 2 and bloc.get(NID, {}).get('comptes') == 1,
      {k: v.get('comptes') for k, v in bloc.items()})
check('Pilotage : gestes de la période', {g: bloc.get(NS, {}).get(g) for g in ('vue', 'finie', 'cta', 'passee')} == {'vue': 2, 'finie': 0, 'cta': 1, 'passee': 1},
      bloc.get(NS))
check('Pilotage : date de la nouveauté', bloc.get(NS, {}).get('depuis') == '2026-10-15', bloc.get(NS))

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
