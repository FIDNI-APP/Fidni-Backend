"""Connexion avec Google (apps/authentication/google.py + GoogleLoginView) et comptes sans mot de passe,
sur une base SQLite jetable. Google n'est jamais appelé : la vérification du jeton est remplacée par une
fonction factice, puis la vraie fonction est testée avec une clé RSA locale et un faux client JWKS."""
import os
import re
import sys
import tempfile
import time

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-google-auth.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false',
                   'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core import mail  # noqa: E402
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.authentication import google  # noqa: E402
from apps.authentication.views import USERNAME_RE  # noqa: E402
from apps.users.legal import TERMS_VERSION  # noqa: E402
from apps.users.models import GoogleAccount  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
mail.outbox = []
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


# ── Jetons factices : « jeton » → ce que Google aurait renvoyé ─────────────────────────────────
REAL_VERIFY = google.verify_google_credential
FAKE = {}


def fake_verify(token):
    if token not in FAKE:
        raise google.GoogleTokenError('jeton inconnu')
    return dict(FAKE[token])


def ident(token, sub, email, given='', family=''):
    FAKE[token] = {'sub': sub, 'email': email.lower(), 'given_name': given, 'family_name': family,
                   'name': f'{given} {family}'.strip()}


google.verify_google_credential = fake_verify
PWD = 'Motdepasse-solide-42'
anon = APIClient(HTTP_CF_CONNECTING_IP='4.4.4.4')


def gpost(credential, **extra):
    cache.clear()  # limite de 40 requêtes par minute et par IP
    return anon.post('/api/auth/google/', {'credential': credential, **extra}, format='json')


def bearer(access):
    return APIClient(HTTP_CF_CONNECTING_IP='4.4.4.5', HTTP_AUTHORIZATION=f'Bearer {access}')


CONSENT = {'accept_terms': True, 'age_ok': True}

# 1. Jeton refusé
r = gpost('faux')
check('jeton invalide : 400 invalid_token', r.status_code == 400 and r.data.get('code') == 'invalid_token', r.data)
r = anon.post('/api/auth/google/', {}, format='json')
check('sans jeton : 400 invalid_token', r.status_code == 400 and r.data.get('code') == 'invalid_token', r.data)

# 2. Nouveau compte : consentement exigé
ident('amine', 'g-amine', 'Amine.Benali+fidni@gmail.com', 'Amine', 'Benali')
r = gpost('amine')
check('nouveau compte sans consentement : consent_required', r.status_code == 400
      and r.data.get('code') == 'consent_required' and r.data.get('email') == 'amine.benali+fidni@gmail.com'
      and r.data.get('name') == 'Amine Benali', r.data)
r = gpost('amine', accept_terms=True)
check('… une seule case cochée : toujours refusé', r.status_code == 400 and r.data.get('code') == 'consent_required', r.data)
r = gpost('amine', accept_terms='true', age_ok='true')
check('… cases en texte (« true ») : refusé', r.status_code == 400 and r.data.get('code') == 'consent_required', r.data)
check('… aucun compte créé', not User.objects.filter(email__iexact='amine.benali+fidni@gmail.com').exists())

r = gpost('amine', **CONSENT)
check('création avec consentement : 200, created', r.status_code == 200 and r.data.get('created') is True
      and r.data.get('access') and r.data.get('refresh'), r.data)
u = User.objects.get(email='amine.benali+fidni@gmail.com')
check('… pseudo dérivé de l’adresse', u.username == 'amine_benali' and USERNAME_RE.match(u.username), u.username)
check('… sans mot de passe utilisable', not u.has_usable_password())
check('… prénom et nom de Google', (u.first_name, u.last_name) == ('Amine', 'Benali'), (u.first_name, u.last_name))
check('… actif, adresse confirmée', u.is_active and u.profile.email_verified and u.profile.email_verified_at)
check('… conditions acceptées', u.profile.terms_version == TERMS_VERSION and u.profile.terms_accepted_at)
link = GoogleAccount.objects.get(sub='g-amine')
check('… compte Google lié et daté', link.user_id == u.id and link.last_used_at and link.email == u.email)
check('… dernière connexion enregistrée', u.last_login is not None)
data = r.data['user']
check('… réponse de connexion complète (propriétaire)', data.get('email') == u.email
      and data.get('has_password') is False and data.get('google_linked') is True
      and data['profile'].get('onboarding_completed') is False, data)
