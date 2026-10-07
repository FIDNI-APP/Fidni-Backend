"""Pages par niveau et par chapitre (apps/caracteristics/hubs.py) : API, page pré-remplie, sitemap, liens."""
import json
import os
import re
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-hubs.sqlite3')
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
from django.test import Client  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Subject  # noqa: E402
from apps.things.models import Content  # noqa: E402
import config.seo as seo  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
settings.FRONTEND_URL = 'https://fidni.fr'
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


INDEX = ('<!doctype html><html lang="fr"><head><title>Fidni</title><meta name="title" content="Fidni" />'
         '<meta name="description" content="Générique" /><meta name="robots" content="index, follow" />'
         '<meta name="googlebot" content="index, follow" /></head><body><div id="root"></div></body></html>')
seo._index_cache.update(html=INDEX, at=10 ** 12)

u = User.objects.create_user('auteur', 'a@x.fr', 'x')
sm2 = ClassLevel.objects.get(name='2ème Bac SM')
pc2 = ClassLevel.objects.get(name='2ème Bac PC')
maths = Subject.objects.get(name='Mathématiques')
lim = Chapter.objects.get(name='Limites et continuité', class_levels=sm2)
suites = Chapter.objects.filter(class_levels=sm2, name__icontains='suites').first()


def make(kind, title, chapter):
    c = Content.objects.create(type=kind, title=title, author=u, subject=maths, json_content={'version': '2.1', 'blocks': []})
    c.class_levels.add(sm2)
    c.chapters.add(chapter)
    return c


e1, e2 = make('exercise', 'Prolongement par continuité', lim), make('exercise', 'Théorème des valeurs intermédiaires', lim)
e3 = make('exercise', 'Suite récurrente', suites)
lesson = make('lesson', 'Cours : limites et continuité', lim)
cl = Client()

# ── API
r = cl.get('/api/hubs/', {'section': 'exercises', 'level': '2eme-bac-sm'})
check('API niveau : 200', r.status_code == 200, r.status_code)
d = r.json()
check('niveau : compte et textes', d['count'] == 3 and d['h1'] == 'Exercices corrigés de maths – 2ème Bac SM'
      and '2 Bac SM' in d['title'] and d['indexable'], d)
check('niveau : chapitres avec contenu seulement, comptés',
      [(c['name'], c['count']) for c in d['chapters']] == sorted([(lim.name, 2), (suites.name, 1)], key=lambda x: Chapter.objects.get(name=x[0], class_levels=sm2).id), d['chapters'])
check('niveau : lien vers les cours du même niveau', [x['url'] for x in d['related']] == ['/lessons/niveau/2eme-bac-sm'], d['related'])

r = cl.get('/api/hubs/', {'section': 'exercises', 'level': '2eme-bac-sm', 'chapter': 'limites-et-continuite'})
d = r.json()
check('chapitre : 2 exercices, titre de recherche', r.status_code == 200 and d['count'] == 2
      and d['title'].startswith('Limites et continuité – Exercices corrigés 2ème Bac SM'), d)
check('chapitre : identifiants pour filtrer la liste', d['level']['id'] == sm2.id and d['chapter']['id'] == lim.id)
check('chapitre : lien vers le cours du chapitre', d['related'] == [
    {'section': 'lessons', 'label': 'Cours', 'count': 1, 'url': '/lessons/niveau/2eme-bac-sm/limites-et-continuite'}], d['related'])
check('niveau inconnu : 404', cl.get('/api/hubs/', {'section': 'exercises', 'level': 'cm2'}).status_code == 404)
check('chapitre inconnu : 404', cl.get('/api/hubs/', {'section': 'exercises', 'level': '2eme-bac-sm', 'chapter': 'zzz'}).status_code == 404)
d = cl.get('/api/hubs/', {'section': 'exercises', 'level': '2eme-bac-pc'}).json()
check('niveau sans contenu : consultable mais non indexable', d['count'] == 0 and not d['indexable'], d)

