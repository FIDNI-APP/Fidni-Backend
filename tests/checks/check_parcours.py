"""Régressions du Parcours sur une base SQLite temporaire."""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BACKEND / 'src'), str(BACKEND)]
temp = tempfile.TemporaryDirectory(prefix='fidni-parcours-')
os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_ENV='development',
                  DB_ENGINE='sqlite', SQLITE_PATH=str(Path(temp.name) / 'test.sqlite3'),
                  AWS_STORAGE_ENABLED='false')
import django
django.setup()
from django.core.management import call_command
from django.conf import settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.caracteristics.models import Subject, Chapter
from apps.learningpath.models import (
    LearningPath, PathChapter, Video, ChapterQuiz, QuizQuestion,
    UserChapterProgress, UserVideoProgress,
)

call_command('migrate', verbosity=0)
settings.ALLOWED_HOSTS = ['testserver']
settings.PARCOURS_PUBLIC = False
client = APIClient()
staff = User.objects.create_user('prof', is_staff=True)
client.force_authenticate(staff)
subject = Subject.objects.create(name='Mathématiques test')
chapter = Chapter.objects.create(name='Limites test', subject=subject)
path = LearningPath.objects.create(subject=subject, title='Parcours test', estimated_hours=1)
part = PathChapter.objects.create(learning_path=path, chapter=chapter, title='Limites', order=1)
video = Video.objects.create(path_chapter=part, title='Cours', url='https://example.invalid/film.mp4',
                             duration_seconds=100, order=1)
quiz = ChapterQuiz.objects.create(path_chapter=part, title='Validation', passing_score=70)
question = QuizQuestion.objects.create(quiz=quiz, question_text='1+1 ?', question_type='multiple_choice',
                                       options=['2', '3'], correct_answer_index=0, points=1, order=1)
base = '/api'
response = client.get(f'{base}/learning-paths/{path.id}/')
assert response.status_code == 200, response.data
assert response.data['path_chapters'][0]['quiz']['is_required'] is True
response = client.post(f'{base}/path-chapters/{part.id}/start_chapter/')
assert response.status_code in (200, 201), response.data
cp = UserChapterProgress.objects.get(user=staff, path_chapter=part)
assert cp.progress_percentage == 0
response = client.post(f'{base}/videos/{video.id}/update_progress/', {'watched_seconds': 12}, format='json')
assert response.status_code == 200 and not response.data['is_completed'], response.data
response = client.post(f'{base}/videos/{video.id}/update_progress/', {'watched_seconds': 90}, format='json')
assert response.status_code == 200 and response.data['is_completed'], response.data
cp.refresh_from_db()
assert not cp.is_completed and cp.progress_percentage == 80
response = client.post(f'{base}/chapter-quizzes/{quiz.id}/start_attempt/')
assert response.status_code == 200, response.data
attempt = response.data['attempt_id']
response = client.post(f'{base}/chapter-quizzes/{quiz.id}/submit_attempt/', {
    'attempt_id': attempt, 'answers': [{'question_id': question.id, 'answer_index': 0}],
}, format='json')
assert response.status_code == 200 and response.data['passed'], response.data
assert response.data['results'][0]['correct_answer'] == 0
cp.refresh_from_db()
assert cp.is_completed and cp.progress_percentage == 100
response = client.post(f'{base}/videos/{video.id}/update_progress/', {'watched_seconds': 10, 'notes': 'À revoir'}, format='json')
assert response.status_code == 200
assert UserVideoProgress.objects.get(user=staff, video=video).watched_seconds == 90
response = client.post(f'{base}/path-chapters/{part.id}/complete/')
assert response.status_code == 200, response.data
unknown = Video.objects.create(path_chapter=part, title='Durée inconnue',
                               url='https://example.invalid/unknown.mp4', duration_seconds=0, order=2)
response = client.post(f'{base}/videos/{unknown.id}/update_progress/', {'watched_seconds': 0}, format='json')
assert response.status_code == 200 and not response.data['is_completed'], response.data
student = User.objects.create_user('eleve')
client.force_authenticate(student)
response = client.get(f'{base}/learning-paths/')
assert response.status_code == 404, response.data
response = client.post(f'{base}/learning-paths/', {'title': 'Non', 'subject': subject.id, 'class_level': []}, format='json')
assert response.status_code in (403, 404), response.status_code

# Superutilisateur SANS « staff » (14/11/2026) : le site lui montre Parcours, le serveur doit le laisser lister et créer.
from apps.caracteristics.models import ClassLevel  # noqa: E402
niveau = ClassLevel.objects.create(name='Niveau test', order=99)
admin = User.objects.create_user('natsu_admin', is_superuser=True, is_staff=False)
client.force_authenticate(admin)
response = client.post(f'{base}/learning-paths/', {'title': 'Créé par un admin', 'subject': subject.id,
                                                   'class_level': [niveau.id], 'is_active': True}, format='json')
assert response.status_code == 201, (response.status_code, response.data)
response = client.get(f'{base}/learning-paths/')
titres = [p['title'] for p in (response.data['results'] if isinstance(response.data, dict) else response.data)]
assert response.status_code == 200 and 'Créé par un admin' in titres, (response.status_code, titres)
response = client.patch(f'{base}/videos/{video.id}/', {'title': 'Cours (modifié)'}, format='json')
assert response.status_code == 200, (response.status_code, response.data)

# Parcours de démonstration (python manage.py parcours_demo)
from io import StringIO  # noqa: E402
from apps.caracteristics.models import Subject as _S  # noqa: E402
from apps.learningpath.management.commands import parcours_demo as demo  # noqa: E402
sm2 = ClassLevel.objects.create(name=demo.NIVEAU, order=3)
maths = _S.objects.create(name=demo.MATIERE)
for nom, *_ in demo.CHAPITRES:
    Chapter.objects.create(name=nom, subject=maths).class_levels.add(sm2)
call_command('parcours_demo', '--video-url', 'https://www.youtube.com/watch?v=aaaaaaaaaaa', '--duree', '30',
             '--pour', 'natsu_admin', stdout=StringIO())
lp = LearningPath.objects.get(title=demo.TITRE)
assert lp.path_chapters.count() == 6 and Video.objects.filter(path_chapter__learning_path=lp).count() == 18
for q in QuizQuestion.objects.filter(quiz__path_chapter__learning_path=lp):
    assert 0 <= q.correct_answer_index < len(q.options) and len(set(q.options)) == len(q.options), q.question_text
assert len({q.correct_answer_index for q in QuizQuestion.objects.filter(quiz__path_chapter__learning_path=lp)}) > 1
data = client.get(f'{base}/learning-paths/{lp.id}/').data
ch = sorted(data['path_chapters'], key=lambda c: c['order'])
assert ch[0]['user_progress']['is_completed'] and not ch[1]['user_progress']['is_completed'], ch[:2]
assert [bool(v['user_progress'] and v['user_progress']['is_completed']) for v in ch[1]['videos']] == [True, False, False]
call_command('parcours_demo', stdout=StringIO())  # recréée avec la même vidéo, sans doublon
assert LearningPath.objects.filter(title=demo.TITRE).count() == 1
assert Video.objects.filter(path_chapter__learning_path__title=demo.TITRE).first().url.endswith('aaaaaaaaaaa')
call_command('parcours_demo', '--supprimer', stdout=StringIO())
assert not LearningPath.objects.filter(title=demo.TITRE).exists()
print('OK — sérialisation, lecture, seuil de validation, quiz, chapitre, notes, accès fermé, admin sans staff, démo')
temp.cleanup()