check('… aucun e-mail de confirmation envoyé', len(mail.outbox) == 0, len(mail.outbox))

r = gpost('amine')
check('reconnexion (même sub) : created = false, même compte', r.status_code == 200 and r.data.get('created') is False
      and r.data['user']['id'] == u.id, r.data)
check('… un seul lien', GoogleAccount.objects.filter(user=u).count() == 1)

# 3. Pseudos dérivés uniques
User.objects.create_user('sara', 'autre@exemple.fr', PWD)
ident('sara', 'g-sara', 'sara@gmail.com')
r = gpost('sara', **CONSENT)
check('pseudo déjà pris : suffixe numérique', r.status_code == 200 and r.data['user']['username'] == 'sara2', r.data)
ident('sara-bis', 'g-sara-bis', 'SARA@hotmail.fr')
r = gpost('sara-bis', **CONSENT)
check('… puis le suivant', r.status_code == 200 and r.data['user']['username'] == 'sara3', r.data)
ident('court', 'g-court', 'a@exemple.fr')
r = gpost('court', **CONSENT)
check('adresse trop courte : pseudo complété', r.status_code == 200 and r.data['user']['username'] == 'a_eleve', r.data)
ident('accents', 'g-accents', 'élodie.m@exemple.fr', 'Élodie', 'M3')
r = gpost('accents', **CONSENT)
name = r.data['user']['username'] if r.status_code == 200 else None
check('accents retirés du pseudo', name == 'elodie_m' and USERNAME_RE.match(name), r.data)
el = User.objects.get(username='elodie_m')
check('… nom Google invalide laissé vide (demandé à l’onboarding)', el.first_name == 'Élodie' and el.last_name == '',
      (el.first_name, el.last_name))

# 4. Liaison à un compte existant par e-mail
karim = User.objects.create_user('karim', 'Karim@Exemple.fr', PWD)
ident('karim', 'g-karim', 'karim@exemple.fr')
r = gpost('karim')
check('compte existant (même adresse) : connecté sans consentement', r.status_code == 200
      and r.data.get('created') is False and r.data['user']['id'] == karim.id, r.data)
karim.refresh_from_db()
check('… lien créé, mot de passe conservé', GoogleAccount.objects.filter(user=karim, sub='g-karim').exists()
      and karim.check_password(PWD))
check('… has_password et google_linked', r.data['user'].get('has_password') is True
      and r.data['user'].get('google_linked') is True, r.data['user'])

ancien = User.objects.create_user('ancien', 'double@exemple.fr', PWD)
User.objects.create_user('recent', 'DOUBLE@exemple.fr', PWD)
ident('double', 'g-double', 'double@exemple.fr')
r = gpost('double')
check('deux comptes avec la même adresse : le plus ancien', r.status_code == 200 and r.data['user']['id'] == ancien.id, r.data)

# 5. Compte en attente de confirmation d'e-mail : activé
attente = User.objects.create_user('attente', 'attente@exemple.fr', PWD)
attente.is_active = False
attente.save()
attente.profile.email_verified = False
attente.profile.save()
attente.profile.terms_version = ''
attente.profile.save()
ident('attente', 'g-attente', 'attente@exemple.fr')
r = gpost('attente')
attente.refresh_from_db()
check('compte en attente : les cases sont redemandées (n’importe qui a pu l’inscrire)', r.status_code == 400
      and r.data.get('code') == 'consent_required' and not attente.is_active
      and not GoogleAccount.objects.filter(sub='g-attente').exists(), r.data)
r = gpost('attente', **CONSENT)
attente.refresh_from_db()
attente.profile.refresh_from_db()
check('… puis activé par Google, même compte', r.status_code == 200 and r.data['user']['id'] == attente.id
      and r.data.get('created') is False and attente.is_active
      and attente.profile.email_verified and attente.profile.email_verified_at, r.data)
check('… le mot de passe d’inscription ne sert plus', not attente.has_usable_password()
      and r.data['user'].get('has_password') is False)
