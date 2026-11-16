"""Devoirs rangés par semestre et par numéro (Natsu, 16/11/2026) : lecture du titre (things/devoir.py `rang`),
dossiers de la page d'un niveau (hubs.py `devoirs`), page d'un dossier, filtre `devoir=` de la liste et des
compteurs, page pré-remplie et sitemap."""
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-devoirs-numeros.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from apps.caracteristics import programme  # noqa: E402
from apps.caracteristics.hubs import all_hubs  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Subject  # noqa: E402
from apps.things.devoir import lire_slug_devoir, rang, semestre_de_periode  # noqa: E402
from apps.things.models import Content  # noqa: E402
import config.seo as seo  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
settings.FRONTEND_URL = 'https://fidni.fr'
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


# ── Lecture du titre
check('rang : numéro et mois de novembre → semestre 1',
      rang('Devoir surveillé n° 2 — 2ème Bac SM, M. Haddar (novembre 2024)') == (1, 2))
check('rang : janvier → semestre 1', rang('Devoir surveillé n° 3 — 2ème Bac SM (janvier 2022)') == (1, 3))
check('rang : mars → semestre 2', rang('Devoir surveillé n° 1 — 2ème Bac SM (mars 2026)') == (2, 1))
check('rang : semestre écrit dans le titre', rang('Contrôle n° 2 du semestre 1 — 2ème Bac SM (2026-2027)') == (1, 2)
      and rang('Devoir n° 1 du 2ème semestre') == (2, 1) and rang('CC2 S2 — 1ère Bac SM') == (2, 2))
check('rang : devoir de contrôle, de synthèse numérotés',
      rang('Devoir de contrôle n° 1 — 1ère Bac SM (octobre 2026)') == (1, 1)
      and rang('Devoir de synthèse n° 1 — 2ème Bac SM (octobre 2025)') == (1, 1))
check('rang : sans numéro, bac blanc → pas de numéro',
      rang('Devoir surveillé — 2ème Bac PC/SVT (fonction réciproque)')[1] is None
      and rang('Bac blanc — 2ème Bac SM (mai 2025)')[1] is None)
check('rang : devoir maison ou libre numéroté → même numéro que le DS',
      rang('Devoir maison n° 1 (octobre 2025)') == (1, 1)
      and rang('Devoir libre n° 1 — 2ème Bac SM (Lycée Riad Ezzahia) : limites') == (1, 1))
check('rang : sans mois, période du chapitre', rang('Devoir surveillé n° 2 — M. X', ['Semestre 2 (semaines 1–3)']) == (2, 2)
      and rang('Devoir surveillé n° 2 — M. X') == (1, 2))
check('période : premier semestre cité', semestre_de_periode('Semestre 1 (semaines 12–15) puis semestre 2') == 1)
check('adresse d\'un dossier', lire_slug_devoir('devoir-2-semestre-1') == (1, 2)
      and lire_slug_devoir('autres-devoirs-semestre-2') == (2, None)
      and lire_slug_devoir('devoir-0-semestre-1') is None and lire_slug_devoir('suites-numeriques') is None)

# ── Contenus
INDEX = ('<!doctype html><html lang="fr"><head><title>Fidni</title><meta name="title" content="Fidni" />'
         '<meta name="description" content="Générique" /><meta name="robots" content="index, follow" />'
         '<meta name="googlebot" content="index, follow" /></head><body><div id="root"></div></body></html>')
seo._index_cache.update(html=INDEX, at=10 ** 12)
u = User.objects.create_user('auteur', 'a@x.fr', 'x')
sm2 = ClassLevel.objects.get(name='2ème Bac SM')
maths = Subject.objects.get(name='Mathématiques')
chapitres = programme.chapitres_du_niveau(sm2)
lim = next(ch for ch in chapitres if ch.name == 'Limites et continuité')
suites = next(ch for ch in chapitres if ch.name == 'Suites numériques')
# Un chapitre du semestre 2 d'après le programme (pour un devoir sans mois).
s2 = next((ch for ch in chapitres if semestre_de_periode((programme.chapitre(sm2.name, ch.name) or {}).get('periode')) == 2),
          None)


