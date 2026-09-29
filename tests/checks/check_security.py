"""Vérification de bout en bout des correctifs de sécurité, sur une base SQLite jetable."""
import os
import tempfile
import re
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
os.environ.update({
    'DJANGO_SETTINGS_MODULE': 'config.settings',
    'DJANGO_ENV': 'development',
    'DB_ENGINE': 'sqlite',
    'SQLITE_PATH': os.path.join(tempfile.gettempdir(), 'fidni-check.sqlite3'),
    'AWS_STORAGE_ENABLED': 'false',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
})
if os.path.exists('/tmp/fidni-check.sqlite3'):
    os.remove('/tmp/fidni-check.sqlite3')

import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)

from django.conf import settings  # noqa: E402
from django.core import mail  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.logging.models import APILog  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
mail.outbox = []
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None, ip='1.1.1.1'):
    c = APIClient(HTTP_CF_CONNECTING_IP=ip)
    if user:
        c.force_authenticate(user)
    return c


alice = User.objects.create_user('alice', 'alice@exemple.fr', 'Motdepasse-solide-42')
bob = User.objects.create_user('bob', 'bob@exemple.fr', 'Motdepasse-solide-42')
staff = User.objects.create_user('prof', 'prof@exemple.fr', 'Motdepasse-solide-42', is_staff=True)
anon = client()

# 1. Comptes : plus de liste, de création ni de suppression anonymes ; e-mail masqué
r = anon.get('/api/users/')
check('liste des comptes fermée', r.status_code == 404, r.status_code)
r = anon.delete('/api/users/alice/')
check('suppression anonyme refusée', r.status_code == 405, r.status_code)
check('alice existe toujours', User.objects.filter(username='alice').exists())
r = anon.post('/api/users/', {'username': 'x'}, format='json')
check('création par /api/users/ refusée', r.status_code == 405, r.status_code)
r = anon.get('/api/users/alice/')
check('profil public sans e-mail', r.status_code == 200 and 'email' not in r.data, r.data.get('email'))
r = client(alice).get('/api/users/alice/')
check('propriétaire voit son e-mail', r.status_code == 200 and r.data.get('email') == 'alice@exemple.fr', r.status_code)
r = client(alice).get('/api/auth/user/')
check('/auth/user/ complet pour soi', r.status_code == 200 and r.data.get('email') == 'alice@exemple.fr', r.status_code)

# 2. Contenus : seul l'auteur (ou le staff) modifie / supprime
item = Content.objects.create(title='Suites', type='exercise', author=alice)
r = client(bob).patch(f'/api/contents/{item.id}/', {'title': 'Piraté'}, format='json')
check('bob ne modifie pas le contenu d’alice', r.status_code == 403, r.status_code)
r = client(bob).delete(f'/api/contents/{item.id}/')
check('bob ne supprime pas le contenu d’alice', r.status_code == 403, r.status_code)
r = client(bob).post(f'/api/contents/{item.id}/solution/', {'content': 'fausse'}, format='json')
check('bob ne réécrit pas la solution', r.status_code == 403, r.status_code)
r = client(bob).post(f'/api/contents/{item.id}/comment/', {'content': 'Merci !'}, format='json')
check('bob peut commenter', r.status_code == 201, (r.status_code, getattr(r, 'data', None)))
comment_id = r.data.get('id') if r.status_code == 201 else None
r = client(bob).post(f'/api/contents/{item.id}/vote/', {'value': 1}, format='json')
check('bob peut voter', r.status_code in (200, 201), r.status_code)
if comment_id:
    r = client(alice).delete(f'/api/comments/{comment_id}/')
    check('alice ne supprime pas le commentaire de bob', r.status_code == 403, r.status_code)
    r = client(bob).patch(f'/api/comments/{comment_id}/', {'content': 'modifié'}, format='json')
    check('bob modifie son propre commentaire', r.status_code == 200, r.status_code)