# ── Pages pré-remplies
r = cl.get('/seo/hub/exercises/2eme-bac-sm/limites-et-continuite/')
page = r.content.decode()
check('page chapitre : 200', r.status_code == 200, r.status_code)
check('page chapitre : titre, canonique, H1', '<title>Limites et continuité – Exercices corrigés 2ème Bac SM (2 Bac SM) | Fidni</title>' in page
      and 'href="https://fidni.fr/exercises/niveau/2eme-bac-sm/limites-et-continuite"' in page
      and '<h1 style="font-size:28px">Limites et continuité : exercices corrigés – 2ème Bac SM</h1>' in page, page[:900])
check('page chapitre : liens vers chaque exercice', f'href="/exercises/{e1.id}"' in page and f'href="/exercises/{e2.id}"' in page
      and f'href="/exercises/{e3.id}"' not in page)
check('page chapitre : autres chapitres et cours', 'href="/exercises/niveau/2eme-bac-sm/' + suites.name.lower().replace(' ', '-').replace('é', 'e') in page
      or '/exercises/niveau/2eme-bac-sm/' in page.split('Autres chapitres')[1], 'Autres chapitres')
check('page chapitre : fil d’Ariane schema.org', '"@type": "BreadcrumbList"' in page and '"@type": "CollectionPage"' in page)
r = cl.get('/seo/hub/exercises/2eme-bac-pc/')
check('page sans contenu : noindex', r.status_code == 200 and 'content="noindex"' in r.content.decode())
check('page inconnue : 404', cl.get('/seo/hub/exercises/cm2/').status_code == 404)

# ── Page d'exercice : fil d'Ariane en liens et exercices voisins
page = cl.get(f'/seo/exercises/{e1.id}/').content.decode()
check('exercice : fil d’Ariane vers niveau et chapitre', 'href="/exercises/niveau/2eme-bac-sm"' in page
      and 'href="/exercises/niveau/2eme-bac-sm/limites-et-continuite"' in page, page[:1500])
check('exercice : exercices du même chapitre', f'href="/exercises/{e2.id}"' in page and f'href="/exercises/{e3.id}"' not in page)
ld = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page)]
crumbs = [x for x in (ld[0] if ld and isinstance(ld[0], list) else ld) if x.get('@type') == 'BreadcrumbList']
check('exercice : BreadcrumbList complète', crumbs and [i['name'] for i in crumbs[0]['itemListElement']]
      == ['Accueil', 'Exercices corrigés', '2ème Bac SM', 'Limites et continuité', 'Prolongement par continuité'], ld)

# ── Listes, accueil, sitemap
page = cl.get('/seo/page/exercises/').content.decode()
check('liste : niveau et chapitre en liens', '<a href="/exercises/niveau/2eme-bac-sm">2ème Bac SM</a>' in page
      and '<a href="/exercises/niveau/2eme-bac-sm/limites-et-continuite">' in page)
page = cl.get('/seo/page/home/').content.decode()
check('accueil : liens par niveau', 'href="/exercises/niveau/2eme-bac-sm"' in page and 'href="/lessons/niveau/2eme-bac-sm"' in page
      and '2eme-bac-pc' not in page)
xml = cl.get('/sitemap.xml').content.decode()
check('sitemap : hubs avec contenu', 'https://fidni.fr/exercises/niveau/2eme-bac-sm/limites-et-continuite</loc>' in xml
      and 'https://fidni.fr/lessons/niveau/2eme-bac-sm</loc>' in xml and '2eme-bac-pc' not in xml)

