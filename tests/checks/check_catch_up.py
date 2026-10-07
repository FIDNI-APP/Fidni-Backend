"""Bandeau « Tu as ouvert N exercices sans dire si tu les as réussis » (apps/things/catch_up.py)."""
import os
import runpy
import sys
import tempfile
from datetime import date, timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-catch-up.sqlite3')
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
from apps.interactions.models import Complete, QuestionProgress, SolutionView, StudyTimeDay  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users.models import ViewHistory  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


author = User.objects.create_user('Fidni', 'f@x.fr', None)
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
ct = ContentType.objects.get_for_model(Content)
JS = {'version': '2.1', 'blocks': [
    {'id': 'q1', 'type': 'question', 'content': {'html': '<p>a</p>'}},
    {'id': 'q2', 'type': 'question', 'content': {'html': '<p>b</p>'},
     'subQuestions': [{'id': 's1', 'content': {'html': '<p>c</p>'}}, {'id': 's2', 'content': {'html': '<p>d</p>'}}]},
]}


def make(title, kind='exercise', by=author):
    return Content.objects.create(type=kind, title=title, author=by, json_content=JS, difficulty='medium')


def opened(c, days=1, seconds=0):
    ViewHistory.objects.create(user=eleve, content_type=ct, object_id=c.id)
    ViewHistory.objects.filter(user=eleve, object_id=c.id).update(viewed_at=timezone.now() - timedelta(days=days))
    if seconds:
        StudyTimeDay.objects.create(user=eleve, object_id=c.id, date=date.today(), seconds=seconds)


travaille = make('Travaillé 5 min')
opened(travaille, days=2, seconds=300)
solution = make('Solution regardée')
opened(solution, days=1)
SolutionView.objects.create(user=eleve, content_type=ct, object_id=solution.id)
entame = make('Une question évaluée')
opened(entame, days=3)
QuestionProgress.objects.create(user=eleve, content_type=ct, object_id=entame.id, question_path='q1', status='success')
coup_oeil = make('Juste ouvert')
opened(coup_oeil, days=1, seconds=20)
reussi = make('Déjà réussi')
opened(reussi, days=1, seconds=600)
Complete.objects.create(user=eleve, content_type=ct, object_id=str(reussi.id), status='success')
vieux = make('Ouvert il y a 2 mois')
opened(vieux, days=60, seconds=600)
examen = make('Examen travaillé', kind='exam')
opened(examen, days=1, seconds=900)
mien = make('Mon propre exercice', by=eleve)
opened(mien, days=1, seconds=900)

c = APIClient()
r = c.get('/api/contents/a-evaluer/?type=exercise')
check('visiteur : refusé', r.status_code in (401, 403), r.status_code)
c.force_authenticate(eleve)
r = c.get('/api/contents/a-evaluer/?type=exercise')
titles = [x['title'] for x in r.data['items']]
check('réponse', r.status_code == 200, r.status_code)
check('travaillés (temps, solution, question évaluée), du plus récent au plus ancien',
      titles == ['Solution regardée', 'Travaillé 5 min', 'Une question évaluée'], titles)
check('compte total', r.data['count'] == 3, r.data['count'])
check('écartés : juste ouvert, déjà décidé, trop ancien, examen, le sien',
      not {'Juste ouvert', 'Déjà réussi', 'Ouvert il y a 2 mois', 'Examen travaillé', 'Mon propre exercice'} & set(titles), titles)
item = r.data['items'][0]
check('chemins des questions (comme sur la page du contenu)', item['paths'] == ['q1', 'q2.s1', 'q2.s2'], item['paths'])
check('questions déjà évaluées', r.data['items'][2]['assessed'] == 1, r.data['items'][2])
r = c.get(f'/api/contents/a-evaluer/?type=exercise&exclude={solution.id},abc')
check('bandeau fermé : ces contenus ne sont plus redemandés',
      [x['title'] for x in r.data['items']] == ['Travaillé 5 min', 'Une question évaluée'] and r.data['count'] == 2, r.data)
r = c.get('/api/contents/a-evaluer/?type=exam')
check('examens à part', [x['title'] for x in r.data['items']] == ['Examen travaillé'], r.data)

# « Réussi » depuis le bandeau : toutes les questions + le contenu, comme « Tout réussi ».
r = c.post(f'/api/contents/{travaille.id}/assess_many/',
           {'assessments': {p: 'success' for p in item['paths']}, 'completion': 'success'}, format='json')
c.post(f'/api/contents/{entame.id}/mark_progress/', {'status': 'review'}, format='json')
titles = [x['title'] for x in c.get('/api/contents/a-evaluer/?type=exercise').data['items']]
check('une fois évalués, ils sortent du bandeau', titles == ['Solution regardée'], titles)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