r = client(alice).post(f'/api/contents/{item.id}/solution/', {'content': 'la vraie'}, format='json')
check('alice écrit sa solution', r.status_code in (200, 201), r.status_code)
r = client(alice).delete(f'/api/contents/{item.id}/')
check('alice supprime son contenu', r.status_code == 204, r.status_code)
item2 = Content.objects.create(title='Intégrales', type='exercise', author=alice)
r = client(staff).delete(f'/api/contents/{item2.id}/')
check('le staff peut supprimer', r.status_code == 204, r.status_code)
r = anon.get('/api/contents/?type=exercise')
check('lecture publique des contenus', r.status_code == 200, r.status_code)

# 3. Connexion par e-mail ou nom, erreurs sans fuite d'information
cache.clear()
r = anon.post('/api/auth/login/', {'identifier': 'ALICE@exemple.fr', 'password': 'Motdepasse-solide-42'}, format='json')
check('connexion par e-mail (casse ignorée)', r.status_code == 200 and 'access' in r.data and 'refresh' in r.data, r.status_code)
tokens = r.data if r.status_code == 200 else {}
r = anon.post('/api/auth/login/', {'identifier': 'alice', 'password': 'Motdepasse-solide-42'}, format='json')
check('connexion par nom d’utilisateur', r.status_code == 200, r.status_code)
if tokens:
    c = APIClient(HTTP_AUTHORIZATION='Bearer ' + tokens['access'])
    r = c.get('/api/auth/user/')
    check('le jeton d’accès fonctionne', r.status_code == 200 and r.data['username'] == 'alice', r.status_code)
    r = anon.post('/api/token/refresh/', {'refresh': tokens['refresh']}, format='json')
    check('le jeton de rafraîchissement fonctionne', r.status_code == 200 and 'access' in r.data, r.status_code)
r = anon.post('/api/auth/login/', {'identifier': 'alice', 'password': 'faux'}, format='json')
check('mauvais mot de passe → 401', r.status_code == 401, r.status_code)

cache.clear()
r = anon.post('/api/auth/register/', {'username': 'carla', 'email': 'Carla@Exemple.fr', 'password': '12345678'}, format='json')
check('mot de passe trop faible refusé', r.status_code == 400 and r.data.get('field') == 'password', r.status_code)
r = anon.post('/api/auth/register/', {'username': 'ca rla!', 'email': 'carla@exemple.fr', 'password': 'Motdepasse-solide-42'}, format='json')
check('nom d’utilisateur invalide refusé', r.status_code == 400 and r.data.get('field') == 'username', r.status_code)
r = anon.post('/api/auth/register/', {'username': 'carla', 'email': 'ALICE@exemple.fr', 'password': 'Motdepasse-solide-42'}, format='json')
check('e-mail déjà pris (casse ignorée)', r.status_code == 400 and r.data.get('field') == 'email', r.status_code)
mail.outbox[:] = []
r = anon.post('/api/auth/register/', {'username': 'carla', 'email': 'Carla@Exemple.fr', 'password': 'Motdepasse-solide-42', 'accept_terms': True, 'age_ok': True}, format='json')
check('inscription valide', r.status_code == 201 and len(mail.outbox) == 1, (r.status_code, len(mail.outbox)))
r = anon.post('/api/auth/login/', {'identifier': 'carla', 'password': 'mauvais'}, format='json')
check('compte non confirmé + mauvais mdp → 401 (rien ne fuit)', r.status_code == 401, r.status_code)
r = anon.post('/api/auth/login/', {'identifier': 'carla@exemple.fr', 'password': 'Motdepasse-solide-42'}, format='json')
check('compte non confirmé + bon mdp → email_not_verified', r.status_code == 403 and r.data.get('code') == 'email_not_verified', r.status_code)
token = re.search(r'token=([^\s]+)', mail.outbox[-1].body).group(1)
r = anon.post('/api/auth/verify-email/', {'token': token}, format='json')
check('confirmation d’e-mail', r.status_code == 200, r.status_code)

