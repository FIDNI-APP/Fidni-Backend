"""Suppression de compte (par l'utilisateur / par la modération) : SQLite jetable."""
import io
import os
import tempfile
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': os.path.join(tempfile.gettempdir(), 'fidni-del.sqlite3'), 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists('/tmp/fidni-del.sqlite3'):
    os.remove('/tmp/fidni-del.sqlite3')
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from django.conf import settings  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from PIL import Image  # noqa: E402
from apps.things.models import Content, Comment, ProposedSolution  # noqa: E402
from apps.interactions.models import Vote, RevisionList  # noqa: E402
from apps.uploads.models import FileAttachment  # noqa: E402
from apps.users.account_deletion import DELETED_USERNAME  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
settings.MEDIA_ROOT = '/tmp/fidni-del-media'
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None, ip='1.1.1.1'):
    c = APIClient(HTTP_CF_CONNECTING_IP=ip)
    if user:
        c.force_authenticate(user)
    return c


def png(name='img.png'):
    buf = io.BytesIO()
    Image.new('RGB', (20, 20), 'white').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


PW = 'Motdepasse-solide-42'
alice = User.objects.create_user('alice', 'a@x.fr', PW)
bob = User.objects.create_user('bob', 'b@x.fr', PW)
carol = User.objects.create_user('carol', 'c@x.fr', PW)
admin = User.objects.create_user('modo', 'm@x.fr', PW, is_staff=True)
root = User.objects.create_user('root', 'r@x.fr', PW, is_staff=True, is_superuser=True)
a = client(alice)

# ----- Alice publie, commente (avec image), propose une solution (avec photo), vote, range…
ex = Content.objects.create(type='exercise', title='Suites', author=alice, json_content={'blocks': []})
ex_bob = Content.objects.create(type='exercise', title='Dérivées', author=bob, json_content={'blocks': []})
img_c = a.post('/api/files/upload/', {'file': png('schema.png')}, format='multipart').data['id']
a.post(f'/api/contents/{ex_bob.id}/comment/', {'content': 'Voir mon schéma', 'file_ids': [img_c]}, format='json')
img_s = a.post('/api/files/upload/', {'file': png('copie.png')}, format='multipart').data['id']
a.post('/api/proposed-solutions/', {'content': ex_bob.id, 'body': 'Ma solution', 'file_ids': [img_s]}, format='json')
loose = a.post('/api/files/upload/', {'file': png('brouillon.png')}, format='multipart').data['id']  # jamais publiée
a.post(f'/api/contents/{ex_bob.id}/vote/', {'value': 1}, format='json')
RevisionList.objects.create(user=alice, name='Bac blanc')
login = client(ip='9.9.9.9').post('/api/auth/login/', {'identifier': 'alice', 'password': PW}, format='json').data
check('préparation : contenus, votes, fichiers en place', Vote.objects.filter(user=alice).count() == 1
      and FileAttachment.objects.filter(uploaded_by=alice).count() == 3)

