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

r = client(alice).patch(f'/api/documents/{doc_id}/', {'entete': {'actif': 1, 'etablissement': ' Lycée Ibn Sina ', 'classe': '2 Bac SM',
                                                                'pirate': '<script>', 'consignes': 'x' * 900}}, format='json')
e = r.data.get('entete', {}) if r.status_code == 200 else {}
check('en-tête : champs connus, nettoyés', r.status_code == 200 and e.get('actif') is True and e.get('etablissement') == 'Lycée Ibn Sina'
      and 'pirate' not in e and len(e.get('consignes', '')) == 300, r.data)
r = client(alice).patch(f'/api/documents/{doc_id}/', {'entete': 'n’importe quoi'}, format='json')
check('en-tête invalide refusé', r.status_code == 400, r.status_code)

r = client(alice).post(f'/api/documents/{doc_id}/dupliquer/')
check('dupliquer (avec l’en-tête)', r.status_code == 201 and r.data['title'] == 'Mon DS (copie)' and r.data['html'] == HTML
      and r.data['entete'].get('classe') == '2 Bac SM', r.data)
r = client(bob).post(f'/api/documents/{doc_id}/dupliquer/')
check('dupliquer le document d’un autre : refusé', r.status_code == 404, r.status_code)

# ── Word (.docx) : export puis réimport (pandoc)
import io  # noqa: E402
import re  # noqa: E402
import zipfile  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

WORD = ('<h2>Exercice 1</h2><p style="text-align: center">Centré</p><p>Soit $f(x)=\\dfrac{\\ln x}{x}$ et $a &lt; b$.</p>'
        '<p>$$\\int_0^1 f(x)\\,\\mathrm{d}x=\\frac13\\tag{1}$$</p>'
        '<div data-callout-type="theorem"><p>Toute suite croissante majorée converge.</p></div>'
        '<div data-page-break=""></div><ol><li><p>Calculer $\\lim\\limits_{x\\to0^+} f(x)$.</p></li></ol>'
        '<p>$$%TV{"x":1}\n\\begin{array}{c|ccc} x &amp; 0 &amp; 1 \\\\ \\hline f &amp; - &amp; + \\end{array}$$</p>'
        '<p><img src="https://evil.example/x.png"></p>')
d = client(alice).post('/api/documents/', {'title': 'Devoir Word', 'html': WORD, 'orientation': 'paysage',
                                           'entete': {'actif': True, 'type': 'Devoir n° 2', 'classe': '1 Bac'}},
                       format='json').data
r = client(alice).get(f'/api/documents/{d["id"]}/docx/')
docx = b''.join(r.streaming_content) if getattr(r, 'streaming', False) else r.content
check('export Word', r.status_code == 200 and docx[:2] == b'PK' and 'devoir-word.docx' in r['Content-Disposition'], r.status_code)
xml = zipfile.ZipFile(io.BytesIO(docx)).read('word/document.xml').decode()
check('export : vraies équations Word', xml.count('<m:oMath') >= 4, xml.count('<m:oMath'))
check('export : saut de page, paysage, en-tête, encadré numéroté',
      'w:type="page"' in xml and 'w:orient="landscape"' in xml and 'Devoir n° 2' in xml and 'Théorème 1' in xml
      and 'FIDNI-SAUT' not in xml and 'TV{' not in xml)
check('export : image extérieure ignorée', 'evil' not in xml and '<pic:pic' not in xml)
r = client(bob).get(f'/api/documents/{d["id"]}/docx/')
check('export du document d’un autre : refusé', r.status_code == 404, r.status_code)

r = client(alice).post('/api/documents/importer-docx/', {'fichier': SimpleUploadedFile('DS 2.docx', docx)}, format='multipart')
h = r.data.get('html', '') if r.status_code == 201 else ''
check('import Word', r.status_code == 201 and r.data['title'] == 'DS 2', r.data)
maths = re.findall(r'\$\$?[^$]+\$\$?', h)
check('import : formules en LaTeX', '$f(x) = \\frac{\\ln x}{x}$' in h.replace('\\dfrac', '\\frac') and '$a &lt; b$' in h
      and any('\\int' in m for m in maths) and '<h2>Exercice 1</h2>' in h and '<ol' in h, h[:600])
check('import : pas de style ni de classe', 'class=' not in h and 'style=' not in h and '<span' not in h, h[:300])
r = client(alice).post('/api/documents/importer-docx/', {'fichier': SimpleUploadedFile('x.docx', b'pas un zip')}, format='multipart')
check('import : fichier invalide refusé', r.status_code == 400 and '.docx' in r.data['detail'], r.data)

r = client(alice).delete(f'/api/documents/{doc_id}/')
check('supprimer', r.status_code == 204 and not Document.objects.filter(pk=doc_id).exists(), r.status_code)

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
