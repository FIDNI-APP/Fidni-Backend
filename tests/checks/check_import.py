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
        {'type': 'question', 'html': '<p>Calculer $f\'(x)$.</p>', 'points': 2, 'theoremes': ["dérivée d'une fonction composée"],
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
check('a_verifier de la fiche accepté mais ignoré (bandeau retiré le 17/10/2026)',
      'a_verifier' not in importing.to_structure({**EXO, 'a_verifier': True})
      and 'a_verifier' not in errs(lambda f: f.update(a_verifier=True)))
check('a_verifier : booléen exigé', 'a_verifier' in errs(lambda f: f.update(a_verifier='oui')))
check('théorèmes de la question : nom exact du programme (casse ignorée)',
      st['blocks'][1]['meta']['theorems'] == ["Dérivée d'une fonction composée"] and 'skills' not in st['blocks'][1]['meta'],
      st['blocks'][1].get('meta'))
check('question sans théorème (calcul) : pas de clé theorems', 'theorems' not in (st['blocks'][2]['subQuestions'][0].get('meta') or {}))
check('théorème inconnu refusé, avec le plus proche',
      'Théorème des valeurs intermédiaires (TVI)' in errs(lambda f: f['blocs'][1].update(theoremes=['Theoreme des valeurs intermediaires'])),
      errs(lambda f: f['blocs'][1].update(theoremes=['Theoreme des valeurs intermediaires'])))
check('ancien nom de théorème accepté et traduit',
      importing.to_structure({**EXO, 'blocs': [{**EXO['blocs'][1], 'theoremes': ['Théorème de Moivre']}]})['blocks'][0]['meta']['theorems']
      == ['Formule de Moivre'] and not errs(lambda f: f['blocs'][1].update(theoremes=['Théorème de Moivre'])))
check('« notions » refusé (remplacé par « theoremes »)', 'n’existe plus' in errs(lambda f: f['blocs'][1].update(notions=['derivee'])))
check('theoremes : liste de noms exigée', 'liste de noms' in errs(lambda f: f['blocs'][1].update(theoremes='TVI')))
from apps.caracteristics.models import Theorem  # noqa: E402
manquants = set(importing.theoremes_programme().values()) - set(Theorem.objects.values_list('name', flat=True))
check('chaque théorème du programme existe dans la base', not manquants, sorted(manquants))

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
check('TVI rattaché au chapitre « Limites et continuité »', e == [] and not any('TVI' in x for x in w), (e, w))
check('théorème d’une question hors des chapitres indiqués : averti aussi',
      any("Dérivée d'une fonction composée" in x for x in w), w)
_, w, _ = importing.check_against_db({**EXO, 'theoremes': ['Loi binomiale']})
check('théorème hors des chapitres indiqués : averti', any('Loi binomiale' in x for x in w), w)
e, _, res = importing.check_against_db({**EXO, 'niveaux': ['2ème Bac PC'], 'chapitres': ['Limites et continuité']})
check('ancien nom de niveau « 2ème Bac PC » accepté (→ 2ème Bac PC/SVT)', e == [] and [lv.name for lv in res['levels']]
      == ['2ème Bac PC/SVT'], (e, [lv.name for lv in res['levels']]))
# Exercice, examen : seulement le dernier chapitre du programme utilisé (Natsu, 16/10/2026).
e, w, res = importing.check_against_db({**EXO, 'chapitres': ['Limites et continuité', 'Dérivation et étude des fonctions']})
check('DS de dérivabilité : rangé dans « Dérivation » seulement, limites = prérequis (averti)',
      e == [] and [c.name for c in res['chapters']] == ['Dérivation et étude des fonctions']
      and any('prérequis retirés : Limites et continuité' in x for x in w), ([c.name for c in res['chapters']], w))
_, _, res = importing.check_against_db({**EXO, 'chapitres': ['Dérivation et étude des fonctions', 'Fonctions logarithmiques']})
check('dernier chapitre dans l’ordre du programme, quel que soit l’ordre de la fiche',
      [c.name for c in res['chapters']] == ['Fonctions logarithmiques'], [c.name for c in res['chapters']])
_, _, res = importing.check_against_db({**EXO, 'type': 'lecon', 'chapitres': ['Limites et continuité', 'Dérivation et étude des fonctions']})
check('leçon : tous ses chapitres gardés', len(res['chapters']) == 2, [c.name for c in res['chapters']])

import importlib  # noqa: E402
from django.apps import apps as django_apps  # noqa: E402
from django.contrib.auth.models import User as _U  # noqa: E402
from apps.caracteristics.models import Chapter as _Ch, ClassLevel as _CL  # noqa: E402
from apps.things.models import Content as _C  # noqa: E402
_sm = _CL.objects.get(name='2ème Bac SM')
_lim = _Ch.objects.get(name='Limites et continuité', class_levels=_sm)
_der = _Ch.objects.get(name='Dérivation et étude des fonctions', class_levels=_sm)
_auteur = _U.objects.create_user('mig17', 'mig17@x.fr', None)
_ds = _C.objects.create(type='exam', title='DS dérivabilité', author=_auteur, json_content={'version': '2.1', 'blocks': []})
_ds.class_levels.set([_sm]); _ds.chapters.set([_lim, _der])  # noqa: E702
_lc = _C.objects.create(type='lesson', title='Leçon deux chapitres', author=_auteur, json_content={'version': '1.0', 'sections': []})
_lc.class_levels.set([_sm]); _lc.chapters.set([_lim, _der])  # noqa: E702
_m17 = importlib.import_module('apps.things.migrations.0017_chapitre_principal')
_m17.forwards(django_apps, None)
_ds.refresh_from_db()
check('migration 0017 : DS publié ramené à « Dérivation », chapitre retiré noté',
      list(_ds.chapters.all()) == [_der] and _ds.json_content.get('chapitres_retires') == [_lim.pk], _ds.json_content)
check('migration 0017 : leçon intacte', _lc.chapters.count() == 2)
_m17.backwards(django_apps, None)
_ds.refresh_from_db()
check('migration 0017 inverse : chapitres remis', set(_ds.chapters.all()) == {_lim, _der}
      and 'chapitres_retires' not in _ds.json_content)
_suites = _Ch.objects.get(name='Suites numériques', class_levels=_sm)
_ds.chapters.set([_suites, _der])
importlib.import_module('apps.things.migrations.0018_chapitre_principal_ordre_sm').forwards(django_apps, None)
check('2ème Bac SM : dérivation avant suites (ordre de M. Haddar) → un DS fonctions + suites va dans « Suites »',
      list(_ds.chapters.all()) == [_suites], [c.name for c in _ds.chapters.all()])
# Chapitre décidé à la main (CHAPITRES_FORCES) : prioritaire sur « dernier chapitre », à l'import comme pour les publiés.
_, w, res = importing.check_against_db({**EXO, 'cle': 'ds1-2sm-2020', 'type': 'examen',
                                        'chapitres': ['Limites et continuité', 'Dérivation et étude des fonctions']})
check('clé corrigée à la main : « Limites et continuité » malgré la dérivation listée',
      [c.name for c in res['chapters']] == ['Limites et continuité'] and any('CHAPITRES_FORCES' in x for x in w),
      ([c.name for c in res['chapters']], w))
_ds.json_content = {'version': '2.1', 'blocks': [], 'import': {'cle': 'ds1-2sm-2020'}}
_ds.save()
_ds.chapters.set([_der])
importlib.import_module('apps.things.migrations.0019_chapitres_corriges').forwards(django_apps, None)
check('migration 0019 : DS1 2020 publié remis dans « Limites et continuité »', list(_ds.chapters.all()) == [_lim],
      [c.name for c in _ds.chapters.all()])
# Devoir : aussi le chapitre de chacun de ses exercices (Natsu, 17/10/2026 : DS n° 1 de TC aussi « Ensembles de nombres »).
_TVI, _COMP = 'Théorème des valeurs intermédiaires (TVI)', "Dérivée d'une fonction composée"
_DEVOIR = {**EXO, 'cle': 'devoir-deux-exercices', 'type': 'examen', 'chapitres': ['Limites et continuité', 'Dérivation et étude des fonctions'],
           'blocs': [{'type': 'partie', 'titre': 'Exercice 1'}, {'type': 'question', 'html': '<p>a</p>', 'theoremes': [_TVI]},
                     {'type': 'partie', 'titre': 'Exercice 2'}, {'type': 'question', 'html': '<p>b</p>', 'theoremes': [_COMP]}]}
_, w, res = importing.check_against_db(_DEVOIR)
check('devoir : exercice de limites + exercice de dérivation → les deux chapitres',
      {c.name for c in res['chapters']} == {'Limites et continuité', 'Dérivation et étude des fonctions'}
      and not any('prérequis retirés' in x for x in w), ([c.name for c in res['chapters']], w))
_DEVOIR2 = {**_DEVOIR, 'blocs': [{'type': 'partie', 'titre': 'Exercice 1'},
                                 {'type': 'question', 'html': '<p>a</p>', 'theoremes': [_TVI, _COMP]}]}
_, _, res = importing.check_against_db(_DEVOIR2)
check('devoir : un exercice qui utilise limites ET dérivation → « Dérivation » seulement',
      [c.name for c in res['chapters']] == ['Dérivation et étude des fonctions'], [c.name for c in res['chapters']])
_, _, res = importing.check_against_db({**_DEVOIR, 'type': 'exercice'})
check('exercice : toujours le dernier chapitre seulement', [c.name for c in res['chapters']] == ['Dérivation et étude des fonctions'],
      [c.name for c in res['chapters']])
_ds.json_content = {'version': '2.1', 'chapitres_retires': [_lim.pk], 'blocks': [
    {'id': 's1', 'type': 'section', 'content': {'html': 'Exercice 1'}},
    {'id': 'q1', 'type': 'question', 'meta': {'theorems': [_TVI]}},
    {'id': 's2', 'type': 'section', 'content': {'html': 'Exercice 2'}},
    {'id': 'q2', 'type': 'question', 'meta': {}, 'subQuestions': [{'id': 'q2a', 'meta': {'theorems': [_COMP]}}]}]}
_ds.save()
_ds.chapters.set([_der])
_m21 = importlib.import_module('apps.things.migrations.0021_devoirs_chapitre_par_exercice')
_m21.forwards(django_apps, None)
_ds.refresh_from_db()
check('migration 0021 : DS publié remis aussi dans le chapitre de son exercice de limites',
      set(_ds.chapters.all()) == {_lim, _der} and _ds.json_content.get('chapitres_remis') == [_lim.pk]
      and _ds.json_content.get('chapitres_retires') == [], _ds.json_content)
_m21.backwards(django_apps, None)
_ds.refresh_from_db()
check('migration 0021 inverse', list(_ds.chapters.all()) == [_der] and _ds.json_content.get('chapitres_retires') == [_lim.pk],
      _ds.json_content)
# Bandeau « à vérifier » retiré (17/10/2026) : 0022 efface la clé, updated_at intact.
_C.objects.filter(pk=_lc.pk).update(json_content={**_lc.json_content, 'a_verifier': True})
_avant = _C.objects.get(pk=_lc.pk).updated_at
importlib.import_module('apps.things.migrations.0022_retirer_a_verifier').forwards(django_apps, None)
_lc.refresh_from_db()
check('migration 0022 : clé a_verifier effacée partout, updated_at intact',
      not _C.objects.filter(json_content__has_key='a_verifier').exists() and _lc.json_content.get('sections') == []
      and _lc.updated_at == _avant, _lc.json_content)
# Doublons d'énoncé (Natsu, 16/10/2026) : même énoncé qu'un contenu publié du même type, même sous un autre titre.
_copie = _C.objects.create(type='exercise', title='Titre tout autre', author=_auteur,
                           json_content={**importing.to_structure(EXO), 'import': {'cle': 'autre-cle'}})
e, _, _ = importing.check_against_db({**EXO, 'titre': 'Un titre jamais vu'})
check('doublon d’énoncé (autre titre) : refusé', any('même énoncé' in x and 'Titre tout autre' in x for x in e), e)
_presque = json.loads(json.dumps(EXO).replace('Calculer', 'Calculez'))
e, _, _ = importing.check_against_db({**_presque, 'titre': 'Un titre jamais vu'})
check('doublon d’énoncé à la forme près : refusé aussi', any('même énoncé' in x for x in e), e)
e, _, _ = importing.check_against_db({**EXO, 'titre': 'Un titre jamais vu', 'doublon_ok': True})
check('« doublon_ok » (vérifié à la main) : accepté', not any('même énoncé' in x for x in e), e)
_copie.delete()
_devoir = _C.objects.create(type='exam', title='Devoir qui reprend l’exercice', author=_auteur,
                            json_content={**importing.to_structure(EXO), 'import': {'cle': 'devoir-cle'}})
e, _, _ = importing.check_against_db({**EXO, 'titre': 'Un titre jamais vu'})
check('même énoncé dans un devoir (autre type) : pas un doublon', not any('même énoncé' in x for x in e), e)
_devoir.delete()
# Même modèle d'énoncé, autres formules : pas un doublon (17/10/2026, équations avec valeur absolue de deux séries).
_TEXTE = ('Résoudre dans $\\mathbb{R}$ les équations suivantes, en justifiant chaque étape de la résolution par une '
          'propriété de la valeur absolue : ')
_modele = {**EXO, 'cle': 'abs-serie1', 'titre': 'Équations avec valeur absolue',
           'blocs': [{'type': 'question', 'html': f'<p>{_TEXTE}$|x-1|=2$ ; $|x+1|=3$ ; $|2x-1|=5$.</p>'}]}
_publie = _C.objects.create(type='exercise', title='Équations avec valeur absolue', author=_auteur,
                            json_content={**importing.to_structure(_modele), 'import': {'cle': 'abs-serie1'}})
_autre = {**_modele, 'cle': 'abs-serie2',
          'blocs': [{'type': 'question', 'html': f'<p>{_TEXTE}$|x+1|=x+1$ ; $|x^2-1|=x^2-1$ ; $|x-1|=x$.</p>'}]}
e, w, _ = importing.check_against_db(_autre)
check('même texte, autres formules : pas un doublon ; même titre seul = avertissement',
      not any('doublon' in x for x in e) and any('même titre' in x for x in w), (e, w))
e, _, _ = importing.check_against_db({**_modele, 'cle': 'abs-copie', 'titre': 'Autre titre'})
check('mêmes formules et même texte : toujours un doublon', any('même énoncé' in x for x in e), e)
_publie.delete()
# Document de 2ème Bac PC/SVT : exercice et devoir en PC/SVT seulement (Natsu, 18/10/2026).
_PC = '2ème Bac PC/SVT'
_doc_pc = {**EXO, 'niveaux': [_PC, '2ème Bac SM'], 'chapitres': ['Limites et continuité'],
           'source': {'document': 'suites exrcices (2) -2PC.pdf', 'origine': 'autorise'}}
_, w, res = importing.check_against_db(_doc_pc)
check('document 2PC : exercice rangé en PC/SVT seulement (SM retiré, averti)',
      [lv.name for lv in res['levels']] == [_PC] and any('PC/SVT seulement' in x for x in w), ([lv.name for lv in res['levels']], w))
_, _, res = importing.check_against_db({**_doc_pc, 'source': {'document': 'resume (2SM+2PC).pdf', 'origine': 'autorise'}})
check('document « 2SM + 2PC » : les deux niveaux gardés', len(res['levels']) == 2, [lv.name for lv in res['levels']])
_, _, res = importing.check_against_db({**_doc_pc, 'type': 'lecon'})
check('document 2PC : une leçon aussi en PC/SVT seulement', [lv.name for lv in res['levels']] == [_PC],
      [lv.name for lv in res['levels']])
_pcl = _CL.objects.get(name=_PC)
_lim_pc = _Ch.objects.filter(name='Limites et continuité', class_levels=_pcl).first()
_ex_pc = _C.objects.create(type='exercise', title='Exercice de série PC', author=_auteur, json_content={
    'version': '2.1', 'blocks': [], 'import': {'cle': 'serie-pc-ex1', 'source': {'document': 'ds 2-2pc (suite).pdf'}}})
_ex_pc.class_levels.set([_sm, _pcl]); _ex_pc.chapters.set({_lim, _lim_pc})  # noqa: E702
_ex_sm = _C.objects.create(type='exercise', title='Exercice de série SM', author=_auteur, json_content={
    'version': '2.1', 'blocks': [], 'import': {'cle': 'serie-sm-ex1', 'source': {'document': 'suite 2SM.pdf'}}})
_ex_sm.class_levels.set([_sm, _pcl])
_m23 = importlib.import_module('apps.things.migrations.0023_documents_pc_sans_sm')
_m23.forwards(django_apps, None)
_ex_pc.refresh_from_db()
check('migration 0023 : exercice d’un document PC → PC/SVT seulement, chapitres de PC gardés',
      list(_ex_pc.class_levels.all()) == [_pcl] and _lim_pc in _ex_pc.chapters.all()
      and all(ch.class_levels.filter(pk=_pcl.pk).exists() for ch in _ex_pc.chapters.all()),
      ([lv.name for lv in _ex_pc.class_levels.all()], [(ch.name, ch.pk) for ch in _ex_pc.chapters.all()]))
check('migration 0023 : document SM aussi en PC : intact', _ex_sm.class_levels.count() == 2)
_m23.backwards(django_apps, None)
_ex_pc.refresh_from_db()
check('migration 0023 inverse : SM remis', _ex_pc.class_levels.count() == 2 and 'sm_retire' not in _ex_pc.json_content)
_lecon_pc = _C.objects.create(type='lesson', title='Méthodes PC', author=_auteur, json_content={
    'version': '1.0', 'sections': [], 'import': {'cle': 'methodes-pc', 'source': {'document': 'suite méthode (2PC).pdf'}}})
_lecon_pc.class_levels.set([_sm, _pcl])
_m24 = importlib.import_module('apps.things.migrations.0024_lecons_pc_sans_sm')
_m24.forwards(django_apps, None)
check('migration 0024 : leçon d’un document PC → PC/SVT seulement', list(_lecon_pc.class_levels.all()) == [_pcl])
_m24.backwards(django_apps, None)
check('migration 0024 inverse', _lecon_pc.class_levels.count() == 2)
_ex_pc.delete(); _ex_sm.delete(); _lecon_pc.delete()  # noqa: E702
_ds.delete(); _lc.delete(); _auteur.delete()  # noqa: E702  (la suite compte les contenus)

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
      names[:4] == ['Tronc commun Sciences', '1ère Bac SM', '2ème Bac SM', '2ème Bac PC/SVT'], names)
check('/api/skills/ supprimé (plus de notions)', APIClient().get('/api/skills/').status_code == 404)
check('import : théorèmes des questions ajoutés aux théorèmes du contenu', c.theorems.filter(name="Dérivée d'une fonction composée").exists(),
      list(c.theorems.values_list('name', flat=True)))

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