check('… conditions acceptées par la personne qui possède l’adresse', attente.profile.terms_version == TERMS_VERSION)
cache.clear()
r = anon.post('/api/auth/login/', {'identifier': 'attente@exemple.fr', 'password': PWD}, format='json')
check('… l’auteur de l’inscription ne peut plus s’y connecter', r.status_code == 401, r.status_code)

# 6. Compte désactivé : refusé
off = User.objects.create_user('off', 'off@exemple.fr', PWD)
off.is_active = False
off.save()
ident('off', 'g-off', 'off@exemple.fr')
r = gpost('off')
check('compte désactivé : 403 account_disabled', r.status_code == 403 and r.data.get('code') == 'account_disabled', r.data)
check('… aucun lien créé', not GoogleAccount.objects.filter(sub='g-off').exists())
k = User.objects.get(pk=karim.pk)
k.is_active = False
k.save()
r = gpost('karim')
check('compte lié puis désactivé : 403', r.status_code == 403 and r.data.get('code') == 'account_disabled', r.data)
k.is_active = True
k.save()

# 7. Profil : has_password / google_linked réservés au propriétaire
amine_access = gpost('amine').data['access']
me = bearer(amine_access).get('/api/auth/user/')
check('/api/auth/user/ : has_password false, google_linked true', me.status_code == 200
      and me.data.get('has_password') is False and me.data.get('google_linked') is True, me.data)
alice = User.objects.create_user('alice', 'alice@exemple.fr', PWD)
ca = APIClient()
ca.force_authenticate(alice)
d = ca.get('/api/auth/user/').data
check('compte classique : has_password true, google_linked false', d.get('has_password') is True
      and d.get('google_linked') is False, d)
r = ca.get('/api/users/amine_benali/')
d = r.data
check('profil d’un autre : ni has_password ni google_linked', r.status_code == 200
      and 'has_password' not in d and 'google_linked' not in d, list(d))
r = APIClient().get('/api/users/amine_benali/')
d = r.data
check('… ni pour un visiteur', r.status_code == 200 and 'has_password' not in d and 'google_linked' not in d, list(d))
r = bearer(amine_access).get('/api/users/amine_benali/')
check('… mais oui pour lui-même', r.status_code == 200 and r.data.get('has_password') is False
      and r.data.get('google_linked') is True, r.status_code)
User.objects.create_user('ines.k', 'ines@exemple.fr', PWD)  # point permis par USERNAME_RE à l'inscription
r = APIClient().get('/api/users/ines.k/')
check('profil d’un pseudo avec un point : trouvé (pas de 404)', r.status_code == 200 and r.data.get('username') == 'ines.k',
      r.status_code)
check('… ses statistiques aussi, même pour un visiteur (pas d’erreur 500)',
      APIClient().get('/api/users/ines.k/stats/').status_code == 200)
check('… ses favoris : refusés au visiteur (403, pas 500)',
      APIClient().get('/api/users/ines.k/saved_exercises/').status_code == 403)
r = ca.post('/api/revision-lists/', {'name': 'Bac blanc'}, format='json')
d = ca.get('/api/revision-lists/').data
rows = d.get('results', d) if isinstance(d, dict) else d
check('… ni pour l’auteur imbriqué dans une liste', r.status_code == 201 and rows
      and all('has_password' not in (row.get('user') or {}) for row in rows), (r.status_code, rows))

# 8. Impasses d'un compte sans mot de passe
c = bearer(amine_access)
r = c.patch('/api/auth/user/update/', {'email': 'nouvelle@exemple.fr'}, format='json')
check('changer d’e-mail sans mot de passe : set_password_first', r.status_code == 400
      and r.data.get('code') == 'set_password_first', r.data)
r = c.patch('/api/auth/user/update/', {'first_name': 'Amin'}, format='json')
check('… le reste reste modifiable', r.status_code == 200, r.data)

cache.clear()
mail.outbox[:] = []
anon.post('/api/auth/password-reset/', {'email': 'amine.benali+fidni@gmail.com'}, format='json')
check('mot de passe oublié : lien envoyé au compte Google', len(mail.outbox) == 1, len(mail.outbox))
sans = User.objects.create_user('sansmdp', 'sans@exemple.fr')  # ni mot de passe ni Google
cache.clear()
anon.post('/api/auth/password-reset/', {'email': 'sans@exemple.fr'}, format='json')
check('… mais rien pour un compte sans mot de passe ni Google', len(mail.outbox) == 1 and not sans.has_usable_password(),
      len(mail.outbox))

