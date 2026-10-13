"""Fenêtres « Nouveautés » (14/10/2026) : qui les voit (anciens membres, pas les profs, pas les nouveaux inscrits),
une seule fois par compte (retenu sur le serveur), arrivées avec la connexion. apps/users/nouveautes.py"""
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
nouveau = membre('nouveau', joined=NOUVEAUTES[NID]['inscrits_avant'] + timedelta(minutes=5))
prof = membre('prof_ancien', teacher=True)
chef = membre('chef_ancien', is_staff=True, is_superuser=True)

# — Qui la voit —
r = client().post('/api/auth/login/', {'identifier': 'ancien', 'password': PWD}, format='json')
check('connexion : la réponse porte les nouveautés de l’ancien élève', r.status_code == 200 and r.data['user'].get('nouveautes') == [NID], (r.status_code, r.data.get('user', {}).get('nouveautes')))
r = client(ancien).get('/api/auth/user/')
check('GET /auth/user/ : nouveautes = [progression]', r.status_code == 200 and r.data.get('nouveautes') == [NID], r.data.get('nouveautes'))
r = client(nouveau).get('/api/auth/user/')
check('inscrit après la nouveauté : rien', r.data.get('nouveautes') == [], r.data.get('nouveautes'))
r = client(prof).get('/api/auth/user/')
check('prof : rien (nouveauté des élèves)', r.data.get('nouveautes') == [], r.data.get('nouveautes'))
r = client(chef).get('/api/auth/user/')
check('équipe inscrite avant : la voit', r.data.get('nouveautes') == [NID], r.data.get('nouveautes'))
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
check('vue : 200, plus rien à voir', r.status_code == 200 and r.data == {'a_voir': []}, (r.status_code, r.data))
ancien.profile.refresh_from_db()
premiere = ancien.profile.nouveautes_vues.get(NID)
check('date de la première vue retenue', bool(premiere), ancien.profile.nouveautes_vues)
r = client(ancien).post(f'/api/nouveautes/{NID}/vue/')
ancien.profile.refresh_from_db()
check('second POST : idempotent (même date)', r.status_code == 200 and ancien.profile.nouveautes_vues.get(NID) == premiere)
r = client(ancien).get('/api/auth/user/')
check('après vue : /auth/user/ ne la propose plus', r.data.get('nouveautes') == [], r.data.get('nouveautes'))
r = client().post('/api/auth/login/', {'identifier': 'ancien', 'password': PWD}, format='json')
check('après vue : la connexion ne la propose plus', r.status_code == 200 and r.data['user'].get('nouveautes') == [], r.data.get('user', {}).get('nouveautes'))
r = client(chef).get('/api/auth/user/')
check('vue par un compte : pas par les autres', r.data.get('nouveautes') == [NID])

# — Dans le temps —
fin = NOUVEAUTES[NID]['jusqu_au']
dernier = datetime(fin.year, fin.month, fin.day, 20, 0, tzinfo=dt_timezone.utc)
check('encore proposée le dernier jour', a_voir(chef, maintenant=dernier) == [NID])
check('plus proposée après jusqu_au', a_voir(chef, maintenant=dernier + timedelta(days=1)) == [])

# — PATCH /users/me/ ne peut pas l'écrire —
r = client(chef).patch('/api/users/me/', {'profile': {'nouveautes_vues': {NID: 'x'}}}, format='json')
chef.profile.refresh_from_db()
check('PATCH /users/me/ ne marque rien', NID not in (chef.profile.nouveautes_vues or {}), (r.status_code, chef.profile.nouveautes_vues))

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
