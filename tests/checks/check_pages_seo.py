"""Ce que voient les moteurs de recherche (examen AdSense « contenu à faible valeur ») : corrigé dans la page
pré-remplie d'un exercice ou d'un examen, pages « À propos » et « Contact » (API et page pré-remplie), sitemap."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-pages-seo.sqlite3')
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
cl = Client()

u = User.objects.create_user('auteur', 'a@x.fr', 'x')
sm2 = ClassLevel.objects.get(name='2ème Bac SM')
maths = Subject.objects.get(name='Mathématiques')
lim = Chapter.objects.get(name='Limites et continuité', class_levels=sm2)


def make(kind, title, structure):
    c = Content.objects.create(type=kind, title=title, author=u, subject=maths, json_content=structure)
    c.class_levels.add(sm2)
    c.chapters.add(lim)
    return c


# ── Corrigé dans la page pré-remplie
exo = make('exercise', 'Limite en zéro', {'version': '2.1', 'blocks': [
    {'id': 'c', 'type': 'context', 'content': {'html': '<p>Soit f définie sur ℝ*.</p>'}},
    {'id': 'q1', 'type': 'question', 'content': {'html': '<p>Calculer la limite de f en 0.</p>'},
     'hint': {'html': '<p>Factoriser par x.</p>'},
     'solution': {'html': '<p>On factorise par x : la limite vaut 2.</p>'}},
    {'id': 'q2', 'type': 'question', 'content': {'html': '<p>Étudier la continuité.</p>'}, 'subQuestions': [
        {'id': 'a', 'content': {'html': '<p>À gauche.</p>'}, 'solution': {'html': '<p>Continue à gauche en 0.</p>'}},
        {'id': 'b', 'content': {'html': '<p>À droite.</p>'}},
    ]},
]})
page = cl.get(f'/seo/exercises/{exo.id}/').content.decode()
check('exercice : énoncé puis « Corrigé »', page.find('Calculer la limite') < page.find('>Corrigé<') > 0, page[:300])
check('exercice : indication (« Méthode ») en tête de la solution, numérotée',
      '1. Méthode : Factoriser par x.' in page and 'On factorise par x : la limite vaut 2.' in page
      and page.find('Factoriser par x') > page.find('>Corrigé<'))
check('exercice : solution d’une sous-question, numérotée 2.1', '2.1 Continue à gauche en 0.' in page)
exam = make('exam', 'DS limites', {'version': '2.1', 'blocks': [
    {'id': 's1', 'type': 'section', 'content': {'html': '<p>Exercice 1</p>'}},
    {'id': 'q1', 'type': 'question', 'content': {'html': '<p>Q.</p>'}, 'solution': {'html': '<p>Réponse A.</p>'}},
    {'id': 's2', 'type': 'section', 'content': {'html': '<p>Exercice 2 (sans corrigé)</p>'}},
    {'id': 'q2', 'type': 'question', 'content': {'html': '<p>Q.</p>'}},
    {'id': 's3', 'type': 'section', 'content': {'html': '<p>Problème</p>'}},
    {'id': 'q3', 'type': 'question', 'content': {'html': '<p>Q.</p>'}, 'solution': {'html': '<p>Réponse C.</p>'}},
]})
page = cl.get(f'/seo/exams/{exam.id}/').content.decode()
check('examen : chaque partie renumérote', '1. Réponse A.' in page and '1. Réponse C.' in page)
check('examen : titre d’une partie repris seulement si elle a un corrigé',
      '>Problème</h3>' in page and 'Exercice 2 (sans corrigé)</h3>' not in page)
old = make('exercise', 'Ancien format', {'version': '2.0', 'blocks': [
    {'id': 'q', 'type': 'question', 'content': {'html': '<p>Énoncé.</p>'}}], 'solution': {'html': '<p>Solution d’ensemble.</p>'}})
check('ancien contenu : solution d’ensemble reprise', 'Solution d’ensemble.' in cl.get(f'/seo/exercises/{old.id}/').content.decode())
lecon = make('lesson', 'Cours', {'sections': [{'id': 's', 'title': 'Définitions', 'content': {'html': '<p>Texte.</p>'}}]})
check('leçon : pas de section « Corrigé »', '>Corrigé<' not in cl.get(f'/seo/lessons/{lecon.id}/').content.decode())

# ── À propos, Contact
for slug, needle in (('a-propos', 'Qui fait Fidni'), ('contact', 'contact@fidni.fr')):
    r = cl.get(f'/api/pages/{slug}/')
    data = r.json() if r.status_code == 200 else {}
    check(f'API page {slug}', r.status_code == 200 and data.get('sections') and data.get('h1'), r.status_code)
    html_page = cl.get(f'/seo/page/{slug}/').content.decode()
    check(f'page pré-remplie {slug} : texte, titre propre, indexable',
          needle in html_page and data.get('title', '') in html_page and 'noindex' not in html_page)
check('API page inconnue : 404', cl.get('/api/pages/inconnue/').status_code == 404)

# ── Sitemap
cache.clear()
xml = cl.get('/sitemap.xml').content.decode()
for path in ('/a-propos', '/contact', '/mentions-legales', '/privacy-policy', '/terms-of-service'):
    check(f'sitemap : {path}', f'<loc>https://fidni.fr{path}</loc>' in xml)
check('sitemap : pas de /concours tant qu’il est vide', '<loc>https://fidni.fr/concours</loc>' not in xml)
nat = make('exam', 'Bac 2024', {'version': '2.1', 'blocks': []})
nat.is_national_exam, nat.national_year = True, 2024
nat.save()
cache.clear()
xml = cl.get('/sitemap.xml').content.decode()
check('sitemap : Bac national par année', '<loc>https://fidni.fr/exams/nationaux/2024</loc>' in xml
      and '<loc>https://fidni.fr/exams/nationaux</loc>' in xml)

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
