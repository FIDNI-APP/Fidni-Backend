"""Envoi vidéo admin, reprise, finalisation et accès aux fichiers privés."""
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
temp = tempfile.TemporaryDirectory(prefix='fidni-parcours-upload-')
os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_ENV='development',
                  DB_ENGINE='sqlite', SQLITE_PATH=str(Path(temp.name) / 'db.sqlite3'),
                  AWS_STORAGE_ENABLED='false')
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from apps.caracteristics.models import Subject, Chapter, ClassLevel
from apps.learningpath.models import LearningPath, PathChapter, Video
from apps.uploads.models import FileAttachment

settings.MEDIA_ROOT = str(Path(temp.name) / 'media')
settings.ALLOWED_HOSTS = ['testserver.example']
settings.DEBUG = True
settings.PARCOURS_PUBLIC = False
call_command('migrate', verbosity=0)
staff = User.objects.create_user('admin_video', is_staff=True)
other = User.objects.create_user('autre_admin', is_staff=True)
student = User.objects.create_user('eleve_video')
client = APIClient(HTTP_HOST='testserver.example')
client.force_authenticate(staff)
subject = Subject.objects.create(name='Maths vidéo')
taxonomy = Chapter.objects.create(name='Limites vidéo', subject=subject)
path = LearningPath.objects.create(subject=subject, title='Parcours vidéo')
chapter = PathChapter.objects.create(learning_path=path, chapter=taxonomy, title='Limites', order=0)
level = ClassLevel.objects.create(name='Niveau test vidéo', order=99)
created_path = client.post('/api/learning-paths/', {
    'subject': subject.pk, 'class_level': [level.pk], 'title': 'Nouveau parcours',
    'estimated_hours': 0, 'is_active': True,
}, format='json')
assert created_path.status_code == 201 and created_path.data.get('id'), created_path.data
created_chapter = client.post('/api/path-chapters/', {
    'learning_path': created_path.data['id'], 'chapter': taxonomy.pk, 'title': 'Premier chapitre',
    'order': 0, 'videos': [],
}, format='json')
assert created_chapter.status_code == 201 and created_chapter.data.get('id'), created_chapter.data
content = b'\x00\x00\x00\x18ftypisom' + b'0' * 28
metadata = {'path_chapter': chapter.pk, 'title': 'Cours de limites', 'duration_seconds': 90, 'order': 0}
response = client.post('/api/videos/upload_init/', {
    'name': 'limites.mp4', 'mime_type': 'video/mp4', 'size': len(content), 'video': metadata,
}, format='json')
assert response.status_code == 201, response.data
session = response.data['session']
assert not Video.objects.exists()

def chunk(offset, data):
    return client.post('/api/videos/upload_part/', {
        'session': session, 'offset': offset,
        'file': SimpleUploadedFile('video.part', data, content_type='application/octet-stream'),
    }, format='multipart')

assert chunk(0, content[:20]).data['received'] == 20
assert chunk(0, content[:20]).data['received'] == 20
assert chunk(30, content[30:]).status_code == 409
assert client.post('/api/videos/upload_finish/', {'session': session}, format='json').status_code == 400
client.force_authenticate(other)
assert chunk(20, content[20:]).status_code == 404
client.force_authenticate(staff)
assert chunk(20, content[20:]).data['received'] == len(content)
response = client.post('/api/videos/upload_finish/', {'session': session}, format='json')
assert response.status_code == 201, response.data
video_id = response.data['id']
signed_url = response.data['url']
assert '?play=' in signed_url
response = client.post('/api/videos/upload_finish/', {'session': session}, format='json')
assert response.status_code == 200 and response.data['id'] == video_id
assert Video.objects.count() == 1
attachment = FileAttachment.objects.get(object_id=video_id)
with attachment.file.open('rb') as saved:
    assert saved.read() == content
assert attachment.file.name.startswith('parcours-videos/')
video = Video.objects.get(pk=video_id)
assert '?play=' not in video.url
# L'édition d'un titre ne stocke jamais le jeton temporaire de lecture.
response = client.patch(f'/api/videos/{video_id}/', {'title': 'Titre corrigé', 'url': signed_url}, format='json')
assert response.status_code == 200, response.data
video.refresh_from_db()
assert video.title == 'Titre corrigé' and '?play=' not in video.url
replacement = client.post('/api/videos/upload_init/', {
    'name': 'remplacement.mp4', 'mime_type': 'video/mp4', 'size': len(content),
    'video': metadata, 'target': video_id,
}, format='json')
assert replacement.status_code == 201, replacement.data
session = replacement.data['session']
assert chunk(0, content).data['received'] == len(content)
replacement = client.post('/api/videos/upload_finish/', {'session': session}, format='json')
assert replacement.status_code == 201 and replacement.data['id'] == video_id
assert Video.objects.count() == 1
client.force_authenticate(student)
assert client.get('/api/learning-paths/').status_code == 404
assert client.get(urlsplit(video.url).path).status_code == 404
assert client.post('/api/videos/upload_init/', {}, format='json').status_code == 403
client.force_authenticate(None)
signed_path = urlsplit(signed_url)
response = client.get(signed_path.path + '?' + signed_path.query)
assert response.status_code == 200
assert b''.join(response.streaming_content) == content
response.close()
assert client.get(signed_path.path + '?play=invalide').status_code == 404
print('OK — blocs repris, pas de doublon, fichier exact, titre édité, élève bloqué et lecture privée')
temp.cleanup()
