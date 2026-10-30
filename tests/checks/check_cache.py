"""Lenteurs du 30/10/2026 : cache fichier sans tri du dossier à chaque écriture, index des théorèmes en mémoire."""
import os
import sys
import tempfile
import time

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-cache-check.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from config import cache as cache_mod  # noqa: E402
from config.cache import CacheFichier  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


# ── Cache fichier
dossier = tempfile.mkdtemp(prefix='fidni-cache-')
c = CacheFichier(dossier, {'TIMEOUT': 60, 'OPTIONS': {'MAX_ENTRIES': 50}})
CacheFichier._prochain_tri = 0.0
appels = []
orig = c._list_cache_files
c._list_cache_files = lambda: appels.append(1) or orig()
for i in range(30):
    c.set(f'k{i}', i)
check('le dossier n’est listé qu’au premier tri, pas à chaque écriture', len(appels) <= 2, len(appels))
check('les valeurs se relisent', c.get('k7') == 7 and c.get('k29') == 29)

for i in range(10):
    c.set(f'court{i}', i, 1)
time.sleep(1.2)
n = c.purger_expires()
check('le tri supprime les fichiers expirés', n == 10 and c.get('court3') is None and c.get('k3') == 3, n)

CacheFichier._prochain_tri = 0.0
for i in range(60):
    c.set(f'plein{i}', i)
CacheFichier._prochain_tri = 0.0
c.set('declencheur', 1)
check('au-delà de MAX_ENTRIES, la règle de Django s’applique encore', len(orig()) < 62, len(orig()))
check('le prochain tri est repoussé de TRI_SECONDES', CacheFichier._prochain_tri > time.monotonic() + cache_mod.TRI_SECONDES - 5)

# ── Index des théorèmes
from django.core.cache import cache  # noqa: E402
from apps.caracteristics import theoremes  # noqa: E402
from apps.caracteristics.models import Theorem  # noqa: E402

theoremes.oublier()
Theorem.objects.create(name='Théorème de test du cache')
idx = theoremes.index()
lectures = []
orig_get = cache.get
cache.get = lambda *a, **k: lectures.append(1) or orig_get(*a, **k)
for _ in range(500):
    theoremes.index()
cache.get = orig_get
check('index() ne relit pas le cache à chaque appel', len(lectures) == 0, len(lectures))
check('l’index contient la base', 'théorème de test du cache' in idx)
Theorem.objects.create(name='Théorème ajouté ensuite')
theoremes.oublier()
check('oublier() vide aussi la copie en mémoire', 'théorème ajouté ensuite' in theoremes.index())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
