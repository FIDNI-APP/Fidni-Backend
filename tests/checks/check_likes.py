"""J'aime / je n'aime pas : nombres séparés, tri « Plus aimés », encart de l'accueil."""
import os
import sys
import tempfile
from datetime import date, timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-likes.sqlite3')
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
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
users = [User.objects.create_user(f'eleve{i}', f'e{i}@x.fr', 'Motdepasse-solide-42') for i in range(3)]
for u in users:
    u.profile.class_level = level
    u.profile.save()


def make(title):
    c = Content.objects.create(type='exercise', title=title, author=editorial, subject=subject,
                               json_content={'version': '2.1', 'blocks': []})
    c.class_levels.add(level)
    return c


d = make('D : un je n’aime pas')
c_ = make('C : aucun vote')
b = make('B : 2 j’aime, 1 je n’aime pas')
a = make('A : 2 j’aime')
cl = APIClient()


def vote(user, item, value):
    cl.force_authenticate(user)
    return cl.post(f'/api/contents/{item.id}/vote/', {'value': value}, format='json')


vote(users[0], a, 1); vote(users[1], a, 1)
vote(users[0], b, 1); vote(users[1], b, 1); vote(users[2], b, -1)
r = vote(users[0], d, -1)
check('réponse du vote : j’aime et je n’aime pas séparés', r.status_code == 200 and r.data['like_count'] == 0
      and r.data['dislike_count'] == 1 and r.data['user_vote'] == -1, r.data)
r = vote(users[0], d, -1)
check('re-cliquer retire le vote', r.data['dislike_count'] == 0 and r.data['user_vote'] == 0, r.data)
vote(users[0], d, -1)

cl.force_authenticate(None)
r = cl.get('/api/contents/?type=exercise&sort=most_upvoted')
rows = r.data['results'] if isinstance(r.data, dict) else r.data
titles = [x['title'][0] for x in rows]
check('tri « Plus aimés » : plus de j’aime, puis moins de je n’aime pas', titles == ['A', 'B', 'C', 'D'], titles)
rb = next(x for x in rows if x['id'] == b.id)
check('carte : 2 j’aime, 1 je n’aime pas', rb['like_count'] == 2 and rb['dislike_count'] == 1 and rb['vote_count'] == 1, rb)
r = cl.get(f'/api/contents/{b.id}/')
check('page du contenu : nombres séparés', r.data['like_count'] == 2 and r.data['dislike_count'] == 1, r.status_code)
r = cl.get('/api/contents/?type=exercise&sort=oldest')
rows = r.data['results'] if isinstance(r.data, dict) else r.data
check('tri « Plus anciens » inchangé', [x['title'][0] for x in rows] == ['D', 'C', 'B', 'A'], [x['title'][0] for x in rows])

cl.force_authenticate(users[2])
r = cl.get('/api/dashboard/recommended/')
ex = [x['title'][0] for x in r.data['exercises']]
check('accueil : les plus aimés du niveau, niveau renvoyé', r.status_code == 200 and ex[:2] == ['A', 'B']
      and r.data['level'] == '2ème Bac SM', (ex, r.data.get('level')))

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