r = c.post('/api/auth/password/change/', {}, format='json')
check('définir un mot de passe : nouveau mot de passe requis', r.status_code == 400, r.data)
r = c.post('/api/auth/password/change/', {'new_password': 'court'}, format='json')
check('… mot de passe faible refusé', r.status_code == 400, r.data)
r = c.post('/api/auth/password/change/', {'new_password': 123456789012}, format='json')
check('… nombre au lieu d’un texte : 400 (pas d’erreur serveur)', r.status_code == 400, r.status_code)
r = c.post('/api/auth/password/change/', {'new_password': 'Nouveau-mdp-solide-7'}, format='json')
u.refresh_from_db()
check('définir un mot de passe sans l’actuel : 200 + jetons', r.status_code == 200 and r.data.get('refresh')
      and u.check_password('Nouveau-mdp-solide-7'), r.data)
cache.clear()
r = anon.post('/api/auth/login/', {'identifier': 'amine.benali+fidni@gmail.com', 'password': 'Nouveau-mdp-solide-7'},
              format='json')
check('… connexion par mot de passe ensuite', r.status_code == 200 and r.data['user'].get('has_password') is True, r.status_code)
c2 = bearer(r.data['access'])
r = c2.post('/api/auth/password/change/', {'new_password': 'Encore-un-mdp-solide-9'}, format='json')
check('… désormais, l’actuel est exigé', r.status_code == 400, r.data)
r = c2.patch('/api/auth/user/update/', {'email': 'amine@exemple.fr', 'current_password': 'Nouveau-mdp-solide-7'},
             format='json')
check('… et l’e-mail se change avec lui', r.status_code == 200, r.data)

r = APIClient(HTTP_CF_CONNECTING_IP='5.5.5.5', HTTP_AUTHORIZATION=f"Bearer {gpost('sara').data['access']}") \
    .post('/api/auth/delete-account/', {}, format='json')
check('supprimer un compte Google sans mot de passe', r.status_code == 200, r.data)
check('… compte et lien supprimés', not User.objects.filter(username='sara2').exists()
      and not GoogleAccount.objects.filter(sub='g-sara').exists())
cache.clear()
r = ca.post('/api/auth/delete-account/', {}, format='json')
check('compte avec mot de passe : toujours exigé', r.status_code == 400 and User.objects.filter(pk=alice.pk).exists(), r.data)

# 9. Onboarding : étape enregistrée, date de fin
co = bearer(gpost('court').data['access'])
r = co.patch('/api/onboarding/', {'current_step': 1}, format='json')
prof = User.objects.get(username='a_eleve').profile
check('onboarding : étape enregistrée', r.status_code == 200 and r.data.get('current_step') == 1
      and prof.onboarding_step == 1, r.data)
check('… relue par GET', co.get('/api/onboarding/').data.get('current_step') == 1)
for bad in ('abc', -1, 99, True, None, '²', 2.5):
    r = co.patch('/api/onboarding/', {'current_step': bad}, format='json')
    check(f'… étape invalide refusée ({bad!r})', r.status_code == 400, r.status_code)
r = co.patch('/api/onboarding/', {'user_type': 'admin'}, format='json')
check('… type de compte inconnu refusé', r.status_code == 400, r.status_code)
check('… pas encore de date de fin', prof.onboarding_completed_at is None)
r = co.post('/api/onboarding/', {'user_type': 'student', 'first_name': 'Ali', 'last_name': 'Amrani',
                                 'school_name': 'Lycée Ibn Sina', 'gender': 'm', 'birth_date': '2009-03-14'},
            format='json')
prof.refresh_from_db()
check('onboarding terminé : date posée', r.status_code == 200 and prof.onboarding_completed
      and prof.onboarding_completed_at is not None, r.data)
first_done = prof.onboarding_completed_at
time.sleep(0.01)
co.post('/api/onboarding/', {'user_type': 'student', 'first_name': 'Ali', 'last_name': 'Amrani',
                             'school_name': 'Lycée Ibn Sina', 'gender': 'm', 'birth_date': '2009-03-14'}, format='json')
