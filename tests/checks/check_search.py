import os
import tempfile
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-search.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.caracteristics.models import Chapter  # noqa: E402
from django.core.cache import cache  # noqa: E402

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

# ── Sans accents, sans balises ni LaTeX (Content.search_text), classement titre > chapitre > texte
from apps.caracteristics.models import ClassLevel  # noqa: E402


def found(**params):
    r = cl.get('/api/contents/', {'type': 'exercise', **params})
    return [x['id'] for x in r.data.get('results', r.data)] if r.status_code == 200 else r.status_code


d = Content.objects.create(type='exercise', title="Dérivée d'une fonction", author=u, json_content={'blocks': []})
r = found(search='derivee')
print('sans accents', r)
res.append(r == [d.id])
res.append(found(search='DÉRIVÉE') == [d.id])
e = Content.objects.create(type='exercise', title='Calculs', author=u, json_content={'blocks': [
    {'type': 'question', 'content': {'html': '<p><strong>Montrer</strong> que $\\frac{1}{x} \\leqslant \\sqrt{x}$</p>'}}]})
r = [found(search=w) for w in ('montrer', 'strong', 'frac', 'leqslant')]
print('HTML et LaTeX ignorés', r)
res.append(r == [[e.id], [], [], []])

lim = Chapter.objects.create(name='Limites et continuité')
cache.delete('search_taxonomy_names_v1')  # noms de la taxonomie gardés 10 min par la recherche
g = Content.objects.create(type='exercise', title='Limites usuelles', author=u, json_content={'blocks': []})
f = Content.objects.create(type='exercise', title='Prolongement', author=u, json_content={'blocks': []})
f.chapters.set([lim])
h = Content.objects.create(type='exercise', title='Un calcul', author=u,
                           json_content={'blocks': [{'type': 'context', 'content': {'html': '<p>Les limites en 0</p>'}}]})
r = found(search='limites')
print('titre > chapitre > texte', r)
res.append(r == [g.id, f.id, h.id])
r = found(search='continuite')
print('nom de chapitre sans accent', r)
res.append(r == [f.id])

sm = ClassLevel.objects.create(name='2ème Bac SM', order=7)
cache.delete('search_taxonomy_names_v1')
g.class_levels.set([sm])
h.class_levels.set([sm])
r1, r2 = found(search='limites', **{'class_levels[]': sm.id}), found(search='limites', class_levels=str(sm.id))
print('niveau', r1, r2)
res.append(r1 == r2 == [g.id, h.id])
r = found(search='limites 2eme bac')
print('niveau tapé dans la recherche', r)
res.append(sorted(r) == sorted([g.id, h.id]))
print('OK' if all(res) else 'FAIL', res)
sys.exit(0 if all(res) else 1)
