"""Pilotage › « Un membre n’arrive pas à se connecter » (apps/users/login_diagnostic.py)."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-login-diag.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
import runpy  # noqa: E402
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


UA = {'HTTP_USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0) Chrome/130'}
PWD = 'Motdepasse-solide-42'
admin = User.objects.create_superuser('chef', 'chef@x.fr', PWD)
eleve = User.objects.create_user('Amine', 'amine@x.fr', PWD)
jamais = User.objects.create_user('Sara', 'sara@x.fr', PWD)
jamais.is_active = False
jamais.save()
jamais.profile.email_verified = False
jamais.profile.save()
double = User.objects.create_user('amine2', 'AMINE@x.fr', PWD)

visitor = APIClient(REMOTE_ADDR='10.0.0.5', **UA)
r = visitor.post('/api/auth/login/', {'identifier': 'amine@x.fr', 'password': 'faux'}, format='json')
check('mauvais mot de passe : 401', r.status_code == 401, r.status_code)
r = visitor.post('/api/auth/login/', {'identifier': 'sara@x.fr', 'password': PWD}, format='json')
check('e-mail non confirmé : 403', r.status_code == 403, r.status_code)

pc = APIClient(**UA)
pc.force_authenticate(admin)
check('élève : refusé', APIClient(**UA).get('/api/pilotage/connexion/?q=amine@x.fr').status_code in (401, 403))
r = pc.get('/api/pilotage/connexion/', {'q': 'Amine@x.fr'})
check('réponse', r.status_code == 200, r.status_code)
d = r.data
check('deux comptes avec la même adresse, le plus ancien utilisé', [a['username'] for a in d['accounts']] == ['Amine', 'amine2']
      and d['accounts'][0]['used_for_login'] and not d['accounts'][1]['used_for_login'], d['accounts'])
check('avertissement : adresse partagée', any('partagent cette adresse' in w for w in d['warnings']), d['warnings'])
check('journal : l’essai raté, avec son explication', d['logs'] and d['logs'][0]['status'] == 401
      and d['logs'][0]['code'] == 'invalid_credentials' and d['logs'][0]['hint'], d['logs'])
check('aucun mot de passe dans la réponse', 'faux' not in str(d) and PWD not in str(d))
check('essais en cours comptés', any(t['attempts'] >= 1 for t in d['throttles']), d['throttles'])

d = pc.get('/api/pilotage/connexion/', {'q': 'sara@x.fr'}).data
check('e-mail jamais confirmé : expliqué', any('jamais confirmé' in w for w in d['warnings'])
      and d['logs'][0]['code'] == 'email_not_verified', (d['warnings'], d['logs']))
d = pc.get('/api/pilotage/connexion/', {'q': 'personne@x.fr'}).data
check('adresse inconnue', d['accounts'] == [] and any('Aucun compte' in w for w in d['warnings']), d['warnings'])

for _ in range(16):
    visitor.post('/api/auth/login/', {'identifier': 'amine@x.fr', 'password': 'faux'}, format='json')
d = pc.get('/api/pilotage/connexion/', {'q': 'amine@x.fr'}).data
check('bloqué après 15 essais : signalé', any(t['blocked'] for t in d['throttles'])
      and any('Bloqué' in w for w in d['warnings']) and any(l['status'] == 429 for l in d['logs']), (d['throttles'], d['warnings']))
check('requête trop courte refusée', pc.get('/api/pilotage/connexion/', {'q': 'a'}).status_code == 400)

# Connexion avec Google (jeton remplacé par une fonction factice : Google n'est jamais appelé)
from apps.authentication import google  # noqa: E402
from apps.users.models import GoogleAccount  # noqa: E402

FAKE = {'yasmine': {'sub': 'g-yas', 'email': 'yasmine@gmail.com', 'given_name': 'Yasmine', 'family_name': 'Alaoui',
                    'name': 'Yasmine Alaoui'},
        'nadia': {'sub': 'g-nadia', 'email': 'nadia.perso@gmail.com', 'given_name': 'Nadia', 'family_name': 'B',
                  'name': 'Nadia B'}}


def fake_verify(token):
    if token not in FAKE:
        raise google.GoogleTokenError('jeton inconnu')
    return dict(FAKE[token])


google.verify_google_credential = fake_verify
cache.clear()
r = visitor.post('/api/auth/google/', {'credential': 'yasmine'}, format='json')
check('Google, nouveau compte sans les cases : consent_required', r.status_code == 400
      and r.data.get('code') == 'consent_required', r.data)
visitor.post('/api/auth/google/', {'credential': 'pirate'}, format='json')
d = pc.get('/api/pilotage/connexion/', {'q': 'yasmine@gmail.com'}).data
check('… journal retrouvé par l’adresse (dans la réponse), avec son explication',
      any(l['code'] == 'consent_required' and l['identifier'] == 'yasmine@gmail.com' and l['hint'] for l in d['logs']),
      d['logs'])
check('… aucun jeton dans la réponse du diagnostic', 'pirate' not in str(d))
cache.clear()
r = visitor.post('/api/auth/google/', {'credential': 'yasmine', 'accept_terms': True, 'age_ok': True}, format='json')
check('Google : compte créé', r.status_code == 200 and r.data.get('created') is True, r.data)
d = pc.get('/api/pilotage/connexion/', {'q': 'yasmine@gmail.com'}).data
acc = d['accounts'][0] if d['accounts'] else {}
check('compte Google : google = true, sans mot de passe', acc.get('google') is True and acc.get('has_password') is False, acc)
check('… avertissement juste (Google, « Mot de passe oublié » possible)',
      any('se connecte avec Google' in w and 'Mot de passe oublié' in w for w in d['warnings'])
      and not any('n’envoie rien' in w for w in d['warnings']), d['warnings'])
d = pc.get('/api/pilotage/connexion/', {'q': 'Amine'}).data
check('compte classique : google = false', all(a['google'] is False for a in d['accounts']), d['accounts'])

nadia = User.objects.create_user('nadia', 'nadia@ecole.ma', PWD)
GoogleAccount.objects.create(user=nadia, sub='g-nadia', email='nadia.perso@gmail.com')
d = pc.get('/api/pilotage/connexion/', {'q': 'nadia.perso@gmail.com'}).data
check('recherche par l’adresse Google liée (différente du compte)', [a['username'] for a in d['accounts']] == ['nadia']
      and d['accounts'][0]['google'] and d['accounts'][0]['has_password'], d['accounts'])

sans = User.objects.create_user('sansmdp', 'sans@x.fr')
d = pc.get('/api/pilotage/connexion/', {'q': 'sans@x.fr'}).data
check('sans mot de passe ni Google : « Mot de passe oublié » n’envoie rien',
      any('n’envoie rien' in w for w in d['warnings']), d['warnings'])

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
