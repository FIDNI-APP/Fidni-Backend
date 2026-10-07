"""Cahiers : création sous le nom choisi par l'élève, nom par défaut, doublons refusés proprement."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-cahiers.sqlite3')
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
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.notebooks.models import Notebook  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
level2 = ClassLevel.objects.get(name='1ère Bac SM')
alice = User.objects.create_user('alice', 'alice@x.fr', 'Motdepasse-solide-42')
c = APIClient()
c.force_authenticate(alice)

r = c.post('/api/notebooks/create_notebook/', {'subject_id': subject.id, 'class_level_id': level.id,
                                                'title': '  Mon cahier de terminale  '}, format='json')
check('création acceptée', r.status_code == 201, r.status_code)
check('nom choisi conservé (espaces retirés)', r.data.get('title') == 'Mon cahier de terminale', r.data.get('title'))
check('sections créées depuis les chapitres', len(r.data.get('sections', [])) > 0)
check('nom enregistré en base', Notebook.objects.get(user=alice, class_level=level).title == 'Mon cahier de terminale')

r = c.post('/api/notebooks/create_notebook/', {'subject_id': subject.id, 'class_level_id': level2.id,
                                                'title': 'Mon cahier de terminale'}, format='json')
check('nom déjà pris : refus clair (400, pas 500)', r.status_code == 400 and 'nom' in r.data.get('error', ''), r.status_code)

r = c.post('/api/notebooks/create_notebook/', {'subject_id': subject.id, 'class_level_id': level2.id}, format='json')
check('sans nom : « Matière - Niveau »', r.status_code == 201 and r.data.get('title') == 'Mathématiques - 1ère Bac SM', r.data)

r = c.post('/api/notebooks/create_notebook/', {'subject_id': subject.id, 'class_level_id': level.id,
                                                'title': 'Révisions du bac'}, format='json')
check('deuxième cahier de même matière et même niveau, autre nom : accepté', r.status_code == 201
      and Notebook.objects.filter(user=alice, class_level=level).count() == 2, (r.status_code, getattr(r, 'data', None)))

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
