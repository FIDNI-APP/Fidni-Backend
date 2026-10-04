"""Statistiques de l'élève (/api/stats/me/) : notes d'examen, réussite, difficultés, temps par période, filtres."""
import os
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-stats.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
import runpy  # noqa: E402
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []



def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


from apps.interactions.models import StudyTimeDay  # noqa: E402

now = timezone.now()
today = timezone.localdate()
sm = ClassLevel.objects.get(name='2ème Bac SM')
tc = ClassLevel.objects.get(name='Tronc commun Sciences')
maths = Subject.objects.get(name='Mathématiques')
ct = ContentType.objects.get_for_model(Content)
editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
alice = User.objects.create_user('alice', 'alice@x.fr', 'Motdepasse-solide-42')
bob = User.objects.create_user('bob', 'bob@x.fr', 'Motdepasse-solide-42')


def q(i, pts, skills):
    return {'id': f'q{i}', 'type': 'question', 'points': pts, 'meta': {'skills': skills},
            'content': {'html': '<p>?</p>'}, 'subQuestions': []}


def exam(title, level, blocks):
    c = Content.objects.create(type='exam', title=title, author=editorial, subject=maths,
                               json_content={'version': '2.1', 'blocks': blocks})
    c.class_levels.add(level)
    return c


def assess(c, path, status, days_ago):
    row = QuestionProgress.objects.create(user=alice, content_type=ct, object_id=c.id, question_path=path, status=status)
    QuestionProgress.objects.filter(pk=row.pk).update(assessed_at=now - timedelta(days=days_ago))


# Examen A (il y a 3 jours) : 10 pts, réussi 6 + partiel 4 → 8/10 → 16/20
A = exam('DS A', sm, [q(1, 6, ['limites']), q(2, 4, ['limites'])])
assess(A, 'q1', 'success', 3)
assess(A, 'q2', 'partial', 3)
# Examen B (il y a 10 jours) : 20 pts, réussi 5, échoué 15 → 5/20 → 5/20
B = exam('DS B', sm, [q(1, 5, ['continuite']), q(2, 15, ['continuite'])])
assess(B, 'q1', 'success', 10)
assess(B, 'q2', 'failed', 10)
# Examen C (il y a 40 jours, période précédente) : 10/10 → 20/20
C = exam('DS C', sm, [q(1, 10, ['continuite'])])
assess(C, 'q1', 'success', 40)
# Examen D : moins de la moitié du barème corrigé → ne compte pas
D = exam('DS D', sm, [q(1, 2, ['limites']), q(2, 18, ['limites'])])
assess(D, 'q1', 'success', 2)
# Examen de Tronc commun (filtre de niveau) : 4/4 → 20/20, il y a 1 jour
T = exam('DS TC', tc, [q(1, 4, ['identites-remarquables'])])
assess(T, 'q1', 'success', 1)
# Temps : 30 min aujourd'hui sur A, 20 min il y a 40 jours sur C
StudyTimeDay.objects.create(user=alice, object_id=A.id, date=today, seconds=1800)
StudyTimeDay.objects.create(user=alice, object_id=C.id, date=today - timedelta(days=40), seconds=1200)

c = APIClient()
check('anonyme refusé', c.get('/api/stats/me/').status_code in (401, 403))
c.force_authenticate(alice)
r = c.get('/api/stats/me/?period=30')
d = r.data
res = d['results']
check('30 j : 3 examens (A, B, TC ; D exclu, C hors période)', res['count'] == 3, res)
check('30 j : moyenne (16 + 5 + 20) / 3 = 13,7 ; meilleure 20 ; plus basse 5',
      res['average'] == 13.7 and res['best'] == 20 and res['worst'] == 5, res)
check('période précédente : C seul, 20/20', res['previous']['count'] == 1 and res['previous']['average'] == 20, res['previous'])
check('liste des examens, du plus récent', [e['title'] for e in res['exams']] == ['DS TC', 'DS A', 'DS B'], res['exams'])
check('réussite aux questions (30 j) : 4 réussies sur 6', d['questions']['count'] == 6 and d['questions']['success_rate'] == 67, d['questions'])
check('temps (30 j) : 1800 s ; période précédente : 1200 s', d['time']['seconds'] == 1800 and d['time']['previous_seconds'] == 1200, d['time'])
check('temps par chapitre vide sans chapitre', d['time']['by_theme']['chapter'] == [], d['time']['by_theme'])
check('courbe hebdomadaire sur 30 j', d['period']['granularity'] == 'week' and 4 <= len(d['series']) <= 6, d['series'])
check('difficultés : continuité (1 réussie sur 2 → moins de 3 questions, exclue)', all(x['slug'] != 'continuite' for x in d['difficulties']), d['difficulties'])
lim = next((x for x in d['difficulties'] if x['slug'] == 'limites'), None)
check('difficultés : limites (3 questions, 2 réussies → 67 %)', lim and lim['questions'] == 3 and lim['success_rate'] == 67, d['difficulties'])
check('filtres : niveaux travaillés', {x['name'] for x in d['filters']['levels']} == {'2ème Bac SM', 'Tronc commun Sciences'}, d['filters'])
r = c.get(f'/api/stats/me/?period=30&level={sm.id}')
check('filtre niveau 2ème Bac SM : 2 examens, moyenne 10,5', r.data['results']['count'] == 2 and r.data['results']['average'] == 10.5, r.data['results'])
r = c.get('/api/stats/me/?period=all')
check('tout : 4 examens, pas de comparaison', r.data['results']['count'] == 4 and r.data['results']['previous'] is None, r.data['results'])
r = c.get('/api/stats/me/?period=7')
check('7 j : A et TC, courbe par jour', r.data['results']['count'] == 2 and r.data['period']['granularity'] == 'day' and len(r.data['series']) == 7, r.data['period'])
c.force_authenticate(bob)
r = c.get('/api/stats/me/')
check('bob : aucune donnée d’alice', r.data['results']['count'] == 0 and r.data['time']['seconds'] == 0)

# Le suivi du temps alimente le journal jour par jour.
c.force_authenticate(alice)
c.post('/api/study-time/track/', {'content_type': 'exam', 'content_id': A.id, 'time_spent_seconds': 60}, format='json')
check('suivi du temps : +60 s dans le journal du jour', StudyTimeDay.objects.get(user=alice, object_id=A.id, date=today).seconds == 1860)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
