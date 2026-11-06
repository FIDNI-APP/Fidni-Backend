"""Avatars lionceaux : attribution à l'inscription et choix par l'élève, sur SQLite jetable."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-avatars.sqlite3')
MEDIA = tempfile.mkdtemp(prefix='fidni-avatars-media')
os.environ.update({
    'DJANGO_SETTINGS_MODULE': 'config.settings',
    'DJANGO_ENV': 'development',
    'DB_ENGINE': 'sqlite',
    'SQLITE_PATH': DB,
    'AWS_STORAGE_ENABLED': 'false',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
})
if os.path.exists(DB):
    os.remove(DB)

import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.files.base import ContentFile  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.users.models import AVATARS_LIONS, avatar_lion_url  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
settings.MEDIA_ROOT = MEDIA
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None):
    c = APIClient(HTTP_CF_CONNECTING_IP='1.1.1.1')
    if user:
        c.force_authenticate(user)
    return c


URL = '/api/users/avatar/choisir/'
VALIDES = {avatar_lion_url(n) for n in AVATARS_LIONS}
PUBLIC = os.path.join(os.path.dirname(BACKEND), 'frontend', 'public', 'avatars')

check('36 lionceaux', len(AVATARS_LIONS) == 36 and len(VALIDES) == 36)
if os.path.isdir(PUBLIC):
    manquants = [n for n in AVATARS_LIONS if not os.path.exists(os.path.join(PUBLIC, f'{n}.webp'))]
    check('chaque lionceau a son image', not manquants, manquants)

u = User.objects.create_user('lionceau_test', 'lionceau@example.com', 'x' * 12)
u.profile.refresh_from_db()
check('nouveau compte : un lionceau au hasard', u.profile.avatar_url in VALIDES, u.profile.avatar_url)
check('plus aucun avatar DiceBear', 'dicebear' not in (u.profile.avatar_url or ''))

r = client().post(URL, {'avatar': 'lion-07'}, format='json')
check('visiteur refusé', r.status_code == 401, r.status_code)

c = client(u)
r = c.post(URL, {'avatar': 'lion-07'}, format='json')
u.profile.refresh_from_db()
check('choix enregistré', r.status_code == 200 and u.profile.avatar_url == avatar_lion_url('lion-07'), (r.status_code, r.data))
check('adresse renvoyée', r.data.get('avatar_url') == avatar_lion_url('lion-07'), r.data)
r = client().get(f'/api/users/{u.username}/')
check('visible sur le profil public', (r.data.get('profile') or {}).get('avatar') == avatar_lion_url('lion-07'), r.status_code)

avant = u.profile.avatar_url
for mauvais in ('lion-37', 'lion-00', 'lion-7', '../../secret', 'https://exemple.test/x.png',
                'javascript:alert(1)', '', None, 7, ['lion-07'], {'a': 1}):
    r = c.post(URL, {'avatar': mauvais}, format='json')
    u.profile.refresh_from_db()
    check(f'refusé : {mauvais!r}', r.status_code == 400 and u.profile.avatar_url == avant, (r.status_code, u.profile.avatar_url))
r = c.post(URL, {}, format='json')
check('refusé : rien', r.status_code == 400, r.status_code)

# Le lionceau remplace une photo envoyée, et le fichier disparaît.
u.profile.avatar_file.save('photo.jpg', ContentFile(b'photo'), save=True)
chemin = u.profile.avatar_file.path
check('photo envoyée en place', os.path.exists(chemin))
r = c.post(URL, {'avatar': 'lion-36'}, format='json')
u.profile.refresh_from_db()
check('le lionceau remplace la photo', r.status_code == 200 and not u.profile.avatar_file
      and u.profile.avatar == avatar_lion_url('lion-36'), u.profile.avatar)
check('le fichier de la photo est supprimé', not os.path.exists(chemin))

# « Retirer » redonne un lionceau.
r = c.delete('/api/users/avatar/')
u.profile.refresh_from_db()
check('retirer : retour à un lionceau', r.status_code == 200 and u.profile.avatar_url in VALIDES, u.profile.avatar_url)

# Le choix d'un élève ne touche pas les autres.
v = User.objects.create_user('lionceau_autre', 'autre@example.com', 'x' * 12)
v.profile.refresh_from_db()
ancien = v.profile.avatar_url
client(u).post(URL, {'avatar': 'lion-01'}, format='json')
v.profile.refresh_from_db()
check('le choix ne touche que son propre compte', v.profile.avatar_url == ancien)

# Migration des comptes existants : seuls les avatars DiceBear changent.
import importlib  # noqa: E402
from django.apps import apps as registre  # noqa: E402
migration = importlib.import_module('apps.users.migrations.0017_avatars_lionceaux')

comptes = {n: User.objects.create_user(f'migration_{n}', f'{n}@example.com', 'x' * 12) for n in
           ('dicebear', 'dicebear2', 'choisi', 'google', 'photo', 'vide')}
DICEBEAR = 'https://api.dicebear.com/7.x/avataaars/svg?seed=Felix'
GOOGLE = 'https://lh3.googleusercontent.com/a/photo'
valeurs = {'dicebear': DICEBEAR, 'dicebear2': DICEBEAR, 'choisi': avatar_lion_url('lion-12'), 'google': GOOGLE,
           'photo': None, 'vide': None}
for n, url in valeurs.items():
    p = comptes[n].profile
    p.avatar_url = url
    p.save()
comptes['photo'].profile.avatar_file.save('photo.jpg', ContentFile(b'photo'), save=True)
fichier = comptes['photo'].profile.avatar_file.name

migration.vers_lionceaux(registre, None)
for u in comptes.values():
    u.profile.refresh_from_db()
check('DiceBear → un lionceau', comptes['dicebear'].profile.avatar_url in VALIDES
      and comptes['dicebear2'].profile.avatar_url in VALIDES, comptes['dicebear'].profile.avatar_url)
check('plus aucune adresse DiceBear en base',
      not u.profile.__class__.objects.filter(avatar_url__startswith='https://api.dicebear.com/').exists())
check('un lionceau déjà choisi ne change pas', comptes['choisi'].profile.avatar_url == avatar_lion_url('lion-12'))
check('une adresse Google ne change pas', comptes['google'].profile.avatar_url == GOOGLE)
check('une photo envoyée ne change pas', comptes['photo'].profile.avatar_file.name == fichier
      and comptes['photo'].profile.avatar_url is None)
check('un compte sans avatar ne change pas', comptes['vide'].profile.avatar_url is None)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
