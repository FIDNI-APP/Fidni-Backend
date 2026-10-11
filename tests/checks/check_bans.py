"""Bannir un compte (users/bans.py) et pseudos insultants (authentication/pseudos.py), sur une base SQLite
jetable : adresse, compte Google et IP d'un compte supprimé par la modération ne recréent plus de compte."""
import os
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-bans.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false',
                   'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.authentication import google  # noqa: E402
from apps.authentication.pseudos import pseudo_interdit  # noqa: E402
from apps.users.bans import ban_reason, ip_key, normalize_email  # noqa: E402
from apps.users.legal import purge_old_logs  # noqa: E402
from apps.users.models import Bannissement, GoogleAccount, UserProfile  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


FAKE = {}
google.verify_google_credential = lambda token: dict(FAKE[token]) if token in FAKE else (_ for _ in ()).throw(
    google.GoogleTokenError('jeton inconnu'))


def ident(token, sub, email):
    FAKE[token] = {'sub': sub, 'email': email.lower(), 'given_name': '', 'family_name': '', 'name': ''}


PWD = 'Motdepasse-solide-42'
CONSENT = {'accept_terms': True, 'age_ok': True}


def client(ip='5.5.5.5', user=None):
    cache.clear()  # limites de requêtes par IP
    c = APIClient(HTTP_CF_CONNECTING_IP=ip)
    if user is not None:
        c.force_authenticate(user)
    return c


def register(username, email, ip='5.5.5.5'):
    return client(ip).post('/api/auth/register/', {'username': username, 'email': email, 'password': PWD, **CONSENT},
                           format='json')


def gpost(token, ip='5.5.5.5'):
    return client(ip).post('/api/auth/google/', {'credential': token, **CONSENT}, format='json')


# ── Normalisation
check('Gmail : points, « +suite » et googlemail ramenés à la même boîte',
      normalize_email('Amine.B+fidni@GoogleMail.com') == 'amineb@gmail.com' == normalize_email('amineb@gmail.com'))
check('autre domaine : « +suite » retiré, points gardés', normalize_email('a.b+x@Yahoo.fr') == 'a.b@yahoo.fr')
check('IPv6 : préfixe /64', ip_key('2a01:e0a:1:2:aaaa:bbbb:cccc:dddd') == ip_key('2a01:e0a:1:2::1') == '2a01:e0a:1:2::/64')
check('IPv4 telle quelle, IP invalide ignorée', ip_key('41.2.3.4') == '41.2.3.4' and ip_key('pas-une-ip') is None)

# ── IP retenues à l'inscription et à la connexion
r = register('troll_un', 'Troll.Un+x@gmail.com', ip='41.10.0.1')
troll = User.objects.get(username='troll_un')
check('inscription : IP retenue (inscription et dernière)', r.status_code == 201
      and troll.profile.signup_ip == '41.10.0.1' and troll.profile.last_ip == '41.10.0.1', (r.status_code, r.data))
troll.is_active = True
troll.save()
UserProfile.objects.filter(user=troll).update(email_verified=True)
r = client('41.10.0.2').post('/api/auth/login/', {'identifier': 'troll_un', 'password': PWD}, format='json')
troll.profile.refresh_from_db()
check('connexion : dernière IP mise à jour', r.status_code == 200 and troll.profile.last_ip == '41.10.0.2', r.status_code)
cache.clear()
r2 = APIClient(HTTP_CF_CONNECTING_IP='41.10.0.3').post('/api/token/refresh/', {'refresh': r.data['refresh']}, format='json')
troll.profile.refresh_from_db()
check('renouvellement de session : dernière IP mise à jour', r2.status_code == 200 and troll.profile.last_ip == '41.10.0.3',
      (r2.status_code, troll.profile.last_ip))
GoogleAccount.objects.create(user=troll, sub='sub-troll', email='troll.gmail@gmail.com')

# ── Modération : supprimer ET bannir
admin = User.objects.create_superuser('admin_bans', 'admin@x.fr', PWD)
r = client(user=admin).post('/api/moderation/users/troll_un/delete/', {'confirm': 'troll_un', 'bannir': True}, format='json')
banned = r.data.get('banned') if r.status_code == 200 else None
check('modération : compte supprimé et banni', r.status_code == 200 and not User.objects.filter(username='troll_un').exists()
      and banned and banned['email'] and banned['google'] and len(banned['ip']) == 3, (r.status_code, banned))
check('adresse bannie à vie, IP 30 jours',
      Bannissement.objects.get(kind='email', value='trollun@gmail.com').expires_at is None
      and all(b.expires_at and b.expires_at > timezone.now() + timedelta(days=29)
              for b in Bannissement.objects.filter(kind='ip')))

