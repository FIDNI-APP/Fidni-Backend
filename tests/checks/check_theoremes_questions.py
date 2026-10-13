"""Théorèmes de chaque question (13/10/2026) : commande questions_theoremes (export pour l'étiquetage, puis
application à la place des anciennes notions meta.skills)."""
import io
import json
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-theoremes-questions.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))  # taxonomie réelle (théorèmes du programme)
from django.contrib.auth.models import User  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402
from django.utils import timezone  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.ia.models import IAJob  # noqa: E402
from apps.things.models import Content  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


TVI, BIJ = 'Théorème des valeurs intermédiaires (TVI)', 'Théorème de la bijection'
author = User.objects.create_user('Fidni', 'f@x.fr', None)
sm = ClassLevel.objects.get(name='2ème Bac SM')
lim = Chapter.objects.get(name='Limites et continuité')
il_y_a = timezone.now() - timedelta(days=30)


def make(title, blocks, kind='exercise'):
    c = Content.objects.create(type=kind, title=title, author=author, json_content={'version': '2.1', 'blocks': blocks})
    c.class_levels.set([sm])
    c.chapters.set([lim])
    Content.objects.filter(pk=c.pk).update(updated_at=il_y_a)
    return Content.objects.get(pk=c.pk)


ex = make('Fonction continue', [
    {'id': 'ctx', 'type': 'context', 'content': {'html': '<p>Soit $f(x)=x^3+x-1$.</p>'}},
    {'id': 'q1', 'type': 'question', 'content': {'html': '<p>Montrer que $f$ s&#39;annule sur $[0,1]$.</p>'},
     'solution': {'html': '<p>$f$ est continue et $f(0)f(1)&lt;0$.</p>'}, 'meta': {'skills': ['tvi'], 'difficulty': 'easy'}},
    {'id': 'q2', 'type': 'question', 'content': {'html': '<p>Étudier $f$.</p>'}, 'subQuestions': [
        {'id': 'a', 'content': {'html': '<p>Bijection.</p>'}, 'meta': {'skills': ['bijection']}},
        {'id': 'b', 'content': {'html': '<p>Calculer $f(2)$.</p>'}, 'meta': {'skills': ['calcul']}}]},
])
autre = make('Titre qui va changer', [{'id': 'q1', 'type': 'question', 'content': {'html': '<p>?</p>'},
                                       'meta': {'skills': ['tvi']}}])
lecon = make('Cours', [{'id': 'q1', 'type': 'question', 'meta': {'skills': ['tvi']}}], kind='lesson')
job = IAJob.objects.create(kind=IAJob.IMPORT, status=IAJob.PRET, result={'fiches': [{'blocs': [
    {'type': 'question', 'notions': ['tvi'], 'sous_questions': [{'notions': ['x'], 'html': '?'}]}]}]})
fini = IAJob.objects.create(kind=IAJob.IMPORT, status=IAJob.PUBLIE, result={'fiches': [{'blocs': [{'notions': ['tvi']}]}]})

# ── Export (lecture seule)
work = tempfile.mkdtemp()
out = os.path.join(work, 'questions.json')
call_command('questions_theoremes', exporter=out, stdout=io.StringIO())
data = json.load(open(out, encoding='utf-8'))
by_id = {c['id']: c for c in data['contenus']}
e = by_id.get(ex.id)
check('export : exercices et examens seulement', set(by_id) == {ex.id, autre.id}, sorted(by_id))
check('export : chaque question avec son chemin, son libellé, ses anciennes notions',
      [(q['chemin'], q['label'], q['notions']) for q in e['questions']]
      == [('q1', 'Q1', ['tvi']), ('q2.a', 'Q2a', ['bijection']), ('q2.b', 'Q2b', ['calcul'])], e['questions'])
check('export : énoncé et solution en texte (balises ôtées, entités décodées), contexte',
      e['questions'][0]['enonce'] == "Montrer que $f$ s'annule sur $[0,1]$."
      and e['questions'][0]['solution'] == '$f$ est continue et $f(0)f(1)<0$.'
      and e['questions'][0]['contexte'] == 'Soit $f(x)=x^3+x-1$.'
      and 'Étudier $f$.' in e['questions'][1]['contexte'], e['questions'][:2])
check('export : candidats = théorèmes du niveau, ceux du chapitre du contenu d’abord',
      TVI in e['theoremes_candidats'][:12] and BIJ in e['theoremes_candidats'][:12]
      and 'Formule de Moivre' in e['theoremes_candidats'], e['theoremes_candidats'][:12])
check('export : rien d’écrit', Content.objects.get(pk=ex.pk).json_content == ex.json_content)

# ── Application
mapping = {'contenus': {
    str(ex.id): {'titre': 'Fonction continue', 'questions': {
        'q1': ['théorème des valeurs intermédiaires (tvi)'], 'q2.a': [BIJ, 'Théorème inventé'], 'q2.b': [], 'q9': [TVI]}},
    str(autre.id): {'titre': 'Ancien titre', 'questions': {'q1': [TVI]}},
    '999999': {'titre': 'Disparu', 'questions': {}},
}}
fichier = os.path.join(work, 'theoremes.json')
json.dump(mapping, open(fichier, 'w', encoding='utf-8'), ensure_ascii=False)

buf = io.StringIO()
call_command('questions_theoremes', appliquer=fichier, a_blanc=True, stdout=buf)
check('à blanc : rapport, rien de gardé', 'Répétition à blanc' in buf.getvalue()
      and Content.objects.get(pk=ex.pk).json_content == ex.json_content
      and IAJob.objects.get(pk=job.pk).result == job.result, buf.getvalue())