# 4. Mot de passe oublié
cache.clear()
mail.outbox[:] = []
r = anon.post('/api/auth/password-reset/', {'email': 'bob@exemple.fr'}, format='json')
check('demande de réinitialisation', r.status_code == 200 and len(mail.outbox) == 1, (r.status_code, len(mail.outbox)))
r = anon.post('/api/auth/password-reset/', {'email': 'personne@exemple.fr'}, format='json')
check('adresse inconnue : même réponse, aucun e-mail', r.status_code == 200 and len(mail.outbox) == 1, len(mail.outbox))
m = re.search(r'uid=([^&\s]+)&token=([^\s]+)', mail.outbox[0].body)
uid, tok = m.group(1), m.group(2)
r = anon.post('/api/auth/password-reset/confirm/', {'uid': uid, 'token': tok, 'password': 'court'}, format='json')
check('nouveau mot de passe faible refusé', r.status_code == 400, r.status_code)
r = anon.post('/api/auth/password-reset/confirm/', {'uid': uid, 'token': tok, 'password': 'Nouveau-mdp-solide-7'}, format='json')
check('réinitialisation réussie', r.status_code == 200, (r.status_code, getattr(r, 'data', None)))
r = anon.post('/api/auth/password-reset/confirm/', {'uid': uid, 'token': tok, 'password': 'Autre-mdp-solide-8'}, format='json')
check('le lien ne sert qu’une fois', r.status_code == 400, r.status_code)
r = anon.post('/api/auth/login/', {'identifier': 'bob', 'password': 'Nouveau-mdp-solide-7'}, format='json')
check('connexion avec le nouveau mot de passe', r.status_code == 200, r.status_code)

# 5. Journaux : jamais de mot de passe en clair
cache.clear()
APILog.objects.all().delete()
from django.test import Client  # noqa: E402  (passe par tous les middlewares)
Client(HTTP_CF_CONNECTING_IP='9.9.9.9').post('/api/auth/login/', {'identifier': 'alice', 'password': 'Secret-Tape-123'},
                                            content_type='application/json')
logs = list(APILog.objects.all())
check('l’échec de connexion est journalisé', len(logs) == 1, len(logs))
check('… sans le mot de passe', all('Secret-Tape-123' not in (l.request_body or '') for l in logs),
      [l.request_body for l in logs])
check('… avec la vraie IP du visiteur', all(l.ip_address == '9.9.9.9' for l in logs), [l.ip_address for l in logs])

# 6. Limitation : les essais en série sur un compte sont bloqués
cache.clear()
codes = [anon.post('/api/auth/login/', {'identifier': 'alice', 'password': f'x{i}'}, format='json').status_code for i in range(17)]
check('essais en série bloqués (429)', codes[-1] == 429 and codes[0] == 401, codes)
r = client(ip='2.2.2.2').post('/api/auth/login/', {'identifier': 'bob', 'password': 'Nouveau-mdp-solide-7'}, format='json')
check('un autre compte n’est pas bloqué', r.status_code == 200, r.status_code)

# 7. Routes d'admin et de test fermées ; écriture anonyme refusée par défaut
check('stats d’audience réservées', anon.get('/api/logs/analytics/stats/').status_code in (401, 403))
check('route de test réservée', anon.get('/api/logs/test/errors/?type=slow').status_code in (401, 403))
check('stats accessibles au staff', client(staff).get('/api/logs/analytics/stats/').status_code == 200)
check('déconnexion sans jeton', anon.post('/api/auth/logout/').status_code == 200)

# 8. Changer d'adresse e-mail exige le mot de passe actuel
cache.clear()
carol = User.objects.create_user('carol', 'carol@exemple.fr', 'Motdepasse-solide-42')
c = client(carol)
r = c.patch('/api/auth/user/update/', {'email': 'pirate@exemple.fr'}, format='json')
check('e-mail sans mot de passe refusé', r.status_code == 400 and r.data.get('code') == 'password_required', r.status_code)
r = c.patch('/api/auth/user/update/', {'email': 'pirate@exemple.fr', 'current_password': 'faux'}, format='json')
check('e-mail avec mauvais mot de passe refusé', r.status_code == 400, r.status_code)
carol.refresh_from_db()
check('… adresse inchangée', carol.email == 'carol@exemple.fr', carol.email)
r = c.patch('/api/auth/user/update/', {'first_name': 'Carole', 'email': 'CAROL@exemple.fr'}, format='json')
check('nom modifiable sans mot de passe (même e-mail)', r.status_code == 200, (r.status_code, getattr(r, 'data', '')))
r = c.patch('/api/auth/user/update/', {'email': 'carole@exemple.fr', 'current_password': 'Motdepasse-solide-42'}, format='json')
carol.refresh_from_db()
check('e-mail changé avec le bon mot de passe', r.status_code == 200 and carol.email == 'carole@exemple.fr', r.status_code)