# ── La même personne ne recrée pas de compte
r = register('troll_deux', 'trollun@gmail.com', ip='8.8.8.8')
check('inscription : même adresse refusée (sans dire pourquoi)', r.status_code == 400 and r.data.get('code') == 'banned', r.data)
r = register('troll_trois', 't.r.o.l.l.u.n+autre@googlemail.com', ip='8.8.8.8')
check('inscription : variante Gmail de la même adresse refusée', r.status_code == 400 and r.data.get('code') == 'banned', r.data)
r = register('troll_quatre', 'nouvelle@yahoo.fr', ip='41.10.0.2')
check('inscription : depuis une IP bannie, refusée', r.status_code == 400 and r.data.get('code') == 'banned', r.data)
ident('g-troll', 'sub-troll', 'autre.adresse@gmail.com')
r = gpost('g-troll', ip='9.9.9.9')
check('Google : même compte Google refusé', r.status_code == 403 and r.data.get('code') == 'banned', r.data)
ident('g-mail', 'sub-neuf', 'troll.un@gmail.com')
r = gpost('g-mail', ip='9.9.9.9')
check('Google : adresse bannie refusée', r.status_code == 403 and r.data.get('code') == 'banned', r.data)
ident('g-ip', 'sub-neuf-2', 'quelquun@gmail.com')
r = gpost('g-ip', ip='41.10.0.1')
check('Google : nouveau compte depuis une IP bannie refusé', r.status_code == 403 and r.data.get('code') == 'banned', r.data)

# ── Les autres ne sont pas gênés
membre = User.objects.create_user('membre_ok', 'membre@ok.fr', PWD)
r = client('41.10.0.1').post('/api/auth/login/', {'identifier': 'membre_ok', 'password': PWD}, format='json')
check('membre existant : se connecte depuis une IP bannie', r.status_code == 200, r.status_code)
GoogleAccount.objects.create(user=membre, sub='sub-membre', email='membre@ok.fr')
ident('g-membre', 'sub-membre', 'membre@ok.fr')
r = gpost('g-membre', ip='41.10.0.1')
check('membre existant : connexion Google depuis une IP bannie', r.status_code == 200, (r.status_code, r.data))
r = register('eleve_sain', 'eleve@sain.fr', ip='7.7.7.7')
check('autre adresse, autre IP : inscription acceptée', r.status_code == 201, r.data)
Bannissement.objects.filter(kind='ip').update(expires_at=timezone.now() - timedelta(minutes=1))
check('IP bannie expirée : plus bloquante', ban_reason(ip='41.10.0.2') is None)
r = register('eleve_ip', 'eleve@ip.fr', ip='41.10.0.2')
check('IP expirée : inscription acceptée', r.status_code == 201, r.data)
purge_old_logs()
check('purge : IP expirées supprimées, adresses gardées', not Bannissement.objects.filter(kind='ip').exists()
      and Bannissement.objects.filter(kind='email').exists())

# ── Pilotage › Membres : liste, ajout à la main, débannir (administrateurs seulement)
eleve = User.objects.get(username='eleve_sain')
check('liste : refusée à un élève', client(user=eleve).get('/api/pilotage/bannis/').status_code in (401, 403))
r = client(user=admin).get('/api/pilotage/bannis/')
check('liste : bannissements en cours', r.status_code == 200 and any(b['value'] == 'trollun@gmail.com' for b in r.data['results']))
r = client(user=admin).post('/api/pilotage/bannis/', {'kind': 'email', 'value': 'L7WAY67@Gmail.com', 'motif': 'pseudo'}, format='json')
check('ajout à la main d’une adresse (normalisée)', r.status_code == 201 and r.data['value'] == 'l7way67@gmail.com', r.data)
r = register('revenant', 'l7way67@gmail.com', ip='6.6.6.6')
check('adresse ajoutée à la main : inscription refusée', r.status_code == 400 and r.data.get('code') == 'banned', r.data)
r = client(user=admin).post('/api/pilotage/bannis/', {'kind': 'ip', 'value': 'n’importe quoi'}, format='json')
check('ajout : IP invalide refusée', r.status_code == 400, r.data)
ban_id = Bannissement.objects.get(value='l7way67@gmail.com').id
r = client(user=admin).delete(f'/api/pilotage/bannis/{ban_id}/')
check('débannir', r.status_code == 204 and not Bannissement.objects.filter(pk=ban_id).exists(), r.status_code)
r = register('revenant', 'l7way67@gmail.com', ip='6.6.6.6')
check('débanni : inscription acceptée (pseudo correct)', r.status_code == 201, r.data)

# ── Pseudos insultants
for name in ('l7way67', 'L7wa_x', 's4lope', 'fdp_2', 'zb.77', 'qahba12', 'nique_ta'):
    check(f'pseudo refusé : {name}', pseudo_interdit(name))
for name in ('zbida', 'amine_b', '7amza', 'technique_x', 'unique', 'orbite', 'khraibi', 'lhwa_zwin', 'zebiba', 'connexion'):
    check(f'pseudo accepté : {name}', not pseudo_interdit(name))
r = register('l7way68', 'neuf@neuf.fr', ip='3.3.3.3')
check('inscription : pseudo insultant refusé', r.status_code == 400 and r.data.get('field') == 'username', r.data)
r = client(user=eleve).patch('/api/users/me/', {'username': 'Connard_99'}, format='json')
check('changement de pseudo : insulte refusée', r.status_code == 400, (r.status_code, r.data))
ident('g-insulte', 'sub-insulte', 'l7wa.boy@gmail.com')
r = gpost('g-insulte', ip='3.3.3.4')
check('Google : adresse insultante → pseudo neutre', r.status_code == 200
      and User.objects.get(google_accounts__sub='sub-insulte').username.startswith('eleve'), (r.status_code, r.data))

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
