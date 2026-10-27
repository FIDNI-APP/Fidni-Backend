"""Un exercice = un niveau (26/10/2026) : commande dedoubler_pc (original en SM, copie PC/SVT avec sa difficulté)."""
import json
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-dedoubler.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))  # taxonomie réelle
from django.contrib.auth.models import User  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.things.models import Content, Solution  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


author = User.objects.create_user('Fidni', 'f@x.fr', None)
sm = ClassLevel.objects.get(name='2ème Bac SM')
pc = ClassLevel.objects.get(name='2ème Bac PC/SVT')
lim_sm = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
lim_pc = Chapter.objects.filter(name='Limites et continuité', class_levels=pc).first()
check('taxonomie : un chapitre « Limites et continuité » par niveau', lim_sm and lim_pc)

js = {'version': '2.1', 'import': {'cle': 'lim-ex1'}, 'blocks': [
    {'id': 'b1', 'type': 'question', 'content': {'html': '<p>a</p>'}, 'meta': {'difficulty': 'easy'}},
    {'id': 'b2', 'type': 'question', 'content': {'html': '<p>b</p>'},
     'subQuestions': [{'id': 's1', 'content': {'html': '<p>b1</p>'}, 'meta': {'difficulty': 'easy'}}]}]}
partage = Content.objects.create(type='exercise', title='Limites partagées', author=author, json_content=js,
                                 difficulty='easy')
partage.class_levels.set([sm, pc])
partage.chapters.set([c for c in (lim_sm, lim_pc) if c])
Solution.objects.create(content_item=partage, solution_text='sol', author=author)
seul = Content.objects.create(type='exercise', title='SM seul', author=author, json_content={'blocks': []},
                              difficulty='medium')
seul.class_levels.set([sm])

plan = os.path.join(tempfile.gettempdir(), 'plan-dedoubler.json')
with open(plan, 'w', encoding='utf-8') as fh:
    json.dump({str(partage.id): {'difficulte': 'moyen', 'questions': {'b1': 'moyen', 'b2.s1': 'difficile', 'zz': 'facile'}}},
              fh)

avant = Content.objects.count()
call_command('dedoubler_pc', plan=plan, essai=True)
check('essai : rien ne change', Content.objects.count() == avant and partage.class_levels.count() == 2)

call_command('dedoubler_pc', plan=plan)
partage.refresh_from_db()
copie = Content.objects.get(pk=partage.json_content['import']['copie_2pc'])
check('original : 2ème Bac SM seulement, chapitre SM seulement, difficulté inchangée',
      list(partage.class_levels.values_list('name', flat=True)) == ['2ème Bac SM']
      and list(partage.chapters.all()) == [lim_sm] and partage.difficulty == 'easy'
      and partage.json_content['blocks'][0]['meta']['difficulty'] == 'easy')
check('copie : 2ème Bac PC/SVT seulement, chapitre PC, difficulté du plan (contenu et questions)',
      list(copie.class_levels.values_list('name', flat=True)) == ['2ème Bac PC/SVT']
      and list(copie.chapters.all()) == [lim_pc] and copie.difficulty == 'medium'
      and copie.json_content['blocks'][0]['meta']['difficulty'] == 'medium'
      and copie.json_content['blocks'][1]['subQuestions'][0]['meta']['difficulty'] == 'hard')
check('copie : clé propre, lien vers l’original, solution recopiée, autre numéro',
      copie.json_content['import']['cle'] == 'lim-ex1-2pc' and copie.json_content['import']['copie_de'] == partage.id
      and Solution.objects.get(content_item=copie).solution_text == 'sol' and copie.display_id != partage.display_id)
attendu = [c.id for c in {lim_sm, lim_pc} if c and not c.class_levels.filter(pk=sm.pk).exists()]
check('réversible : chapitres retirés de l’original (ceux qui ne sont pas aussi de SM) notés', partage.json_content['import']['chapitres_pc_retires'] == attendu, (partage.json_content['import'], attendu))
check('un contenu d’un seul niveau n’est pas touché', seul.class_levels.count() == 1 and not Content.objects.filter(
    json_content__import__copie_de=seul.id).exists())
n = Content.objects.count()
try:
    call_command('dedoubler_pc', plan=plan)
    relance = True
except CommandError:
    relance = True
check('relancer ne crée pas de seconde copie (plus rien à dédoubler)', relance and Content.objects.count() == n)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
