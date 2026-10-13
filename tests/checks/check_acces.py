"""Accès réservés (12/10/2026) : création de contenu pour l'équipe seulement, « Mes documents » pour les
enseignants (déclarés) et l'équipe. Modifier son propre contenu reste possible."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-acces.sqlite3')
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
from django.core.cache import cache  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user=None):
    cache.clear()
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


eleve = User.objects.create_user('eleve_a', 'e@x.fr', 'x')
prof = User.objects.create_user('prof_a', 'p@x.fr', 'x')
prof.profile.user_type = 'teacher'
prof.profile.save(update_fields=['user_type'])
admin = User.objects.create_superuser('chef_a', 'c@x.fr', 'x')
staff = User.objects.create_user('staff_a', 's@x.fr', 'x', is_staff=True)
level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
BODY = {'type': 'exercise', 'title': 'Exercice', 'difficulty': 'easy', 'subject': subject.pk, 'class_levels': [level.pk],
        'json_content': {'version': '2.1', 'blocks': []}}

# ── Création de contenu : l'équipe seulement
check('visiteur : création refusée', client().post('/api/contents/', BODY, format='json').status_code in (401, 403))
r = client(eleve).post('/api/contents/', BODY, format='json')
check('élève : création refusée', r.status_code == 403, r.status_code)
r = client(prof).post('/api/contents/', BODY, format='json')
check('enseignant : création refusée (pour l’instant)', r.status_code == 403
      and 'réservée à l’équipe' in str(r.data.get('detail', '')), (r.status_code, r.data))
r = client(admin).post('/api/contents/', BODY, format='json')
check('administrateur : création acceptée', r.status_code == 201, (r.status_code, r.data))
r = client(staff).post('/api/contents/', {**BODY, 'title': 'Par le staff'}, format='json')
check('staff : création acceptée', r.status_code == 201, (r.status_code, r.data))

# ── Un contenu déjà publié par un enseignant : il le modifie toujours ; les autres gestes restent ouverts
old = Content.objects.create(type='exercise', title='Ancien', author=prof, subject=subject, json_content={'version': '2.1', 'blocks': []})
old.class_levels.add(level)
r = client(prof).patch(f'/api/contents/{old.id}/', {'title': 'Ancien (corrigé)'}, format='json')
check('auteur : modifie son contenu existant', r.status_code == 200, (r.status_code, getattr(r, 'data', None)))
r = client(eleve).patch(f'/api/contents/{old.id}/', {'title': 'Piraté'}, format='json')
check('élève : ne modifie pas le contenu d’un autre', r.status_code == 403, r.status_code)
r = client(eleve).post(f'/api/contents/{old.id}/vote/', {'value': 1}, format='json')
check('élève : vote toujours possible', r.status_code in (200, 201), (r.status_code, getattr(r, 'data', None)))
check('lecture publique inchangée', client().get(f'/api/contents/{old.id}/').status_code == 200)

# ── Import PDF de l'assistant de création : l'équipe seulement
pdf = SimpleUploadedFile('x.pdf', b'%PDF-1.4 vide', content_type='application/pdf')
r = client(prof).post('/api/parse-pdf/', {'file': pdf, 'content_type': 'exercise'}, format='multipart')
check('enseignant : import PDF refusé', r.status_code == 403, r.status_code)

# ── « Mes documents » : enseignants et équipe
check('élève : « Mes documents » refusé', client(eleve).get('/api/documents/').status_code == 403)
check('enseignant : « Mes documents » ouvert', client(prof).get('/api/documents/').status_code == 200)
check('administrateur : « Mes documents » ouvert', client(admin).get('/api/documents/').status_code == 200)
r = client(prof).post('/api/documents/', {'title': 'DS', 'html': '<p>Soit</p>'}, format='json')
check('enseignant : crée un document', r.status_code == 201, (r.status_code, getattr(r, 'data', None)))

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
