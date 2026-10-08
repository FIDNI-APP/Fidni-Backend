"""Listes de révision : étiquettes (niveau, matière, chapitres), ajout rapide « À revoir », suggestions."""
import os
import sys
import tempfile


BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-revisions.sqlite3')
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
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject, Chapter  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress, RevisionList  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []



def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
chapter = Chapter.objects.filter(class_levels=level, subject=subject).order_by('id').first()
ct = ContentType.objects.get_for_model(Content)
editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
alice = User.objects.create_user('alice', 'alice@x.fr', 'Motdepasse-solide-42')
bob = User.objects.create_user('bob', 'bob@x.fr', 'Motdepasse-solide-42')


def make(title):
    c = Content.objects.create(type='exercise', title=title, author=editorial, subject=subject,
                               json_content={'version': '2.1', 'blocks': []})
    c.class_levels.add(level)
    c.chapters.add(chapter)
    return c


ex1, ex2, ex3 = make('Raté'), make('Questions faibles'), make('Réussi')
c = APIClient()
c.force_authenticate(alice)

r = c.post('/api/revision-lists/', {'name': 'Limites — DS 1', 'class_level_ids': [level.id],
                                    'subject_ids': [subject.id], 'chapter_ids': [chapter.id]}, format='json')
check('création avec étiquettes', r.status_code == 201, (r.status_code, r.data))
lid = r.data.get('id')
r = c.get(f'/api/revision-lists/{lid}/')
check('étiquettes relues (niveau, matière, chapitre)',
      [x['name'] for x in r.data['class_levels']] == ['2ème Bac SM'] and [x['name'] for x in r.data['subjects']] == ['Mathématiques']
      and [x['id'] for x in r.data['chapters']] == [chapter.id], r.data)
r = c.post('/api/revision-lists/', {'name': 'Sans étiquette'}, format='json')
check('étiquettes facultatives', r.status_code == 201 and r.data['chapters'] == [], r.status_code)
r = c.post('/api/revision-lists/', {'name': 'Limites — DS 1'}, format='json')
check('nom en double : refus clair', r.status_code == 400 and 'name' in r.data, r.status_code)

# Progrès d'alice : ex1 marqué Échoué ; ex2 avec deux questions ratées ; ex3 réussi.
Complete.objects.create(user=alice, content_type=ct, object_id=str(ex1.id), status='review')
QuestionProgress.objects.create(user=alice, content_type=ct, object_id=ex2.id, question_path='q1', status='failed')
QuestionProgress.objects.create(user=alice, content_type=ct, object_id=ex2.id, question_path='q2', status='partial')
Complete.objects.create(user=alice, content_type=ct, object_id=str(ex3.id), status='success')

r = c.get('/api/revision-lists/suggestions/')
ids = [x['id'] for x in r.data['results']]
check('suggestions : exercice raté et exercice aux questions faibles', set(ids) == {ex1.id, ex2.id}, r.data)
row = next(x for x in r.data['results'] if x['id'] == ex2.id)
check('suggestion : nombre de questions faibles et chapitre', row['weak_questions'] == 2 and row['chapters'] == [chapter.name], row)

r = c.post('/api/revision-lists/quick_add/', {'object_id': ex1.id}, format='json')
check('ajout rapide : crée « À revoir »', r.status_code == 201 and r.data['created_list'] and r.data['list_name'] == 'À revoir', r.data)
quick = RevisionList.objects.get(user=alice, name='À revoir')
check('ajout rapide : liste étiquetée d’après l’exercice',
      list(quick.class_levels.values_list('id', flat=True)) == [level.id] and list(quick.chapters.values_list('id', flat=True)) == [chapter.id])
r = c.post('/api/revision-lists/quick_add/', {'object_id': ex1.id}, format='json')
check('ajout rapide idempotent', r.status_code == 200 and not r.data['added'] and quick.items.count() == 1, r.data)
# Page Révisions : résumé léger des listes (plus de cartes complètes) et liste ouverte préchargée.
from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
Complete.objects.update_or_create(user=alice, content_type=ct, object_id=str(ex1.id), defaults={'status': 'review'})
connection.queries_log.clear()
with CaptureQueriesContext(connection) as queries:
    r = c.get('/api/revision-lists/')
rows = {x['name']: x for x in r.data}
check('listes : résumé léger', r.status_code == 200 and rows['À revoir']['item_count'] == 1
      and rows['À revoir']['progress'] == {'success': 0, 'review': 1, 'todo': 0}
      and rows['À revoir']['items'][0]['content_type_name'] == 'exercise' and 'content_object' not in rows['À revoir']['items'][0]
      and rows['À revoir']['item_chapters'] == [chapter.name], rows.get('À revoir'))
check('listes : peu de requêtes', len(queries) <= 12, len(queries))
quick_id = rows['À revoir']['id']
r = c.get(f'/api/revision-lists/{quick_id}/')
item = r.data['items'][0]
check('liste ouverte : carte complète avec l’énoncé', r.status_code == 200 and item['content_object']['id'] == ex1.id
      and 'json_content' in item['content_object'] and item['content_type_name'] == 'exercise', r.data)
r = c.get(f'/api/revision-lists/{quick_id}/statistics/')
check('statistiques de la liste', r.data['total_items'] == 1 and r.data['review'] == 1 and r.data['completed'] == 1, r.data)
r = c.get('/api/revision-lists/suggestions/')
check('suggestion retirée une fois dans une liste', [x['id'] for x in r.data['results']] == [ex2.id], r.data)

c.force_authenticate(bob)
check('bob ne voit pas les listes d’alice', c.get(f'/api/revision-lists/{lid}/').status_code == 404)
check('bob : aucune suggestion', c.get('/api/revision-lists/suggestions/').data['count'] == 0)
c.force_authenticate(None)
check('anonyme refusé', c.get('/api/revision-lists/suggestions/').status_code in (401, 403))

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
