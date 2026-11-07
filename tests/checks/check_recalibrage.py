"""Migration things 0026 : recalibrage de cinq difficultés, seulement si elles n'ont pas été corrigées à la main."""
import importlib
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
DB = os.path.join(tempfile.gettempdir(), 'fidni-recalibrage.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from django.apps import apps as registre  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from apps.things.models import Content  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


auteur = User.objects.create_user('auteur_recal', 'a@example.com', 'x' * 12)
avant = {120: ('exercise', 'hard'), 57: ('exam', 'medium'), 293: ('exam', 'medium'), 16: ('exam', 'hard'),
         191: ('exam', 'easy'),  # déjà corrigé à la main : ne doit pas bouger
         500: ('exercise', 'hard')}  # hors liste
for pk, (kind, diff) in avant.items():
    Content.objects.create(id=pk, type=kind, title=f'Contenu {pk}', difficulty=diff, author=auteur)

m = importlib.import_module('apps.things.migrations.0026_recalibrage_difficulte')
m.forwards(registre, None)
d = dict(Content.objects.values_list('id', 'difficulty'))
check('#120, #57, #293 → Facile', d[120] == d[57] == d[293] == 'easy', d)
check('#16 → Moyen', d[16] == 'medium', d)
check('#191 déjà corrigé à la main : inchangé', d[191] == 'easy', d)
check('contenu hors liste : inchangé', d[500] == 'hard', d)
m.forwards(registre, None)
check('relancée : rien ne bouge', dict(Content.objects.values_list('id', 'difficulty')) == d)
m.backwards(registre, None)
d2 = dict(Content.objects.values_list('id', 'difficulty'))
check('retour arrière : difficultés d’avant', d2[120] == 'hard' and d2[57] == 'medium' and d2[16] == 'hard'
      and d2[191] == 'easy' and d2[500] == 'hard', d2)
print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
