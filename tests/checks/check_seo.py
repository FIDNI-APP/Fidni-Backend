"""Pages de contenu pour les moteurs de recherche (config/seo.py) et plan du site."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-seo.sqlite3')
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
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


# index.html de l'application, sans passer par le réseau.
INDEX = ('<!doctype html><html lang="fr"><head><title>Fidni - Accueil</title>'
         '<meta name="title" content="Fidni - Accueil" /><meta name="description" content="Générique" />'
         '<meta name="robots" content="index, follow" /></head><body><div id="root"></div>'
         '<script type="module" src="/assets/app.js"></script></body></html>')
seo._index_cache.update(html=INDEX, at=10 ** 12)

u = User.objects.create_user('auteur', 'a@x.fr', 'x')
level = ClassLevel.objects.get(name='2ème Bac SM')
chapter = Chapter.objects.filter(name='Limites et continuité').first()
subject = Subject.objects.filter(name='Mathématiques').first()
c = Content.objects.create(type='exercise', title='Continuité en 0 de x sin(1/x) <script>', author=u, subject=subject,
                           json_content={'version': '2.1', 'credit': 'M. Haddar, professeur de mathématiques', 'blocks': [
                               {'type': 'context', 'content': {'html': '<p>Soit $f(x) = x\\sin\\left(\\dfrac{1}{x}\\right)$ &amp; f(0) = 0</p>'}},
                               {'type': 'question', 'content': {'html': '<p>Montrer que $f$ est continue en $0$</p>'},
                                'solution': {'html': '<p>SECRET-SOLUTION</p>'}},
                           ], 'import': {'source': {'note': 'NOTE-INTERNE'}}})
c.class_levels.add(level)
c.chapters.add(chapter)

cl = Client()
r = cl.get(f'/seo/exercises/{c.pk}/')
page = r.content.decode()
check('page de contenu : 200 et HTML', r.status_code == 200 and r['Content-Type'].startswith('text/html'), r.status_code)
check('titre propre au contenu', '<title>Continuité en 0 de x sin(1/x) &lt;script&gt; – Exercice corrigé 2ème Bac SM | Fidni</title>' in page, page[:400])
check('description propre au contenu', 'content="Exercice de mathématiques (2ème Bac SM, Limites et continuité)' in page, page[:600])
check('lien canonique', f'<link rel="canonical" href="https://fidni.fr/exercises/{c.pk}" />' in page)
check('données structurées schema.org', '"@type": "LearningResource"' in page)
check('énoncé présent dans #root', 'Montrer que $f$ est continue en $0$' in page and '<div id="root"><div class="fd-prerender"><main' in page)
check('entités décodées puis échappées une seule fois', '&amp; f(0) = 0' in page, page)
check('titre échappé (pas de balise injectée)', '<script>' not in page.split('<script type="module"')[0].replace('<script type="application/ld+json">', ''))
check('solution et note interne absentes', 'SECRET-SOLUTION' not in page and 'NOTE-INTERNE' not in page)
check('crédit affiché', 'Proposé par M. Haddar' in page)
check('le script de l’application est conservé', '/assets/app.js' in page)
r = cl.get(f'/seo/lessons/{c.pk}/')
check('mauvaise section → 404 noindex', r.status_code == 404 and 'content="noindex"' in r.content.decode())
r = cl.get('/seo/exercises/999999/')
check('contenu inexistant → 404', r.status_code == 404)
r = cl.get('/sitemap.xml')
check('plan du site contient le contenu', r.status_code == 200 and f'https://fidni.fr/exercises/{c.pk}' in r.content.decode())

# ---------------------------------------------------------------- IndexNow (aucun envoi réel)
import time  # noqa: E402
from django.db import transaction  # noqa: E402
from config import indexnow  # noqa: E402

check('IndexNow désactivé hors production', not indexnow.enabled())
sent = []
indexnow.submit = lambda urls: sent.append(sorted(urls))  # on intercepte l'envoi
indexnow.DELAY = 0.2
settings.INDEXNOW_ENABLED = True
with transaction.atomic():
    c2 = Content.objects.create(type='lesson', title='Leçon test', author=u, subject=subject, json_content={})
    c.title = 'Titre modifié'
    c.save()
time.sleep(0.8)
check('contenus créés/modifiés annoncés en un seul envoi groupé',
      sent == [[f'https://fidni.fr/exercises/{c.pk}', f'https://fidni.fr/lessons/{c2.pk}']], sent)
p = indexnow.payload(['https://fidni.fr/exercises/1'])
check('requête IndexNow conforme (hôte, clé, fichier de clé)',
      p['host'] == 'fidni.fr' and p['keyLocation'] == f'https://fidni.fr/{settings.INDEXNOW_KEY}.txt'
      and p['urlList'] == ['https://fidni.fr/exercises/1'], p)
key_file = os.path.join(os.path.dirname(BACKEND), 'frontend', 'public', f'{settings.INDEXNOW_KEY}.txt')
check('fichier de clé présent dans frontend/public avec la bonne clé',
      os.path.exists(key_file) and open(key_file).read().strip() == settings.INDEXNOW_KEY, key_file)
settings.INDEXNOW_ENABLED = False

# Accueil et listes pré-remplis
r = cl.get('/seo/page/exercises/')
lp = r.content.decode()
check('liste des exercices : 200, titre ciblé (Maroc)', r.status_code == 200 and '<title>Exercices de maths corrigés' in lp and 'Maroc' in lp, r.status_code)
check('liste : lien vers chaque exercice, rangé par niveau et chapitre',
      f'href="/exercises/{c.pk}"' in lp and '<h2' in lp and '2ème Bac SM' in lp and 'Limites et continuité' in lp)
root = lp.split('<div id="root">')[1]
check('liste : pas de balise injectée ni de solution', '<script>' not in root and 'SECRET-SOLUTION' not in lp)
check('liste : canonique et données structurées', '/exercises" />' in lp and 'rel="canonical"' in lp and '"CollectionPage"' in lp)
r = cl.get('/seo/page/home/')
hp = r.content.decode()
check('accueil : titre ciblé, WebSite + logo', r.status_code == 200 and 'Lycée et Bac au Maroc' in hp and '"WebSite"' in hp
      and 'android-chrome-512x512.png' in hp, r.status_code)
check('accueil : liens vers les listes et les contenus', 'href="/exercises"' in hp and f'href="/exercises/{c.pk}"' in hp)
check('page inconnue : 404', cl.get('/seo/page/inconnue/').status_code == 404)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