buf = io.StringIO()
call_command('questions_theoremes', appliquer=fichier, stdout=buf)
rapport = buf.getvalue()
ex2 = Content.objects.get(pk=ex.pk)
b = ex2.json_content['blocks']
check('question : nom exact posé (casse ignorée), notions retirées, le reste du meta gardé',
      b[1]['meta'] == {'theorems': [TVI], 'difficulty': 'easy'}, b[1]['meta'])
check('sous-question : théorème connu gardé, inconnu signalé', b[2]['subQuestions'][0]['meta'] == {'theorems': [BIJ]}
      and 'théorème inconnu « Théorème inventé »' in rapport, (b[2]['subQuestions'][0], rapport))
check('question de calcul : aucun théorème, plus de meta vide', 'meta' not in b[2]['subQuestions'][1], b[2]['subQuestions'][1])
check('théorèmes ajoutés au contenu (filtre « Théorème »)', set(ex2.theorems.values_list('name', flat=True)) == {TVI, BIJ},
      list(ex2.theorems.values_list('name', flat=True)))
check('date de modification avancée (index des questions relu)', ex2.updated_at > il_y_a + timedelta(days=29))
autre2 = Content.objects.get(pk=autre.pk)
check('titre changé : étiquetage sauté (signalé), anciennes notions retirées quand même',
      'titre changé' in rapport and 'theorems' not in (autre2.json_content['blocks'][0].get('meta') or {})
      and 'skills' not in (autre2.json_content['blocks'][0].get('meta') or {}) and not autre2.theorems.exists(), rapport)
check('chemin et contenu introuvables : signalés', f'#{ex.id} q9' in rapport and '999999' in rapport, rapport)
check('leçon : pas touchée', Content.objects.get(pk=lecon.pk).json_content == lecon.json_content)
r = IAJob.objects.get(pk=job.pk).result['fiches'][0]['blocs'][0]
check('travail IA en attente : champ « notions » retiré des fiches', 'notions' not in r
      and 'notions' not in r['sous_questions'][0] and r['sous_questions'][0]['html'] == '?', r)
check('travail IA déjà publié : pas touché', IAJob.objects.get(pk=fini.pk).result == fini.result)
check('plus aucune notion dans les contenus', not any('skills' in json.dumps(c.json_content)
                                                      for c in Content.objects.filter(type__in=('exercise', 'exam'))))

buf = io.StringIO()
call_command('questions_theoremes', appliquer=fichier, stdout=buf)
check('relancer : même résultat', Content.objects.get(pk=ex.pk).json_content == ex2.json_content, buf.getvalue())
try:
    call_command('questions_theoremes', stdout=io.StringIO())
    ok = False
except CommandError:
    ok = True
check('sans option : erreur', ok)

# ── Enregistré depuis l'éditeur (API) : les théorèmes des questions s'ajoutent à ceux du contenu
from rest_framework.test import APIClient  # noqa: E402
from django.conf import settings  # noqa: E402
from apps.caracteristics.models import Subject  # noqa: E402
settings.ALLOWED_HOSTS = ['*']
admin = User.objects.create_superuser('chef', 'c@x.fr', 'x')
api = APIClient()
api.force_authenticate(admin)
body = {'type': 'exercise', 'title': 'Depuis l’éditeur', 'difficulty': 'easy', 'subject': Subject.objects.get(name='Mathématiques').pk,
        'class_levels': [sm.pk], 'chapters': [lim.pk],
        'json_content': {'version': '2.1', 'blocks': [{'id': 'q1', 'type': 'question', 'content': {'html': '<p>?</p>'},
                                                       'meta': {'theorems': [TVI]}}]}}
r = api.post('/api/contents/', body, format='json')
cree = Content.objects.get(pk=r.data['id']) if r.status_code == 201 else None
check('création : théorème de la question ajouté au contenu', cree and list(cree.theorems.values_list('name', flat=True)) == [TVI],
      (r.status_code, getattr(r, 'data', None)))
body['json_content']['blocks'][0]['meta']['theorems'] = [BIJ]
r = api.patch(f'/api/contents/{cree.id}/', {'json_content': body['json_content'], 'theorems': []}, format='json')
check('modification : théorèmes du contenu = ceux envoyés + ceux des questions', r.status_code == 200
      and set(cree.theorems.values_list('name', flat=True)) == {BIJ}, (r.status_code, list(cree.theorems.values_list('name', flat=True))))

# ── Objectif de « Ma progression » : à difficulté égale, les exercices des théorèmes les moins réussis d'abord
# (sans jamais les nommer à l'élève).
from apps.interactions.devoirs import _for_you  # noqa: E402
eleve = User.objects.create_user('eleve', 'e@x.fr', 'x')
faciles = []
for i in range(3):
    x = make(f'Facile {i}', [{'id': 'q1', 'type': 'question', 'content': {'html': '<p>?</p>'}}])
    Content.objects.filter(pk=x.pk).update(difficulty='easy')
    faciles.append(x.id)
moyen = make('Moyen', [{'id': 'q1', 'type': 'question', 'content': {'html': '<p>?</p>'}}])
Content.objects.filter(pk=moyen.pk).update(difficulty='medium')
rows = _for_you(eleve, [lim.id], {lim.id: lim.name}, ['easy', 'medium'], limit=10, soon_ids={faciles[2], moyen.id})
ordre = [r['id'] for r in rows]
check('à difficulté égale : exercice du théorème faible d’abord ; la difficulté reste prioritaire',
      ordre.index(faciles[2]) == min(ordre.index(f) for f in faciles) and ordre.index(moyen.id) > max(ordre.index(f) for f in faciles),
      ordre)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
