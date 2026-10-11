"""Indication : la « Méthode : » en tête d'une solution devient l'indication de la question (bouton du site)."""
import copy
import importlib
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-indications.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from django.apps import apps as django_apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Subject  # noqa: E402
from apps.things import importing  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.things.structure_utils import merge_hints_into_solutions, move_methods_to_hints, split_method  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


# ---------------------------------------------------------------- découpe
SOL = ('<p><strong>Méthode :</strong> forme indéterminée $\\frac{0}{0}$ : on factorise par $x - 2$.</p>'
       '<p>Pour $x \\neq 2$, on a…</p><p>Donc la limite vaut $2$.</p>')
hint, rest = split_method(SOL)
check('méthode séparée (texte et formules gardés, sans l’étiquette, majuscule en tête)',
      hint == '<p>Forme indéterminée $\\frac{0}{0}$ : on factorise par $x - 2$.</p>', hint)
check('le raisonnement reste la solution', rest == '<p>Pour $x \\neq 2$, on a…</p><p>Donc la limite vaut $2$.</p>', rest)
check('sans « Méthode : » : rien ne change', split_method('<p>On a $f(0)=1$.</p>') == (None, '<p>On a $f(0)=1$.</p>'))
check('« Méthode : » seule (rien après) : gardée dans la solution',
      split_method('<p><strong>Méthode :</strong> on dérive.</p>')[0] is None)
check('variantes tolérées (espace insécable, sans accent)',
      split_method('<p><strong>Methode&nbsp;:</strong> idée</p><p>suite</p>')[0] == '<p>Idée</p>')

# ---------------------------------------------------------------- structure : aller-retour
st = {'version': '2.1', 'blocks': [
    {'id': 'b1', 'type': 'question', 'content': {'type': 'text', 'html': '<p>Q1</p>'},
     'solution': {'type': 'text', 'html': SOL}, 'subQuestions': []},
    {'id': 'b2', 'type': 'question', 'content': {'type': 'text', 'html': '<p>Q2</p>'}, 'subQuestions': [
        {'id': 's1', 'content': {'type': 'text', 'html': '<p>a</p>'},
         'solution': {'type': 'text', 'html': '<p><strong>Méthode :</strong> idée a</p><p>calcul a</p>'}},
        {'id': 's2', 'content': {'type': 'text', 'html': '<p>b</p>'},
         'solution': {'type': 'text', 'html': '<p>calcul b sans méthode</p>'}}]},
]}
original = copy.deepcopy(st)
n = move_methods_to_hints(st)
check('questions et sous-questions converties (2 sur 3)', n == 2, n)
check('indication sur la sous-question', st['blocks'][1]['subQuestions'][0]['hint']['html'] == '<p>Idée a</p>')
check('pas d’indication inventée', 'hint' not in st['blocks'][1]['subQuestions'][1])
check('deuxième passage sans effet (migration rejouable)', move_methods_to_hints(st) == 0)
merge_hints_into_solutions(st)
check('retour arrière : solutions identiques à l’origine', st == original)

# ---------------------------------------------------------------- import d'une fiche
fiche = {'cle': 'tst-ind', 'type': 'exercice', 'blocs': [
    {'type': 'question', 'html': '<p>Calculer.</p>', 'solution': SOL},
    {'type': 'question', 'html': '<p>Encore.</p>', 'indice': '<p>Pense à $x^2$.</p>', 'solution': '<p>Réponse.</p>'},
]}
s = importing.to_structure(fiche)
check('import : la méthode devient l’indication', s['blocks'][0].get('hint', {}).get('html', '').startswith('<p>Forme'))
check('import : la solution commence par le raisonnement', s['blocks'][0]['solution']['html'].startswith('<p>Pour'))
check('import : le champ « indice » d’une fiche est l’indication affichée',
      s['blocks'][1].get('hint', {}).get('html') == '<p>Pense à $x^2$.</p>' and 'hint' not in s['blocks'][1].get('meta', {}))
check('contrôle des formules : l’indication est vérifiée aussi',
      any('Pense' in h for _, h in importing.all_html(s)))

# ---------------------------------------------------------------- migration des contenus publiés
editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
subject = Subject.objects.get_or_create(name='Mathématiques')[0]
c = Content.objects.create(type='exercise', title='Avec méthode', author=editorial, subject=subject,
                           json_content=copy.deepcopy(original))
mig = importlib.import_module('apps.things.migrations.0013_indications')
mig.forwards(django_apps, None)
c.refresh_from_db()
check('migration : contenu publié converti', c.json_content['blocks'][0].get('hint', {}).get('html', '').startswith('<p>Forme'))
mig.backwards(django_apps, None)
c.refresh_from_db()
check('migration inverse : « Méthode : » remise en tête', c.json_content == original)
mig.forwards(django_apps, None)

# ---------------------------------------------------------------- l'API
cl = APIClient()
r = cl.get(f'/api/contents/{c.pk}/')
blocks = (r.data.get('structure') or r.data.get('json_content') or {}).get('blocks', [])
check('page du contenu : indication et solution envoyées', r.status_code == 200 and blocks and blocks[0].get('hint')
      and blocks[0].get('solution'), r.status_code)
r = cl.get('/api/contents/', {'type': 'exercise', 'view': 'card'})
rows = r.data.get('results', r.data) if isinstance(r.data, dict) else r.data
card = next((x for x in rows if x.get('id') == c.pk), {})
check('mode cartes : ni solution ni indication', 'hint' not in str(card.get('json_content')) and 'solution' not in str(card.get('json_content')),
      str(card.get('json_content'))[:200])

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