# ── Examens : section devoirs / section nationaux (le filtre était ignoré : paramètre mal nommé)
ds = make('exam', 'Devoir surveillé n° 1', lim)
bac = make('exam', 'Examen national 2019', lim)
bac.is_national_exam, bac.national_year = True, 2019
bac.save()
ids = lambda r: {x['id'] for x in r.json().get('results', [])}  # noqa: E731
r = cl.get('/api/contents/', {'type': 'exam', 'is_national_exam': 'true'})
check('examens nationaux seulement', ids(r) == {bac.id}, ids(r))
r = cl.get('/api/contents/', {'type': 'exam', 'is_national_exam': 'false'})
check('section Examens : devoirs seulement', ids(r) == {ds.id}, ids(r))
r = cl.get('/api/contents/', {'type': 'exam', 'is_national_exam': 'true', 'national_year_min': 2020})
check('année du Bac : filtre', ids(r) == set(), ids(r))
r = cl.get('/api/contents/', {'type': 'exam', 'is_national_exam': 'true', 'national_year_min': 2015, 'national_year_max': 2019})
check('année du Bac : intervalle', ids(r) == {bac.id}, ids(r))

# ── Compteur de vues (visiteurs comptés, une fois par 24 h ; robots et comptes maison exclus)
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
cache.clear()
NAV = {'HTTP_USER_AGENT': 'Mozilla/5.0 (Linux; Android 14) Chrome/128 Mobile', 'HTTP_CF_CONNECTING_IP': '41.1.2.3'}
vc = lambda: Content.objects.get(pk=e1.pk).view_count  # noqa: E731
v0 = vc()
r = cl.post(f'/api/contents/{e1.id}/view/', **NAV)
check('vue : visiteur non connecté compté', r.status_code == 200 and r.json()['counted'] and vc() == v0 + 1, (r.status_code, r.content[:120]))
r = cl.post(f'/api/contents/{e1.id}/view/', **NAV)
check('vue : même visiteur le même jour, pas recompté', not r.json()['counted'] and vc() == v0 + 1)
r = cl.post(f'/api/contents/{e1.id}/view/', **{**NAV, 'HTTP_CF_CONNECTING_IP': '41.9.9.9'})
check('vue : autre visiteur compté', r.json()['counted'] and vc() == v0 + 2)
r = cl.post(f'/api/contents/{e1.id}/view/', HTTP_USER_AGENT='Mozilla/5.0 (compatible; Googlebot/2.1)')
check('vue : robot non compté', not r.json()['counted'] and vc() == v0 + 2)
eleve = User.objects.create_user('eleve_vues', 'ev@x.fr', 'x')
ac = APIClient(); ac.force_authenticate(eleve)
r = ac.post(f'/api/contents/{e1.id}/view/', **NAV)
check('vue : élève connecté compté', r.json()['counted'] and vc() == v0 + 3)
r = ac.post(f'/api/contents/{e1.id}/view/', **NAV)
check('vue : élève, une fois par 24 h', not r.json()['counted'] and vc() == v0 + 3)
adm = User.objects.create_superuser('admin_vues', 'av@x.fr', 'x')
aa = APIClient(); aa.force_authenticate(adm)
r = aa.post(f'/api/contents/{e1.id}/view/', **NAV)
check('vue : administrateur non compté', not r.json()['counted'] and vc() == v0 + 3)
from django.utils import timezone as _tz  # noqa: E402
from apps.things.models import ContentDailyView  # noqa: E402
dv = ContentDailyView.objects.filter(content=e1, date=_tz.localdate()).first()
check('vue : comptée aussi dans le jour (courbe du Pilotage)', dv is not None and dv.count == 3, dv and dv.count)

# ── Slugs exposés par l'API (liens de l'application)
r = cl.get(f'/api/class-levels/{sm2.id}/')
check('API niveaux : slug', r.status_code == 200 and r.json().get('slug') == '2eme-bac-sm', r.status_code)
r = cl.get('/api/contents/', {'type': 'exercise'})
item = next((x for x in r.json().get('results', []) if x['id'] == e1.id), None) if r.status_code == 200 else None
check('API contenus : slug des chapitres', item is not None and item['chapters'][0]['slug'] == 'limites-et-continuite', r.status_code)

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
