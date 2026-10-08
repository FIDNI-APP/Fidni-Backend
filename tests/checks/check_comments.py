"""Commentaires : réponses imbriquées sous le commentaire d'origine, rattachement des anciennes réponses."""
import importlib
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-comments.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.apps import apps as django_apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.notifications.services import excerpt  # noqa: E402
from apps.things.models import Comment, Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


auteur = User.objects.create_user('prof', 'p@x.fr', 'Motdepasse-solide-42')
a, b = (User.objects.create_user(n, f'{n}@x.fr', 'Motdepasse-solide-42') for n in ('amina', 'badr'))
ex = Content.objects.create(type='exercise', title='Ex', author=auteur, json_content={'blocks': []})
autre = Content.objects.create(type='exercise', title='Autre', author=auteur, json_content={'blocks': []})


def client(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


racine = client(a).post(f'/api/contents/{ex.id}/comment/', {'content': '<p>Question 2 : je bloque</p>'}, format='json').data
r1 = client(b).post(f'/api/contents/{ex.id}/comment/', {'content': '<p>@amina pose $u_n$</p>', 'parent_id': racine['id']}, format='json')
r2 = client(a).post(f'/api/contents/{ex.id}/comment/', {'content': '<p>@badr merci !</p>', 'parent': r1.data['id']}, format='json')
check('réponse avec « parent_id » (envoyé par la page du contenu)', r1.status_code == 201
      and Comment.objects.get(pk=r1.data['id']).parent_id == racine['id'], r1.status_code)
check('réponse avec « parent »', r2.status_code == 201 and Comment.objects.get(pk=r2.data['id']).parent_id == r1.data['id'])
tree = client(a).get(f'/api/contents/{ex.id}/').data['comments']
check('arbre : un seul commentaire racine, réponses dedans', len(tree) == 1 and tree[0]['replies'][0]['id'] == r1.data['id']
      and tree[0]['replies'][0]['replies'][0]['id'] == r2.data['id'], tree)
ailleurs = Comment.objects.create(content_item=autre, author=b, content='ailleurs')
r = client(a).post(f'/api/contents/{ex.id}/comment/', {'content': 'x', 'parent': ailleurs.id}, format='json')
check('parent d\'un autre contenu : refusé', r.status_code == 400, r.status_code)
r = client(a).post(f'/api/contents/{ex.id}/comment/', {'content': 'x', 'parent': 'abc'}, format='json')
check('parent invalide : refusé', r.status_code == 400, r.status_code)

# Anciennes réponses enregistrées à plat : rattachées par la migration 0009.
Comment.objects.all().delete()
t0 = timezone.now() - timedelta(days=5)
q = Comment.objects.create(content_item=ex, author=a, content='Comment faire la 3 ?')
rep1 = Comment.objects.create(content_item=ex, author=b, content='@amina utilise la récurrence')
rep2 = Comment.objects.create(content_item=ex, author=a, content='@badr super, merci')
seul = Comment.objects.create(content_item=ex, author=b, content='Autre question sans mention')
fantome = Comment.objects.create(content_item=ex, author=b, content='@inconnu bonjour')
for i, c in enumerate([q, rep1, rep2, seul, fantome]):
    Comment.objects.filter(pk=c.pk).update(created_at=t0 + timedelta(minutes=i))
importlib.import_module('apps.things.migrations.0009_rattacher_reponses').rattacher(django_apps, None)
p = dict(Comment.objects.values_list('id', 'parent_id'))
check('ancienne réponse « @amina » rattachée au commentaire d\'amina', p[rep1.id] == q.id, p)
check('réponse à la réponse rattachée à la bonne réponse', p[rep2.id] == rep1.id, p)
check('sans mention, ou mention sans commentaire : inchangé', p[seul.id] is None and p[fantome.id] is None and p[q.id] is None, p)

check('extrait de notification sans HTML, formules gardées',
      excerpt('<p>Pose <strong>$u_n = 1$</strong> &amp; conclus</p><p>fin</p>') == 'Pose $u_n = 1$ & conclus fin',
      excerpt('<p>Pose <strong>$u_n = 1$</strong> &amp; conclus</p><p>fin</p>'))

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