def make(title, chapter, national=False):
    c = Content.objects.create(type='exam', title=title, author=u, subject=maths, is_national_exam=national,
                               json_content={'version': '2.1', 'blocks': []})
    c.class_levels.add(sm2)
    c.chapters.add(chapter)
    return c


a = make('Devoir surveillé n° 1 — 2ème Bac SM (octobre 2024)', lim)
b = make('Devoir surveillé n° 2 — 2ème Bac SM (novembre 2024)', suites)
c2 = make('Contrôle continu n° 2 — 2ème Bac SM (décembre 2025)', lim)
autre = make('Devoir sur table — 2ème Bac SM (suites)', suites)  # sans numéro : comme le n° 2 sur les suites
dm = make('Devoir maison n° 1 — 2ème Bac SM (octobre 2024)', lim)  # devoir maison n° 1 : avec le DS n° 1
blanc = make('Bac blanc — 2ème Bac SM (janvier 2025)', lim)  # bac blanc : « Autres devoirs »
s2a = make('Devoir surveillé n° 1 — 2ème Bac SM (février 2025)', lim)
sans_mois = make('Devoir surveillé n° 2 — 2ème Bac SM, M. X', s2) if s2 else None
make('Examen national 2024', lim, national=True)
cl = Client()

r = cl.get('/api/hubs/', {'section': 'exams', 'level': '2eme-bac-sm'})
d = r.json()
dv = d.get('devoirs') or []
check('niveau : devoirs rangés par semestre', [g['semestre'] for g in dv] == [1, 2], dv)
s1 = dv[0]['folders'] if dv else []
check('semestre 1 : n° 1 (avec le devoir maison n° 1), n° 2 (avec le devoir sans numéro sur les suites), puis le bac blanc',
      [(f['name'], f['count']) for f in s1]
      == [('Devoir surveillé n° 1', 2), ('Devoir surveillé n° 2', 3), ('Autres devoirs', 1)], s1)
check('adresse du dossier', s1 and s1[1]['url'] == '/exams/niveau/2eme-bac-sm/devoir-2-semestre-1', s1)
s2f = dv[1]['folders'] if len(dv) > 1 else []
check('semestre 2 : février et devoir sans mois d\'un chapitre du semestre 2',
      [(f['numero'], f['count']) for f in s2f] == ([(1, 1), (2, 1)] if s2 else [(1, 1)]), s2f)
check('Bac national exclu', sum(f['count'] for g in dv for f in g['folders']) == (8 if s2 else 7))
check('exercices : pas de devoirs', cl.get('/api/hubs/', {'section': 'exercises', 'level': '2eme-bac-sm'}).json().get('devoirs') is None)

r = cl.get('/api/hubs/', {'section': 'exams', 'level': '2eme-bac-sm', 'chapter': 'devoir-2-semestre-1'})
d = r.json()
check('dossier : 200, textes', r.status_code == 200 and d['count'] == 3
      and d['h1'] == 'Devoir surveillé n° 2 du semestre 1 – 2ème Bac SM' and d['chapter'] is None, d)
check('dossier : chapitres de ses devoirs (filtre)', sorted(c['name'] for c in d['devoir']['chapters'])
      == sorted([lim.name, suites.name]), d.get('devoir'))
check('dossier inconnu des exercices : 404',
      cl.get('/api/hubs/', {'section': 'exercises', 'level': '2eme-bac-sm', 'chapter': 'devoir-2-semestre-1'}).status_code == 404)
vide = cl.get('/api/hubs/', {'section': 'exams', 'level': '2eme-bac-sm', 'chapter': 'devoir-5-semestre-2'}).json()
check('dossier vide : non indexé', vide['count'] == 0 and not vide['indexable'])

