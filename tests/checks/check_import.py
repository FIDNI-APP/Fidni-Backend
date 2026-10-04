"""Import de contenus (fiches fidni-fiche/1) : vérifications, conversion, import, mise à jour, figures."""
import copy
import io
import json
import os
import runpy
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-import.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false',
                   'MEDIA_ROOT': os.path.join(tempfile.gettempdir(), 'fidni-import-media')})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))  # taxonomie réelle
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402
from PIL import Image  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.things import importing  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.uploads.models import FileAttachment  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


EXO = {
    'format': 'fidni-fiche/1', 'cle': 'test-derivee-1', 'type': 'exercice', 'titre': 'Dérivée d’un quotient',
    'niveaux': ['2ème bac sm'], 'chapitres': ['Dérivation et étude des fonctions'], 'difficulte': 'facile',
    'source': {'document': 'serie.pdf', 'pages': '1', 'origine': 'original'},
    'blocs': [
        {'type': 'contexte', 'html': '<p>Soit $f(x) = \\dfrac{x^2}{x-1}$ pour $x<1$ ou $x>1$.</p><p><img src="figures/courbe.png" alt="Courbe de f"></p>'},
        {'type': 'question', 'html': '<p>Calculer $f\'(x)$.</p>', 'points': 2, 'notions': ['Dérivée'],
         'solution': '<p>$$f\'(x) = \\dfrac{x(x-2)}{(x-1)^2}$$</p>'},
        {'type': 'question', 'html': '<p>Étudier $f$.</p>', 'sous_questions': [
            {'html': '<p>Signe de $f\'$.</p>', 'points': 1.5, 'solution': '<p>Tableau de signes.</p>'},
            {'html': '<p>Variations.</p>', 'points': 1}]},
    ],
}

# ---------------------------------------------------------------- vérifications sans base
errors, warnings, images = importing.validate(EXO)
check('fiche valide : aucune erreur', errors == [], errors)
check('question sans solution signalée', any('Q2.2' in w for w in warnings), warnings)
check('figure repérée', images == {'figures/courbe.png'}, images)


def errs(mut):
    f = copy.deepcopy(EXO)
    mut(f)
    return ' | '.join(importing.validate(f)[0])


check('« $ » non apparié détecté', 'non apparié' in errs(lambda f: f['blocs'][1].update(html='<p>Calculer $f(x).</p>')))
check('formule en ligne sur deux lignes refusée', 'non apparié' in errs(lambda f: f['blocs'][1].update(html='<p>$a +\nb$</p>')))
check('délimiteur \\( refusé', 'délimiteur' in errs(lambda f: f['blocs'][1].update(html='<p>\\(x\\)</p>')))
check('balise <script> refusée', '<script>' in errs(lambda f: f['blocs'][1].update(html='<p>a</p><script>x</script>')))
check('attribut style refusé', 'style' in errs(lambda f: f['blocs'][1].update(html='<p style="color:red">a</p>')))
check('image sans alt refusée', 'alternatif' in errs(lambda f: f['blocs'][0].update(html='<img src="figures/courbe.png">')))
check('image externe refusée', 'figures/' in errs(lambda f: f['blocs'][0].update(html='<img src="https://x.fr/a.png" alt="a">')))
check('balise mal fermée détectée', 'fermer' in errs(lambda f: f['blocs'][1].update(html='<p><strong>a</p></strong>'))
      or 'ne ferme pas' in errs(lambda f: f['blocs'][1].update(html='<p><strong>a</p></strong>')))
check('barème des sous-questions incohérent', 'annoncés' in errs(lambda f: f['blocs'][2].update(points=5)))
check('origine des droits obligatoire', 'origine' in errs(lambda f: f['source'].pop('origine')))
check('clé invalide refusée', 'cle' in errs(lambda f: f.update(cle='Mauvaise Clé')))
check('question sans texte propre acceptée si elle a des sous-questions',
      importing.validate({**EXO, 'blocs': [{'type': 'question', 'sous_questions': [{'html': '<p>a</p>', 'solution': '<p>b</p>'}]}]})[0] == [])
check('question sans texte ni sous-question refusée',
      'vide' in errs(lambda f: f['blocs'][1].update(html='')))
