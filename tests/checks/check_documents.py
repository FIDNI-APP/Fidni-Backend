"""Éditeur de documents « façon Word » (apps/documents) sur une base SQLite jetable : chaque membre ne voit
et ne modifie que ses documents, formules `$…$` gardées telles quelles, garde-fous de taille."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-documents.sqlite3')
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
from rest_framework.test import APIClient  # noqa: E402

from apps.documents.models import Document  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


alice = User.objects.create_user('alice', 'alice@x.fr', 'x')
bob = User.objects.create_user('bob', 'bob@x.fr', 'x')

r = client().get('/api/documents/')
check('visiteur : refusé', r.status_code == 401, r.status_code)

HTML = '<h1>DS 1</h1><p>Soit $f(x)=\\frac{1}{x}$ et</p><p>$$\\int_0^1 x^2\\,dx=\\frac13$$</p>'
r = client(alice).post('/api/documents/', {'title': '  ', 'html': HTML}, format='json')
check('création', r.status_code == 201, r.data)
doc_id = r.data['id']
check('titre vide → « Document sans titre »', r.data['title'] == 'Document sans titre', r.data['title'])
check('formules gardées telles quelles', Document.objects.get(pk=doc_id).html == HTML)

r = client(alice).patch(f'/api/documents/{doc_id}/', {'title': 'Mon DS', 'orientation': 'paysage', 'marges': 'etroite'}, format='json')
check('renommer, mise en page', r.status_code == 200 and r.data['orientation'] == 'paysage' and r.data['marges'] == 'etroite', r.data)

r = client(alice).get('/api/documents/')
rows = r.data['results'] if isinstance(r.data, dict) else r.data
check('liste : sans HTML, avec aperçu du texte', r.status_code == 200 and rows and 'html' not in rows[0]
      and rows[0]['excerpt'].startswith('DS 1'), rows)

r = client(alice).get('/api/documents/?q=ds')
rows = r.data['results'] if isinstance(r.data, dict) else r.data
check('recherche par titre', len(rows) == 1)

r = client(bob).get(f'/api/documents/{doc_id}/')
check('un autre membre ne le lit pas', r.status_code == 404, r.status_code)
r = client(bob).patch(f'/api/documents/{doc_id}/', {'title': 'pirate'}, format='json')
check('ni ne le modifie', r.status_code == 404, r.status_code)
r = client(bob).get('/api/documents/')
rows = r.data['results'] if isinstance(r.data, dict) else r.data
check('ni ne le voit dans sa liste', rows == [], rows)

r = client(alice).patch(f'/api/documents/{doc_id}/', {'html': '<p><img src="data:image/png;base64,AAAA"></p>'}, format='json')
check('image base64 refusée', r.status_code == 400, r.status_code)
r = client(alice).patch(f'/api/documents/{doc_id}/', {'html': 'x' * 2_000_001}, format='json')
check('document trop gros refusé', r.status_code == 400, r.status_code)
r = client(alice).patch(f'/api/documents/{doc_id}/', {'orientation': 'diagonale'}, format='json')
check('orientation inconnue refusée', r.status_code == 400, r.status_code)

r = client(alice).post(f'/api/documents/{doc_id}/dupliquer/')
check('dupliquer', r.status_code == 201 and r.data['title'] == 'Mon DS (copie)' and r.data['html'] == HTML, r.data)
r = client(bob).post(f'/api/documents/{doc_id}/dupliquer/')
check('dupliquer le document d’un autre : refusé', r.status_code == 404, r.status_code)

r = client(alice).delete(f'/api/documents/{doc_id}/')
check('supprimer', r.status_code == 204 and not Document.objects.filter(pk=doc_id).exists(), r.status_code)

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
