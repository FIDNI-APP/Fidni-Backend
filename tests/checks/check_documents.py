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

# ── Formules MathType (MTEF v5) et « Éditeur d'équations 3.0 » (MTEF v3) d'un .docx
from apps.documents import mathtype as MT  # noqa: E402

V5 = (bytes([5, 1, 0, 6, 9]) + b'DSMT6\x00' + bytes([0])
      + bytes([1, 0,                                   # LINE
               3, 0, 11, 0, 0,                         # TMPL fraction
               1, 0, 2, 0, 0x88, 0x31, 0, 0,            # LINE « 1 »
               1, 0, 2, 0, 0x83, 0x78, 0,               # LINE « x »
               3, 0, 28, 0, 0, 1, 1, 1, 0, 2, 0, 0x88, 0x32, 0, 0, 0,  # exposant : [vide][2]
               0,                                      # fin de la ligne du dénominateur
               0,                                      # fin du gabarit
               0x02, 0, 0x86, 0x64, 0x22,              # « ≤ »
               0, 0]))                                 # fin de la ligne, fin de l'équation
V3 = bytes([3, 1, 1, 3, 10,
            0x01, 0x02, 0x83, 0x61, 0,                  # LINE, « a »
            0x03, 13, 0, 0,                             # TMPL racine
            0x01, 0x02, 0x88, 0x32, 0, 0x00,            # [2]
            0x11, 0x00,                                 # [index vide], fin du gabarit
            0x00, 0x00])
check('MathType v5 → LaTeX', MT.mtef_vers_latex(V5) == r'\frac{1}{x^{2}}\leqslant', MT.mtef_vers_latex(V5))
check('Éditeur d’équations 3.0 → LaTeX', MT.mtef_vers_latex(V3) == r'a\sqrt{2}', MT.mtef_vers_latex(V3))
casse = 0
for i in range(len(V5)):
    for b in (0, 1, 0x7F, 0xFF):
        try:
            MT.mtef_vers_latex(V5[:i] + bytes([b]) + V5[i + 1:])
        except MT.MathTypeErreur:
            pass
        except Exception:
            casse += 1
check('MathType : un objet abîmé échoue proprement', casse == 0, casse)

# Un .docx avec des objets formule (le flux OLE est remplacé ici par le MTEF lui-même).
reel = MT.mtef_de_ole
MT.mtef_de_ole = lambda octets: octets
objet = ('<w:r><w:object><v:shape><v:imagedata r:id="rIdI{i}"/></v:shape>'
         '<o:OLEObject Type="Embed" ProgID="Equation.{p}" r:id="rIdO{i}"/></w:object></w:r>')
corps = ('<w:p><w:r><w:t xml:space="preserve">On en déduit que </w:t></w:r>' + objet.format(i=0, p='DSMT4')
         + '<w:r><w:t xml:space="preserve"> et </w:t></w:r>' + objet.format(i=1, p='3') + '</w:p>'
         + '<w:p>' + objet.format(i=2, p='DSMT4') + '</w:p>' + '<w:p>' + objet.format(i=3, p='DSMT4') + '</w:p>')
buf = io.BytesIO()
with zipfile.ZipFile(io.BytesIO(docx)) as zin, zipfile.ZipFile(buf, 'w') as zout:
    for it in zin.infolist():
        x = zin.read(it.filename)
        if it.filename == 'word/document.xml':
            x = x.decode().replace('<w:body>', '<w:body>' + corps, 1).encode()
        if it.filename == 'word/_rels/document.xml.rels':
            x = x.decode().replace('</Relationships>', ''.join(
                f'<Relationship Id="rIdO{i}" Type="oleObject" Target="embeddings/oleObject{i}.bin"/>' for i in range(4))
                + '</Relationships>').encode()
        zout.writestr(it, x)
    for i, b in enumerate([V5, V3, V5, b'\x09abime']):
        zout.writestr(f'word/embeddings/oleObject{i}.bin', b)
r = client(alice).post('/api/documents/importer-docx/', {'fichier': SimpleUploadedFile('mt.docx', buf.getvalue())}, format='multipart')
MT.mtef_de_ole = reel
h = r.data.get('html', '') if r.status_code == 201 else ''
check('import : formules MathType en ligne', r'On en déduit que $\displaystyle \frac{1}{x^{2}}\leqslant$ et $a\sqrt{2}$' in h, h[:400])
check('import : formule MathType seule = centrée', r'<p>$$\frac{1}{x^{2}}\leqslant$$</p>' in h, h[:500])
check('import : formule illisible signalée', r.status_code == 201 and any('1 formule' in a for a in r.data['avertissements']),
      r.data.get('avertissements'))

r = client(alice).delete(f'/api/documents/{doc_id}/')
check('supprimer', r.status_code == 204 and not Document.objects.filter(pk=doc_id).exists(), r.status_code)

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