check('solution au niveau question + sous-questions refusée', 'sous-question' in errs(lambda f: f['blocs'][2].update(solution='<p>x</p>')))

EXAM = {
    'format': 'fidni-fiche/1', 'cle': 'test-bac-2099', 'type': 'examen', 'titre': 'Examen test 2099',
    'niveaux': ['2ème Bac SM'], 'chapitres': ['Suites numériques'], 'difficulte': 'moyen',
    'source': {'document': 'bac.pdf', 'origine': 'officiel'}, 'examen': {'national': True, 'annee': 2099, 'duree_minutes': 240},
    'blocs': [
        {'type': 'partie', 'titre': 'Exercice 1', 'points': 3},
        {'type': 'question', 'html': '<p>Q</p>', 'points': 1, 'solution': '<p>S</p>'},
        {'type': 'question', 'html': '<p>Q</p>', 'points': 2, 'solution': '<p>S</p>'},
        {'type': 'partie', 'titre': 'Exercice 2', 'points': 4},
        {'type': 'question', 'html': '<p>Q</p>', 'points': 3, 'solution': '<p>S</p>'},
    ],
}
e, w, _ = importing.validate(EXAM)
check('barème d’une partie incohérent détecté', any('Exercice 2' in x and '4' in x for x in e), e)
check('total ≠ 20 signalé pour un examen', any('20' in x for x in w), w)
EXAM['blocs'][4]['points'] = 4
check('examen cohérent : aucune erreur', importing.validate(EXAM)[0] == [], importing.validate(EXAM)[0])
st = importing.to_structure(EXAM)
check('partie convertie en bloc « section » avec son barème',
      st['blocks'][0]['type'] == 'section' and st['blocks'][0]['points'] == 3 and st['blocks'][0]['content']['html'] == 'Exercice 1')

LECON = {
    'format': 'fidni-fiche/1', 'cle': 'test-lecon-suites', 'type': 'lecon', 'titre': 'Suites : l’essentiel',
    'niveaux': ['2ème Bac SM'], 'chapitres': ['Suites numériques'], 'source': {'document': 'cours.docx', 'origine': 'original'},
    'sections': [{'titre': 'Définition', 'html': '<div data-callout-type="definition" data-callout-title="Définition"><p>Une suite…</p></div>',
                  'sous_sections': [{'titre': 'Exemple', 'html': '<p>$u_n = 2^n$</p>'}]}],
}
check('leçon avec encadré : valide', importing.validate(LECON)[0] == [], importing.validate(LECON)[0])
check('encadré de type inconnu refusé', 'callout' in ' '.join(importing.validate(
    {**LECON, 'sections': [{'titre': 'x', 'html': '<div data-callout-type="bidule" data-callout-title="x">a</div>'}]})[0]))

st = importing.to_structure(EXO)
html0 = st['blocks'][0]['content']['html']
check('« < » et « > » échappés dans les formules seulement', '$x&lt;1$' in html0 and '$x&gt;1$' in html0 and '<p>' in html0, html0)
mixed = importing.escape_math_in_html('<p>$$a<b$$</p><p>Donc $(v_n)$ et $x>0$.</p>')
check('formule centrée puis en ligne : HTML intact entre les deux',
      mixed == '<p>$$a&lt;b$$</p><p>Donc $(v_n)$ et $x&gt;0$.</p>', mixed)
iv = importing.escape_math_in_html(r'<p>$D = ]-\infty;-3[ \cup ]2;+\infty[$, $[a,b]$, $\sqrt[3]{x}$, $\left]0,\pi\right[$</p>')
check('intervalles à la française : crochets marqués, le reste intact',
      iv == r'<p>$D = \mathopen{]}-\infty;-3\mathclose{[} \cup \mathopen{]}2;+\infty\mathclose{[}$, $[a,b]$, $\sqrt[3]{x}$, $\left]0,\pi\right[$</p>'
      and importing.escape_math_in_html(iv) == iv, iv)
iv2 = importing.escape_math_in_html(r'<p>sur $]-\infty,0[$ et $]0,1]$</p>')
check('intervalle en début de formule corrigé aussi',
      iv2 == r'<p>sur $\mathopen{]}-\infty,0\mathclose{[}$ et $\mathopen{]}0,1]$</p>', iv2)