def jwt_login(username, password, ip):
    r = client(ip=ip).post('/api/auth/login/', {'identifier': username, 'password': password}, format='json')
    assert r.status_code == 200, (r.status_code, r.data)
    return r.data['access'], r.data['refresh']


def refresh_ok(refresh, ip='7.7.7.7'):
    return client(ip=ip).post('/api/token/refresh/', {'refresh': refresh}, format='json').status_code == 200


# 9. Déconnexion : le jeton de rafraîchissement est révoqué
cache.clear()
_, rf = jwt_login('carol', 'Motdepasse-solide-42', '3.3.3.1')
check('jeton valide avant déconnexion', refresh_ok(rf))
check('déconnexion avec jeton', anon.post('/api/auth/logout/', {'refresh': rf}, format='json').status_code == 200)
check('jeton révoqué après déconnexion', not refresh_ok(rf))
check('déconnexion avec jeton bidon', anon.post('/api/auth/logout/', {'refresh': 'abc'}, format='json').status_code == 200)

# 10. Changement de mot de passe : les autres appareils sont déconnectés
cache.clear()
acc1, rf1 = jwt_login('carol', 'Motdepasse-solide-42', '3.3.3.2')
_, rf2 = jwt_login('carol', 'Motdepasse-solide-42', '3.3.3.3')
c1 = APIClient(HTTP_CF_CONNECTING_IP='3.3.3.2', HTTP_AUTHORIZATION=f'Bearer {acc1}')
r = c1.post('/api/auth/password/change/', {'current_password': 'Motdepasse-solide-42',
                                            'new_password': 'Encore-un-mdp-solide-9'}, format='json')
check('changement de mot de passe', r.status_code == 200 and 'refresh' in r.data, r.status_code)
check('autre appareil déconnecté', not refresh_ok(rf2))
check('ancien jeton de cet appareil révoqué', not refresh_ok(rf1))
check('nouveau jeton fourni valide', refresh_ok(r.data['refresh']))

# 11. Réinitialisation par e-mail : toutes les sessions fermées
cache.clear()
from django.contrib.auth.tokens import default_token_generator  # noqa: E402
from django.utils.encoding import force_bytes  # noqa: E402
from django.utils.http import urlsafe_base64_encode  # noqa: E402
_, rf3 = jwt_login('carol', 'Encore-un-mdp-solide-9', '3.3.3.4')
carol.refresh_from_db()
r = anon.post('/api/auth/password-reset/confirm/', {'uid': urlsafe_base64_encode(force_bytes(carol.pk)),
              'token': default_token_generator.make_token(carol), 'password': 'Dernier-mdp-solide-3'}, format='json')
check('réinitialisation acceptée', r.status_code == 200, r.status_code)
check('sessions fermées après réinitialisation', not refresh_ok(rf3))

# 12. Routes retirées et limites ajoutées
check('api-auth retiré', anon.get('/api-auth/login/').status_code == 404)
cache.clear()
codes = [client(carol).post('/api/parse-pdf/', {}, format='multipart').status_code for _ in range(21)]
check('analyse PDF limitée (429)', codes[-1] == 429 and codes[0] != 429, codes[-3:])
cache.clear()
codes = [client(carol).post('/api/classrooms/join/', {'code': f'ZZ{i}'}, format='json').status_code for i in range(31)]
check('codes de classe limités (429)', codes[-1] == 429 and codes[0] != 429, codes[-3:])

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