# ----- Suppression par l'utilisateur
r = a.post('/api/auth/delete-account/', {'password': 'faux'}, format='json')
check('mauvais mot de passe : refusé', r.status_code == 400 and User.objects.filter(username='alice').exists(), r.status_code)
r = client(root).post('/api/auth/delete-account/', {'password': PW}, format='json')
check('un superadmin ne peut pas se supprimer depuis le site', r.status_code == 403, r.status_code)
r = a.post('/api/auth/delete-account/', {'password': PW}, format='json')
check('suppression par l’utilisateur acceptée', r.status_code == 200, r.data)
check('… le compte n’existe plus', not User.objects.filter(username='alice').exists())
ghost = User.objects.get(username=DELETED_USERNAME)
check('… exercice conservé, attribué à « Compte supprimé »', Content.objects.get(id=ex.id).author_id == ghost.id)
check('… commentaire conservé', Comment.objects.filter(author=ghost, content='Voir mon schéma').exists())
check('… solution proposée conservée avec sa photo', ProposedSolution.objects.get(author=ghost).attachments.count() == 1)
check('… images des contributions conservées', FileAttachment.objects.filter(id__in=[img_c, img_s], uploaded_by=ghost).count() == 2)
check('… fichier personnel non publié effacé', not FileAttachment.objects.filter(id=loose).exists())
check('… votes effacés', Vote.objects.filter(user_id__isnull=True).count() == 0 and Vote.objects.count() == 0)
check('… listes de révision effacées', not RevisionList.objects.filter(name='Bac blanc').exists())
check('… compte fantôme inactif, sans mot de passe utilisable', not ghost.is_active and not ghost.has_usable_password())
r = client(ip='8.8.8.8').post('/api/token/refresh/', {'refresh': login['refresh']}, format='json')
check('… sessions ouvertes révoquées', r.status_code == 401, r.status_code)
r = client().get(f'/api/contents/{ex.id}/')
check('auteur affiché « Compte supprimé », sans avatar', r.data['author']['username'] == DELETED_USERNAME
      and r.data['author']['is_deleted'] is True and r.data['author']['avatar'] is None, r.data['author'])
check('pas de page de profil pour « Compte supprimé »', client().get(f'/api/users/{DELETED_USERNAME}/').status_code == 404)
r = client(ip='7.7.7.7').post('/api/auth/login/', {'identifier': DELETED_USERNAME, 'password': ''}, format='json')
check('impossible de se connecter en « Compte supprimé »', r.status_code in (400, 401), r.status_code)
r = client(ip='6.6.6.6').post('/api/auth/register/', {'username': DELETED_USERNAME, 'email': 'z@x.fr', 'password': PW}, format='json')
check('nom « Compte supprimé » impossible à prendre à l’inscription', r.status_code == 400, r.status_code)

# ----- Deuxième suppression : même compte fantôme
cache.clear()
client(bob).post('/api/auth/delete-account/', {'password': PW}, format='json')
check('deuxième suppression : même compte fantôme réutilisé', User.objects.filter(username=DELETED_USERNAME).count() == 1
      and Content.objects.get(id=ex_bob.id).author_id == ghost.id)

# ----- Modération
ex_carol = Content.objects.create(type='exercise', title='Contenu inapproprié', author=carol, json_content={'blocks': []})
Comment.objects.create(content_item=ex, author=carol, content='spam')
r = client(bob if User.objects.filter(pk=bob.pk).exists() else carol).post('/api/moderation/users/carol/delete/', {'confirm': 'carol'}, format='json')
check('modération : réservée aux admins', r.status_code in (401, 403), r.status_code)
m = client(admin)
r = m.post('/api/moderation/users/carol/delete/', {'confirm': 'Carol'}, format='json')
check('modération : confirmation exacte exigée', r.status_code == 400 and User.objects.filter(username='carol').exists(), r.status_code)
r = m.post('/api/moderation/users/root/delete/', {'confirm': 'root'}, format='json')
check('modération : impossible de supprimer un admin', r.status_code == 403, r.status_code)
r = m.post(f'/api/moderation/users/{DELETED_USERNAME}/delete/', {'confirm': DELETED_USERNAME}, format='json')
check('modération : « Compte supprimé » intouchable', r.status_code == 404, r.status_code)
r = m.post('/api/moderation/users/carol/delete/', {'confirm': 'carol'}, format='json')
check('modération : compte supprimé', r.status_code == 200 and not User.objects.filter(username='carol').exists(), r.data)
check('… son contenu supprimé aussi', not Content.objects.filter(id=ex_carol.id).exists()
      and not Comment.objects.filter(content='spam').exists())

# ----- Commande
dave = User.objects.create_user('dave', 'd@x.fr', PW)
Content.objects.create(type='exercise', title='Dave', author=dave, json_content={'blocks': []})
call_command('supprimer_compte', 'dave', stdout=io.StringIO())
check('commande supprimer_compte (contenu conservé)', Content.objects.get(title='Dave').author_id == ghost.id)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
