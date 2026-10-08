"""Ma progression (apps/users/progression.py) : carte du programme, points forts / à renforcer, Skill IQ,
évolution depuis le début, temps d'étude."""
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-progression.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress, StudyTimeDay  # noqa: E402
from apps.skilliq.models import SkillAssessment, SkillQuestion  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


author = User.objects.create_user('Fidni', 'f@x.fr', None)
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
sm = ClassLevel.objects.get(name='2ème Bac SM')
eleve.profile.class_level = sm
eleve.profile.daily_goal_minutes = 20
eleve.profile.save()
lim = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
der = Chapter.objects.filter(name__startswith='Dérivation', class_levels=sm).first()
autre, vierge = list(Chapter.objects.filter(class_levels=sm).exclude(id__in=[lim.id, der.id])[:2])
ct = ContentType.objects.get_for_model(Content)


def q(qid, skills, points=None):
    b = {'id': qid, 'type': 'question', 'content': {'html': '<p>?</p>'}, 'meta': {'skills': skills}}
    if points is not None:
        b['points'] = points
    return b


def make(title, chapters, blocks, kind='exercise'):
    c = Content.objects.create(type=kind, title=title, author=author, json_content={'version': '2.1', 'blocks': blocks})
    c.class_levels.set([sm])
    c.chapters.set(chapters)
    return c


def assess(c, statuses, days=0):
    for path, st in statuses.items():
        QuestionProgress.objects.create(user=eleve, content_type=ct, object_id=c.id, question_path=path, status=st)
    QuestionProgress.objects.filter(user=eleve, object_id=c.id).update(
        assessed_at=timezone.now() - timedelta(days=days), created_at=timezone.now() - timedelta(days=days))


ex_lim = make('Limites 1', [lim], [q('q1', ['tvi']), q('q2', ['tvi']), q('q3', ['tvi']), q('q4', ['limites-usuelles'])])
ex_der = make('Dérivation 1', [der], [q('q1', ['derivee']), q('q2', ['derivee']), q('q3', ['derivee'])])
make('Dérivation 2 (pas encore fait)', [der], [q('q1', [])])
exam = make('Examen blanc', [lim, der], [q('q1', ['tvi'], 10), q('q2', ['derivee'], 10)], kind='exam')
assess(ex_lim, {'q1': 'success', 'q2': 'success', 'q3': 'success', 'q4': 'success'}, days=40)
assess(ex_der, {'q1': 'success', 'q2': 'review', 'q3': 'partial'}, days=1)
assess(exam, {'q1': 'success', 'q2': 'review'}, days=2)
Complete.objects.create(user=eleve, content_type=ct, object_id=str(ex_lim.id), status='success')
Complete.objects.create(user=eleve, content_type=ct, object_id=str(ex_der.id), status='review')
SkillAssessment.objects.create(user=eleve, chapter=lim, score=8, max_score=10)
SkillAssessment.objects.create(user=eleve, chapter=autre, score=3, max_score=10)
SkillQuestion.objects.create(chapter=vierge, question='?', options=['a', 'b'], correct_answer=0)
today = timezone.localdate()
StudyTimeDay.objects.create(user=eleve, object_id=ex_lim.id, date=today, seconds=1500)
StudyTimeDay.objects.create(user=eleve, object_id=ex_der.id, date=today - timedelta(days=1), seconds=600)
StudyTimeDay.objects.create(user=eleve, object_id=ex_lim.id, date=today - timedelta(days=40), seconds=900)

c = APIClient()
check('visiteur : refusé', c.get('/api/stats/progression/').status_code in (401, 403))
c.force_authenticate(eleve)
r = c.get('/api/stats/progression/')
check('réponse', r.status_code == 200, r.status_code)
d = r.data
chapters = {x['id']: x for x in d['chapters']}
check('le programme du niveau, tous les chapitres', d['level']['name'] == '2ème Bac SM'
      and len(chapters) == Chapter.objects.filter(class_levels=sm).distinct().count(), len(chapters))

L, D, A, V = chapters[lim.id], chapters[der.id], chapters[autre.id], chapters[vierge.id]
# Limites : 4 + 1 (examen) questions réussies sur 5 = 100 %, quiz 80 % → 0,6 × 100 + 0,4 × 80 = 92.
check('chapitre maîtrisé : auto-évaluation + Skill IQ', L['status'] == 'mastered' and L['self_pct'] == 100
      and L['mastery'] == 92 and L['skilliq']['pct'] == 80, (L['status'], L['self_pct'], L['mastery']))
