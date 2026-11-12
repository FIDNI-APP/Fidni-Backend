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
print('OK — sérialisation, lecture, seuil de validation, quiz, chapitre, notes et accès fermé')
temp.cleanup()