# ── Liste et compteurs
r = cl.get('/api/contents/', {'type': 'exam', 'class_levels': sm2.id, 'is_national_exam': 'false', 'devoir': 'devoir-2-semestre-1'})
ids = sorted(x['id'] for x in r.json()['results'])
check('liste : seulement les devoirs du dossier', ids == sorted([b.id, c2.id, autre.id]), ids)
r = cl.get('/api/contents/', {'type': 'exam', 'class_levels': sm2.id, 'devoir': 'devoir-2-semestre-1', 'chapters[]': lim.id})
check('liste : dossier + chapitre', [x['id'] for x in r.json()['results']] == [c2.id])
r = cl.get('/api/contents/', {'type': 'exam', 'devoir': 'devoir-2-semestre-1'})
check('liste : dossier sans niveau → rien', r.json()['count'] == 0)
Content.objects.filter(id=blanc.id).update(difficulty='hard')
r = cl.get('/api/difficulty-counts/', {'content_type': 'exam', 'class_levels[]': sm2.id, 'devoir': 'autres-devoirs-semestre-1'})
check('compteurs de difficulté : ceux du dossier', r.json() == {'hard': 1}, r.json())

# ── Page pré-remplie et sitemap
html = cl.get('/seo/hub/exams/2eme-bac-sm/devoir-2-semestre-1/').content.decode()
check('page pré-remplie du dossier', 'Devoir surveillé n° 2 du semestre 1 – 2ème Bac SM' in html
      and f'/exams/{b.id}' in html and f'/exams/{a.id}"' not in html)
html = cl.get('/seo/hub/exams/2eme-bac-sm/').content.decode()
check('page pré-remplie du niveau : « Par devoir »', 'Par devoir' in html and 'devoir-1-semestre-1' in html)
urls = [x for x, _ in all_hubs()]
check('sitemap : dossiers de devoirs', '/exams/niveau/2eme-bac-sm/devoir-2-semestre-1' in urls
      and '/exams/niveau/2eme-bac-sm/autres-devoirs-semestre-1' in urls)

# ── Devoir sans numéro sur un chapitre sans devoir numéroté : le chapitre numéroté le plus proche du programme
from apps.caracteristics.hubs import _rangs_devoirs  # noqa: E402
ordre = {ch.name: (programme.chapitre(sm2.name, ch.name) or {}).get('ordre') or 0 for ch in chapitres}
numerotes = {lim.name: [(1, 1), (1, 1), (1, 2), (2, 1)], suites.name: [(1, 2)]}
if s2:
    numerotes[s2.name] = [(2, 2)]
autre_ch = next(ch for ch in chapitres if ch.name not in numerotes and ordre.get(ch.name))
ecart = min(abs(ordre[n] - ordre[autre_ch.name]) for n in numerotes)
proche_nom = min((n for n in numerotes if abs(ordre[n] - ordre[autre_ch.name]) == ecart), key=lambda n: ordre[n])
attendu = min(numerotes[proche_nom], key=lambda k: (-numerotes[proche_nom].count(k), k))
proche = make('Devoir surveillé — 2ème Bac SM (sans numéro)', autre_ch)
check('sans numéro, chapitre sans devoir numéroté : celui du chapitre le plus proche',
      _rangs_devoirs(sm2)[proche.id] == attendu, (autre_ch.name, proche_nom, _rangs_devoirs(sm2)[proche.id], attendu))
# Semestre écrit dans le titre : seulement les devoirs numérotés de ce semestre (ici le n° 1 de février sur lim).
mars = make('Devoir surveillé — 2ème Bac SM (mars 2025)', lim)
check('sans numéro, semestre du titre respecté', _rangs_devoirs(sm2)[mars.id] == (2, 1), _rangs_devoirs(sm2)[mars.id])

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