check('identifiants stables (clé + position)', [b['id'] for b in st['blocks']] == ['test-derivee-1-b1', 'test-derivee-1-b2', 'test-derivee-1-b3']
      and st['blocks'][2]['subQuestions'][1]['id'] == 'test-derivee-1-b3-2')
check('points d’une question = somme des sous-questions', st['blocks'][2]['points'] == 2.5, st['blocks'][2].get('points'))
check('mention de l’auteur conservée', importing.to_structure({**EXO, 'credit': 'M. Haddar'}).get('credit') == 'M. Haddar')
check('mention de l’auteur trop longue refusée', 'credit' in errs(lambda f: f.update(credit='x' * 200)))
check('correction « à vérifier » conservée', importing.to_structure({**EXO, 'a_verifier': True}).get('a_verifier') is True
      and 'a_verifier' not in importing.to_structure(EXO))
check('a_verifier : booléen exigé', 'a_verifier' in errs(lambda f: f.update(a_verifier='oui')))
check('notions converties en identifiants', st['blocks'][1]['meta']['skills'] == ['derivee'], st['blocks'][1].get('meta'))
check('notion hors référentiel refusée, avec la plus proche',
      'derivee' in errs(lambda f: f['blocs'][1].update(notions=['derivation'])),
      errs(lambda f: f['blocs'][1].update(notions=['derivation'])))
from apps.caracteristics.models import Chapter  # noqa: E402
from apps.caracteristics.notions import NOTION_INDEX  # noqa: E402
unknown_chapters = {e['chapter'] for e in NOTION_INDEX.values() if e['chapter']} - set(Chapter.objects.values_list('name', flat=True))
check('référentiel : chaque notion est rangée dans un chapitre de la taxonomie (ou transversale)',
      not unknown_chapters and all(e['label'] for e in NOTION_INDEX.values()), sorted(unknown_chapters))

# ---------------------------------------------------------------- base de données et import
work = tempfile.mkdtemp()
os.makedirs(os.path.join(work, 'figures'))
Image.new('RGB', (60, 40), (255, 255, 255)).save(os.path.join(work, 'figures', 'courbe.png'))
with open(os.path.join(work, 'fiche.json'), 'w', encoding='utf-8') as fh:
    json.dump(EXO, fh, ensure_ascii=False)

e, w, res = importing.check_against_db(EXO)
check('taxonomie trouvée (casse ignorée)', e == [] and res['levels'][0].name == '2ème Bac SM', e)
e, _, _ = importing.check_against_db({**EXO, 'chapitres': ['Suites numerique']})
check('chapitre inconnu : erreur avec suggestion', any('proche' in x and 'Suites numériques' in x for x in e), e)
check('sous-domaine déduit du chapitre (Dérivation → Analyse)', [sf.name for sf in res['subfields']] == ['Analyse'],
      [sf.name for sf in res['subfields']])
e, w, res = importing.check_against_db({**EXO, 'chapitres': ['Limites et continuité'],
                                        'theoremes': ['Théorème des valeurs intermédiaires (TVI)']})
check('TVI rattaché au chapitre « Limites et continuité »', e == [] and not any('théorème' in x for x in w), (e, w))
_, w, _ = importing.check_against_db({**EXO, 'theoremes': ['Loi binomiale']})
check('théorème hors des chapitres indiqués : averti', any('Loi binomiale' in x for x in w), w)

out = io.StringIO()
with redirect_stdout(out):
    try:
        call_command('importer_contenu', work, '--verifier', '--apercu', os.path.join(work, 'apercu.json'), stdout=out)
        ok = True
    except CommandError:
        ok = False
apercu = json.load(open(os.path.join(work, 'apercu.json'), encoding='utf-8'))
check('--verifier : fiche valide, rien d’écrit', ok and Content.objects.count() == 0, out.getvalue())
check('aperçu : figure intégrée en data URI', 'data:image/png;base64,' in apercu['structure']['blocks'][0]['content']['html'])

