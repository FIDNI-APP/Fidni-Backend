import os
import tempfile
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': os.path.join(tempfile.gettempdir(), 'fidni-search.sqlite3'), 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists('/tmp/fidni-search.sqlite3'):
    os.remove('/tmp/fidni-search.sqlite3')
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.caracteristics.models import Chapter  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
u = User.objects.create_user('prof', 'p@x.fr', 'Motdepasse-solide-42')
a = Content.objects.create(type='exercise', title='Suites numériques', author=u,
                           json_content={'blocks': [{'type': 'context', 'content': {'html': '<p>Soit la fonction f définie…</p>'}}]})
b = Content.objects.create(type='exercise', title='Étude de fonction', author=u, json_content={'blocks': []})
c = Content.objects.create(type='exercise', title='Probabilités', author=u, json_content={'blocks': []})
ch1 = Chapter.objects.create(name='Fonctions 1') if hasattr(Chapter, 'name') else None
res = []
cl = APIClient()
r = cl.get('/api/contents/', {'type': 'exercise', 'search': 'fonction'})
ids = [x['id'] for x in r.data.get('results', r.data)] if r.status_code == 200 else r.status_code
print('statut', r.status_code, 'ids', ids)
res.append(r.status_code == 200 and ids == [b.id, a.id])
r = cl.get('/api/contents/', {'type': 'exercise', 'search': 'fonction soit'})
ids2 = [x['id'] for x in r.data.get('results', r.data)]
print('deux mots', ids2)
res.append(ids2 == [a.id])
r = cl.get('/api/contents/', {'type': 'exercise', 'search': 'fonction', 'sort': 'oldest'})
ids3 = [x['id'] for x in r.data.get('results', r.data)]
print('tri explicite', ids3)
res.append(ids3 == [a.id, b.id])
print('OK' if all(res) else 'FAIL', res)
sys.exit(0 if all(res) else 1)
