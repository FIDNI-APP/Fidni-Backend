"""Réussite de la classe question par question (15/10/2026 : affichée à côté de chaque question, à la place de
l'onglet « Activité ») : comptes par statut, vrais élèves seulement, à jour après une auto-évaluation."""
import os
import sys
import tempfile


BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-question-stats.sqlite3')
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
from apps.interactions.models import QuestionProgress  # noqa: E402
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
admin = User.objects.create_superuser('patron', 'patron@x.fr', 'Motdepasse-solide-42')
eleves = [User.objects.create_user(f'eleve{i}', f'e{i}@x.fr', 'Motdepasse-solide-42') for i in range(4)]
ex = Content.objects.create(type='exercise', title='Deux questions', author=editorial, subject=subject,
                            json_content={'version': '2.1', 'blocks': [
                                {'id': 'q1', 'type': 'question', 'content': {'html': '<p>Q1</p>'}},
                                {'id': 'q2', 'type': 'question', 'content': {'html': '<p>Q2</p>'}}]})
ex.class_levels.add(level)
ex.chapters.add(chapter)


def evalue(u, path, st):
    QuestionProgress.objects.update_or_create(user=u, content_type=ct, object_id=ex.id, question_path=path,
                                              defaults={'status': st})


evalue(eleves[0], 'q1', 'success')
evalue(eleves[1], 'q1', 'success')
evalue(eleves[2], 'q1', 'failed')
evalue(eleves[3], 'q1', 'partial')
evalue(eleves[0], 'q2', 'review')
evalue(admin, 'q1', 'review')  # compte maison : pas compté

anonyme = APIClient()
r = anonyme.get(f'/api/contents/{ex.id}/question_stats/')
check('visiteur : statistiques lisibles', r.status_code == 200, r.status_code)
q1 = (r.data.get('questions') or {}).get('q1', {}) if r.status_code == 200 else {}
check('q1 : 2 réussi, 1 en partie, 1 à revoir (« failed » compté à revoir)',
      q1 == {'total': 4, 'success': 2, 'partial': 1, 'review': 1}, q1)
check('compte maison (administrateur) exclu, élèves comptés une fois', r.data.get('eleves') == 4, r.data)
check('q2 : une évaluation', r.data['questions'].get('q2') == {'total': 1, 'success': 0, 'partial': 0, 'review': 1})

el = APIClient()
el.force_authenticate(eleves[3])
r = el.post(f'/api/contents/{ex.id}/assess_many/', {'assessments': {'q1': 'success', 'q2': 'success'},
                                                    'source': 'question'}, format='json')
check('auto-évaluation enregistrée', r.status_code == 200, r.status_code)
r = anonyme.get(f'/api/contents/{ex.id}/question_stats/')
check('à jour juste après (cache effacé)', r.data['questions']['q1']['success'] == 3
      and r.data['questions']['q1']['partial'] == 0 and r.data['questions']['q2']['total'] == 2, r.data)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
