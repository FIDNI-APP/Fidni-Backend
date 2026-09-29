"""Solutions d'élèves, commentaires avec images, sécurité des envois : SQLite jetable."""
import io
import os
import tempfile
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': os.path.join(tempfile.gettempdir(), 'fidni-sol.sqlite3'), 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists('/tmp/fidni-sol.sqlite3'):
    os.remove('/tmp/fidni-sol.sqlite3')
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
from apps.things.models import Content, ProposedSolution, Comment  # noqa: E402
from apps.uploads.models import FileAttachment  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
settings.MEDIA_ROOT = '/tmp/fidni-sol-media'
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None):
    c = APIClient(HTTP_CF_CONNECTING_IP='1.1.1.1')
    if user:
        c.force_authenticate(user)
    return c


def png(name='copie.png'):
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), 'white').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


prof = User.objects.create_user('prof', 'p@x.fr', 'Motdepasse-solide-42')
alice = User.objects.create_user('alice', 'a@x.fr', 'Motdepasse-solide-42')
bob = User.objects.create_user('bob', 'b@x.fr', 'Motdepasse-solide-42')
ex = Content.objects.create(type='exercise', title='Suites', author=prof, json_content={'blocks': []})
lesson = Content.objects.create(type='lesson', title='Cours', author=prof, json_content={'blocks': []})
a, b, anon = client(alice), client(bob), client()

# --- Envois de fichiers
r = a.post('/api/files/upload/', {'file': png()}, format='multipart')
check('photo PNG acceptée', r.status_code == 201, r.data)
photo_id = r.data.get('id')
r = a.post('/api/files/upload/', {'file': SimpleUploadedFile('x.png', b'<html><script>alert(1)</script></html>', content_type='image/png')}, format='multipart')
check('faux PNG (HTML déguisé) refusé', r.status_code == 400, r.status_code)
r = a.post('/api/files/upload/', {'file': SimpleUploadedFile('x.svg', b'<svg onload="alert(1)"/>', content_type='image/svg+xml')}, format='multipart')
check('SVG refusé', r.status_code == 400, r.status_code)
r = a.post('/api/files/upload/', {'file': SimpleUploadedFile('page.html', png().read(), content_type='image/png')}, format='multipart')
check('extension incohérente refusée', r.status_code == 400, r.status_code)
comment_bob = Comment.objects.create(content_item=ex, author=bob, content='Question ?')
r = a.post('/api/files/upload/', {'file': png(), 'content_type': 'comment', 'object_id': comment_bob.id}, format='multipart')
check('impossible d’accrocher un fichier au commentaire d’un autre',
      r.status_code == 201 and FileAttachment.objects.get(id=r.data['id']).object_id is None, r.data)

# --- Solutions proposées
r = anon.post('/api/proposed-solutions/', {'content': ex.id, 'body': 'x'}, format='json')
check('visiteur : publication refusée', r.status_code in (401, 403), r.status_code)
r = a.post('/api/proposed-solutions/', {'content': ex.id, 'body': ''}, format='json')
check('solution vide refusée', r.status_code == 400, r.data)
r = a.post('/api/proposed-solutions/', {'content': lesson.id, 'body': 'x'}, format='json')
check('pas de solution sur une leçon', r.status_code == 400, r.data)
r = a.post('/api/proposed-solutions/', {'content': ex.id, 'body': '<p>On pose $u_n$…</p>', 'file_ids': [photo_id]}, format='json')
check('solution texte + photo publiée', r.status_code == 201 and len(r.data['attachments']) == 0 or r.status_code == 201, r.data)
sol_a = ProposedSolution.objects.get(author=alice)
check('… photo rattachée à la solution', sol_a.attachments.count() == 1, sol_a.attachments.count())
r = b.post('/api/proposed-solutions/', {'content': ex.id, 'body': 'Ma version', 'file_ids': [photo_id]}, format='json')
sol_b = ProposedSolution.objects.get(author=bob)
check('la photo d’Alice ne peut pas être reprise par Bob', sol_b.attachments.count() == 0 and sol_a.attachments.count() == 1)
r = b.post('/api/proposed-solutions/', {'content': ex.id, 'file_ids': []}, format='json')
check('ni texte ni photo : refusé', r.status_code == 400)
r = b.post(f'/api/proposed-solutions/{sol_a.id}/vote/', {'value': 1}, format='json')
check('vote sur la solution d’Alice', r.status_code == 200 and r.data['vote_count'] == 1, r.data)
r = anon.get('/api/proposed-solutions/', {'content': ex.id})
check('liste publique, la plus votée d’abord', r.status_code == 200 and [s['id'] for s in r.data] == [sol_a.id, sol_b.id],
      [(s['id'], s['vote_count']) for s in r.data] if r.status_code == 200 else r.status_code)
check('… auteur, pièces jointes et « is_mine »', r.data[0]['author']['username'] == 'alice'
      and len(r.data[0]['attachments']) == 1 and r.data[0]['is_mine'] is False)
check('liste sans exercice précisé : vide', anon.get('/api/proposed-solutions/').data == [])
r = b.patch(f'/api/proposed-solutions/{sol_a.id}/', {'body': 'piraté'}, format='json')
check('Bob ne peut pas modifier la solution d’Alice', r.status_code == 403, r.status_code)
r = b.delete(f'/api/proposed-solutions/{sol_a.id}/')
check('Bob ne peut pas la supprimer', r.status_code == 403, r.status_code)
r = a.patch(f'/api/proposed-solutions/{sol_a.id}/', {'body': '<p>Version corrigée</p>'}, format='json')
check('Alice modifie sa solution', r.status_code == 200 and 'corrigée' in r.data['body'], r.data)
r = a.patch(f'/api/proposed-solutions/{sol_a.id}/', {'content': lesson.id}, format='json')
check('une solution ne change pas d’exercice', r.status_code == 400, r.status_code)
r = a.delete(f'/api/proposed-solutions/{sol_a.id}/')
check('Alice supprime sa solution (et ses photos)', r.status_code == 204 and not FileAttachment.objects.filter(id=photo_id).exists())

# --- Commentaires avec image
r = a.post('/api/files/upload/', {'file': png('schema.png')}, format='multipart')
img_id = r.data['id']
r = a.post(f'/api/contents/{ex.id}/comment/', {'content': 'Voir mon schéma', 'file_ids': [img_id]}, format='json')
check('commentaire avec image', r.status_code == 201 and len(r.data['attachments']) == 1, r.data)
r = b.post(f'/api/contents/{ex.id}/comment/', {'content': 'Je le reprends', 'file_ids': [img_id]}, format='json')
check('image déjà rattachée : pas reprise par un autre', r.status_code == 201 and len(r.data['attachments']) == 0, r.data)

comment_id = Comment.objects.filter(author=alice).latest('id').id
r = a.delete(f'/api/comments/{comment_id}/')
check('commentaire supprimé avec son image', r.status_code == 204 and not FileAttachment.objects.filter(id=img_id).exists(), r.status_code)

# --- Limite de publication
cache.clear()
codes = [b.post('/api/proposed-solutions/', {'content': ex.id, 'body': f'essai {i}'}, format='json').status_code for i in range(21)]
check('publication limitée (429)', codes[-1] == 429 and codes[0] == 201, codes[-3:])

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