call_command('importer_contenu', work, stdout=io.StringIO())
c = Content.objects.get(json_content__import__cle='test-derivee-1')
att = FileAttachment.objects.filter(object_id=c.pk).first()
check('import : contenu créé par le compte éditorial', c.author.username == importing.EDITORIAL_USERNAME and not c.author.has_usable_password())
check('import : niveaux, chapitre, difficulté', list(c.class_levels.values_list('name', flat=True)) == ['2ème Bac SM']
      and c.chapters.count() == 1 and c.difficulty == 'easy')
check('import : figure envoyée et lien stable dans le texte',
      att is not None and f'https://api.fidni.fr/api/files/{att.id}/download/' in c.json_content['blocks'][0]['content']['html'])
check('import : source et clé conservées', c.json_content['import']['source']['document'] == 'serie.pdf')
r = APIClient().get(f'/api/contents/{c.pk}/')
check('le contenu importé est servi par l’API', r.status_code == 200 and r.data['json_content']['blocks'][1]['points'] == 2, r.status_code)
names = [lv['name'] for lv in APIClient().get('/api/class-levels/?content_type=exercise').data]
check('niveaux dans l’ordre du programme, même avec le décompte par type',
      names[:4] == ['Tronc commun Sciences', '1ère Bac SM', '2ème Bac SM', '2ème Bac PC'], names)
r = APIClient().get('/api/skills/')
check('/api/skills/ : tout le référentiel, avec libellés', len(r.data) == len(NOTION_INDEX) and all(x['label'] for x in r.data), len(r.data))

pk, display_id, old_att = c.pk, c.display_id, att.id
EXO2 = copy.deepcopy(EXO)
EXO2['blocs'][1]['html'] = '<p>Calculer la dérivée $f\'(x)$.</p>'
with open(os.path.join(work, 'fiche.json'), 'w', encoding='utf-8') as fh:
    json.dump(EXO2, fh, ensure_ascii=False)
call_command('importer_contenu', work, stdout=io.StringIO())
c = Content.objects.get(pk=pk)
check('ré-import : même contenu mis à jour (pas de doublon)', Content.objects.count() == 1 and c.display_id == display_id
      and 'la dérivée' in c.json_content['blocks'][1]['content']['html'])
check('ré-import : ancienne figure supprimée, nouvelle attachée',
      not FileAttachment.objects.filter(id=old_att).exists() and FileAttachment.objects.filter(object_id=pk).count() == 1)

e, _, _ = importing.check_against_db({**EXO, 'cle': 'autre-cle'})
check('doublon de titre détecté', any('doublon' in x for x in e), e)
check('doublon_ok permet de passer outre', importing.check_against_db({**EXO, 'cle': 'autre-cle', 'doublon_ok': True})[0] == [])

bad = tempfile.mkdtemp()
with open(os.path.join(bad, 'fiche.json'), 'w', encoding='utf-8') as fh:
    json.dump({**EXO, 'cle': 'fiche-cassee', 'titre': 'Autre', 'blocs': [{'type': 'question', 'html': '<p>$x</p>'}]}, fh)
try:
    call_command('importer_contenu', bad, stdout=io.StringIO())
    refused = False
except CommandError:
    refused = True
check('fiche en erreur : import refusé, rien d’écrit', refused and not Content.objects.filter(title='Autre').exists())

# ---------------------------------------------------------------- compte éditorial protégé
editor = User.objects.get(username=importing.EDITORIAL_USERNAME)
User.objects.filter(pk=editor.pk).update(date_joined=timezone.now() - timedelta(days=5 * 365), last_login=None)
out = io.StringIO()
call_command('purger_comptes_inactifs', stdout=out)
check('purge des comptes inactifs : compte éditorial épargné', importing.EDITORIAL_USERNAME not in out.getvalue(), out.getvalue())
admin = User.objects.create_superuser('chef', 'chef@x.fr', 'Motdepasse-solide-42')
cl = APIClient()
cl.force_authenticate(admin)
r = cl.post(f'/api/moderation/users/{importing.EDITORIAL_USERNAME}/delete/', {'confirm': importing.EDITORIAL_USERNAME}, format='json')
check('suppression par modération du compte éditorial refusée', r.status_code == 403 and Content.objects.filter(pk=pk).exists(), r.status_code)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
