"""RGPD : acceptation des conditions, sexe facultatif, export des données, purge des journaux."""
import json
import os
import tempfile
import sys
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': os.path.join(tempfile.gettempdir(), 'fidni-legal.sqlite3'), 'AWS_STORAGE_ENABLED': 'false',
                   'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend'})
if os.path.exists('/tmp/fidni-legal.sqlite3'):
    os.remove('/tmp/fidni-legal.sqlite3')
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.logging.models import APILog  # noqa: E402
from apps.users.legal import TERMS_VERSION, purge_old_logs  # noqa: E402
from apps.caracteristics.models import School  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None, ip='1.1.1.1'):
    c = APIClient(HTTP_CF_CONNECTING_IP=ip)
    if user:
        c.force_authenticate(user)
    return c


PW = 'Motdepasse-solide-42'
base = {'username': 'lina', 'email': 'lina@x.fr', 'password': PW}
r = client().post('/api/auth/register/', base, format='json')
check('inscription sans accepter les conditions : refusée', r.status_code == 400 and r.data.get('field') == 'accept_terms', r.data)
r = client().post('/api/auth/register/', {**base, 'accept_terms': 'on'}, format='json')
check('« accept_terms » doit être exactement vrai', r.status_code == 400, r.status_code)
r = client().post('/api/auth/register/', {**base, 'accept_terms': True}, format='json')
check('inscription sans case âge / accord parental : refusée', r.status_code == 400 and r.data.get('field') == 'age_ok', r.data)
check('… aucun compte créé', not User.objects.filter(username='lina').exists())
r = client().post('/api/auth/register/', {**base, 'accept_terms': True, 'age_ok': True}, format='json')
lina = User.objects.get(username='lina')
check('inscription complète acceptée', r.status_code == 201, r.data)
check('… acceptation horodatée et versionnée', lina.profile.terms_accepted_at is not None and lina.profile.terms_version == TERMS_VERSION)

old = User.objects.create_user('ancien', 'o@x.fr', PW)
r = client(old).get('/api/auth/user/')
check('compte existant : conditions à accepter', r.data['profile']['terms_up_to_date'] is False, r.data['profile'].get('terms_up_to_date'))
client(old).patch('/api/auth/user/update/', {'accept_terms': True}, format='json')
old.profile.refresh_from_db()
check('… acceptation enregistrée', old.profile.terms_version == TERMS_VERSION)
r = client(old).get('/api/auth/user/')
check('… plus rien à accepter', r.data['profile']['terms_up_to_date'] is True)
r = client(lina).get('/api/users/ancien/')
check('statut des conditions privé', 'terms_up_to_date' not in r.data.get('profile', {}))

school = School.objects.first()
r = client(old).post('/api/onboarding/', {'user_type': 'student', 'first_name': 'Anne', 'last_name': 'Ancien',
                                          'school_id': school.id, 'gender': 'N', 'birth_date': '2008-06-01'}, format='json')
old.profile.refresh_from_db()
check('civilité « préfère ne pas le dire » acceptée', r.status_code == 200 and old.profile.gender == 'N', r.data)

APILog.objects.create(endpoint='/api/x/', method='GET', status_code=200, response_time_ms=1, ip_address='1.2.3.4', user=old)
r = client(old).get('/api/auth/my-data/')
check('export de ses données (JSON téléchargeable)', r.status_code == 200 and 'attachment' in r['Content-Disposition'], r.status_code)
data = json.loads(r.content)
check('… compte, profil et journaux inclus', data['compte']['email'] == 'o@x.fr' and 'users.UserProfile' in data
      and 'logging.APILog' in data, list(data.keys())[:8])
check('… sans mot de passe ni jetons', 'password' not in r.content.decode() and 'token_blacklist.OutstandingToken' not in data)
check('export réservé au titulaire du compte', client().get('/api/auth/my-data/').status_code in (401, 403))

vieux = APILog.objects.create(endpoint='/api/y/', method='GET', status_code=200, response_time_ms=1, ip_address='5.6.7.8')
APILog.objects.filter(pk=vieux.pk).update(timestamp=timezone.now() - timedelta(days=200))
n = purge_old_logs()
check('journaux de plus de 6 mois purgés', n >= 1 and not APILog.objects.filter(pk=vieux.pk).exists()
      and APILog.objects.filter(endpoint='/api/x/').exists(), n)

inactif = User.objects.create_user('dormeur', 'd@x.fr', PW)
User.objects.filter(pk=inactif.pk).update(last_login=timezone.now() - timedelta(days=4 * 365))
import io  # noqa: E402
out = io.StringIO()
call_command('purger_comptes_inactifs', stdout=out)
check('comptes inactifs : simulation par défaut', 'dormeur' in out.getvalue() and User.objects.filter(username='dormeur').exists())
call_command('purger_comptes_inactifs', '--appliquer', stdout=io.StringIO())
check('… suppression avec --appliquer (les actifs restent)', not User.objects.filter(username='dormeur').exists()
      and User.objects.filter(username='lina').exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