# Dérivation : réussi 1 + en partie ½ + 0 (exercice) + 0 (examen) sur 4 = 38 %.
check('chapitre à renforcer', D['status'] == 'weak' and D['mastery'] == 38 and D['questions'] == 4, (D['status'], D['mastery']))
check('détail : contenus réussis / à revoir', L['done'] == 1 and L['contents'] == 2 and D['contents'] == 3
      and [x['title'] for x in D['review']] == ['Dérivation 1'], (L['done'], L['contents'], D['contents'], D['review']))
check('détail : notions les mieux et les moins réussies', L['notions']['best'][0]['label'] and D['notions']['worst']
      and D['notions']['worst'][0]['pct'] < 60, (L['notions'], D['notions']))
check('Skill IQ seul : compte aussi', A['status'] == 'weak' and A['mastery'] == 30 and A['self_pct'] is None, A)
check('pas commencé, quiz disponible', V['status'] == 'todo' and V['quiz_ready'] and V['mastery'] is None, V)
s = d['summary']['chapters']
check('résumé des états', s['mastered'] == 1 and s['weak'] == 2 and s['todo'] == s['total'] - 3, s)

check('points forts : la notion la mieux réussie', d['strengths'] and d['strengths'][0]['pct'] == 100
      and d['strengths'][0]['chapter_id'] == lim.id, d['strengths'])
weak = {x['label']: x for x in d['weaknesses']}
check('à renforcer : notion ratée et chapitre du Skill IQ', any(x['source'] == 'notion' for x in d['weaknesses'])
      and autre.name in weak and weak[autre.name]['source'] == 'skilliq'
      and weak[autre.name]['url'] == f'/exercises?chapters={autre.id}', d['weaknesses'])

pts = d['evolution']['points']
check('évolution : cumuls qui ne baissent jamais, jusqu\'au total', pts and all(
    a['questions_ok'] <= b['questions_ok'] and a['exercises'] <= b['exercises'] for a, b in zip(pts, pts[1:]))
      and pts[-1]['questions_ok'] == d['summary']['questions_ok'] == 6 and pts[-1]['exercises'] == 1, pts[-1:])
check('évolution : depuis le premier jour', d['since'] == (today - timedelta(days=40)).isoformat(), d['since'])
check('examens : note sur 20', d['exams']['count'] == 1 and d['exams']['list'][0]['note'] == 10.0, d['exams'])

t = d['time']
check('temps : total, 7 jours, aujourd\'hui, objectif', t['total_seconds'] == 3000 and t['week'] == 2100
      and t['today'] == 1500 and t['goal_minutes'] == 20, (t['total_seconds'], t['week'], t['today']))
check('temps : 28 jours, du plus ancien à aujourd\'hui', len(t['days']) == 28 and t['days'][-1]['date'] == today.isoformat()
      and t['days'][-1]['seconds'] == 1500, t['days'][-1])
check('temps : par mois depuis le début', sum(m['seconds'] for m in t['months']) == 3000, t['months'])
check('temps : par chapitre, le plus long d\'abord', [x['id'] for x in t['by_chapter']][:2] == [lim.id, der.id], t['by_chapter'])
check('série en cours', d['summary']['streak']['current'] >= 2, d['summary']['streak'])

# Objectif quotidien réglable depuis la page.
r = c.patch('/api/settings/', {'daily_goal_minutes': 45}, format='json')
check('objectif quotidien modifiable', r.status_code == 200 and c.get('/api/stats/progression/').data['time']['goal_minutes'] == 45,
      r.status_code)
check('objectif quotidien : valeur absurde refusée', c.patch('/api/settings/', {'daily_goal_minutes': 900}, format='json').status_code == 400)

# Index des questions en cache (things/question_index.py) : relu sans recharger l'énoncé, refait
# dès que le contenu change.
from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from apps.things.question_index import question_index  # noqa: E402
light = list(Content.objects.filter(id=ex_der.id).only('id', 'updated_at'))
first = question_index(light)
connection.queries_log.clear()
with CaptureQueriesContext(connection) as queries:
    again = question_index(light)
check('index des questions : relu du cache, sans requête', again == first and len(queries) == 0, len(queries))
ex_der.json_content = {'version': '2.1', 'blocks': [q('q1', ['ipp']), q('q2', ['ipp'])]}
ex_der.save()
check('index des questions : contenu modifié → index refait',
      question_index(list(Content.objects.filter(id=ex_der.id).only('id', 'updated_at')))[ex_der.id] == [('q1', 0.0, ['ipp']), ('q2', 0.0, ['ipp'])])

# Élève sans niveau ni activité : page vide mais valide.
nouveau = User.objects.create_user('nouveau', 'n@x.fr', 'Motdepasse-solide-42')
c.force_authenticate(nouveau)
r = c.get('/api/stats/progression/')
check('nouvel élève : rien à montrer, pas d\'erreur', r.status_code == 200 and r.data['since'] is None
      and r.data['evolution']['points'] == [] and r.data['time']['total_seconds'] == 0, r.status_code)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
