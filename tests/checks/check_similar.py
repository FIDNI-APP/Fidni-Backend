"""« Pour continuer » : contenus semblables sous un contenu (apps/things/similar.py)."""
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-similar.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))  # taxonomie réelle
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.interactions.models import Complete  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


author = User.objects.create_user('Fidni', 'f@x.fr', None)
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
sm = ClassLevel.objects.get(name='2ème Bac SM')
tc = ClassLevel.objects.get(name='Tronc commun Sciences')
lim = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
der = Chapter.objects.filter(name__startswith='Dérivation', class_levels=sm).first()


def make(title, kind='exercise', level=sm, chapters=(), skills=(), difficulty='medium'):
    js = {'version': '2.1', 'blocks': [{'id': 'b1', 'type': 'question', 'content': {'html': '<p>x</p>'},
                                         'meta': {'skills': list(skills)}}]}
    c = Content.objects.create(type=kind, title=title, author=author, json_content=js,
                               difficulty=difficulty if kind != 'lesson' else None)
    c.class_levels.set([level])
    c.chapters.set([ch for ch in chapters if ch])
    return c


src = make('Source', chapters=[lim], skills=['tvi', 'limites-usuelles'])
proche = make('Mêmes notions', chapters=[lim], skills=['tvi', 'limites-usuelles'])
chapitre = make('Même chapitre', chapters=[lim], skills=['bijection'])
autre = make('Autre chapitre', chapters=[der], skills=['derivee'])
niveau = make('Autre niveau', level=tc, chapters=[lim], skills=['tvi', 'limites-usuelles'])
lecon = make('Cours des limites', kind='lesson', chapters=[lim])
cache.delete('similar_index_v1')

c = APIClient()
r = c.get(f'/api/contents/{src.id}/recommendations/')
titles = [x['title'] for x in r.data['items']]
check('réponse', r.status_code == 200, r.status_code)
check('mêmes notions en tête', titles[:1] == ['Mêmes notions'], titles)
check('même chapitre ensuite, leçon du chapitre proposée', 'Même chapitre' in titles and 'Cours des limites' in titles, titles)
check('rien de commun : absent', 'Autre chapitre' not in titles, titles)
check('autre niveau : absent', 'Autre niveau' not in titles, titles)
check('jamais le contenu lui-même', 'Source' not in titles, titles)
reasons = {x['title']: x['reason'] for x in r.data['items']}
check('raison lisible', reasons['Mêmes notions'].startswith('Mêmes notions :')
      and reasons['Cours des limites'].startswith('Même chapitre :'), reasons)

Complete.objects.create(user=eleve, content_type=ContentType.objects.get_for_model(Content), object_id=str(proche.id),
                        status='success')
c.force_authenticate(eleve)
titles = [x['title'] for x in c.get(f'/api/contents/{src.id}/recommendations/').data['items']]
check('déjà réussi : passe derrière', titles.index('Mêmes notions') > titles.index('Même chapitre'), titles)
check('contenu inconnu : 404', c.get('/api/contents/999999/recommendations/').status_code == 404)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