prof.refresh_from_db()
check('… la date de la première fin est gardée', prof.onboarding_completed_at == first_done)

# 10. La vraie vérification : clé RSA locale, faux client JWKS
google.verify_google_credential = REAL_VERIFY
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _Key:
    def __init__(self, key):
        self.key = key


class FakeJWKS:
    """Remplace jwt.PyJWKClient : renvoie notre clé publique, ou simule Google injoignable."""
    down = False

    def get_signing_key_from_jwt(self, token):
        if self.down:
            raise jwt.PyJWKClientConnectionError('réseau coupé')
        jwt.get_unverified_header(token)  # en-tête illisible → DecodeError, comme le vrai client
        return _Key(KEY.public_key())


fake_jwks = FakeJWKS()
google._jwks_client = fake_jwks


def token(key=KEY, alg='RS256', **over):
    now = int(time.time())
    claims = {'iss': 'https://accounts.google.com', 'aud': settings.GOOGLE_CLIENT_ID, 'sub': '1098765',
              'email': 'Vrai.Eleve@gmail.com', 'email_verified': True, 'given_name': 'Yasmine',
              'family_name': 'Alaoui', 'name': 'Yasmine Alaoui', 'iat': now, 'exp': now + 3600}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={'kid': 'cle-test'})


def refused(tok):
    try:
        google.verify_google_credential(tok)
    except google.GoogleTokenError:
        return True
    return False


info = google.verify_google_credential(token())
check('vrai jeton : accepté', info == {'sub': '1098765', 'email': 'vrai.eleve@gmail.com', 'given_name': 'Yasmine',
                                       'family_name': 'Alaoui', 'name': 'Yasmine Alaoui'}, info)
check('… émetteur sans https accepté', not refused(token(iss='accounts.google.com')))
check('mauvaise audience refusée', refused(token(aud='123-autre-appli.apps.googleusercontent.com')))
check('mauvais émetteur refusé', refused(token(iss='https://accounts.google.com.pirate.example')))
check('émetteur absent refusé', refused(token(iss=None)))
check('jeton expiré refusé', refused(token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200)))
check('signé par une autre clé refusé', refused(token(key=OTHER)))
check('adresse non confirmée refusée', refused(token(email_verified=False)))
check('adresse absente refusée', refused(token(email=None)))
check('sub absent refusé', refused(token(sub=None)))
check('algorithme « none » refusé', refused(jwt.encode({'sub': 'x', 'aud': settings.GOOGLE_CLIENT_ID,
                                                       'iss': 'accounts.google.com', 'email': 'a@b.fr',
                                                       'email_verified': True}, None, algorithm='none')))
check('n’importe quoi refusé', refused('pas.un.jeton') and refused('') and refused(None) and refused('x' * 5000))

r = gpost(token(aud='123-autre-appli.apps.googleusercontent.com'), **CONSENT)
check('route : mauvaise audience → 400 invalid_token', r.status_code == 400 and r.data.get('code') == 'invalid_token', r.data)
r = gpost(token(iss='https://pirate.example'), **CONSENT)
check('route : mauvais émetteur → 400 invalid_token', r.status_code == 400 and r.data.get('code') == 'invalid_token', r.data)
r = gpost(token(), **CONSENT)
check('route : vrai jeton → compte créé', r.status_code == 200 and r.data.get('created') is True
      and r.data['user']['username'] == 'vrai_eleve', r.data)
fake_jwks.down = True
r = gpost(token())
check('Google injoignable : 503 (pas la faute du jeton)', r.status_code == 503
      and r.data.get('code') == 'google_unavailable', r.data)
fake_jwks.down = False

# 11. Données : le lien Google est dans l'export, sans jeton
exp = bearer(gpost(token()).data['access']).get('/api/auth/my-data/')
body = exp.content.decode()
check('export « Mes données » : compte Google inclus', exp.status_code == 200 and '1098765' in body
      and re.search(r'users\.GoogleAccount', body), exp.status_code)

# 12. Pages servies par Django : la fenêtre de connexion Google peut s'ouvrir
coop = APIClient().get('/sitemap.xml').headers.get('Cross-Origin-Opener-Policy')
check('Cross-Origin-Opener-Policy : same-origin-allow-popups', coop == 'same-origin-allow-popups', coop)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
