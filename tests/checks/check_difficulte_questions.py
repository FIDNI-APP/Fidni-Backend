"""Difficulté par question (07/11/2026) : une question peut être « très difficile » (very_hard) dans un contenu moyen.

On vérifie sur une base SQLite jetable : le niveau est accepté pour une question et refusé pour une fiche ; le label d'un
examen compte « très difficile » comme « difficile » ; les statistiques (maîtrise, objectifs) gardent trois niveaux ;
l'API d'un contenu donne bien la difficulté de chaque question à l'élève, et l'enregistrement la conserve.
"""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-difficulte-questions.sqlite3')
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

from apps.things import importing  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.things.question_index import question_levels  # noqa: E402
from apps.users.my_stats import _questions_full  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAUX ') + name + (f' — {detail}' if detail and not ok else ''))


def q(difficulte, points=5, **kw):
    return {'type': 'question', 'html': '<p>Question.</p>', 'points': points, 'difficulte': difficulte, 'theoremes': [],
            'solution': '<p>Solution.</p>', **kw}


def examen(*questions):
    return {'format': importing.FORMAT, 'cle': 'examen-test', 'type': 'examen', 'titre': 'Examen de test',
            'difficulte': 'moyen', 'blocs': [{'type': 'partie', 'titre': 'Exercice 1'}, *questions]}


# ---------------------------------------------------------------- import
meta = importing._meta({'difficulte': 'très difficile', 'theoremes': []})
check('import : « très difficile » devient very_hard sur une question', meta.get('difficulty') == 'very_hard', meta)
fiche_ok = examen(q('très difficile'), q('facile'))
e_ok, _, _ = importing.validate(fiche_ok)
check('import : question « très difficile » acceptée', not any('difficulte' in x for x in e_ok), e_ok)
e_inconnu, _, _ = importing.validate(examen(q('impossible')))
check('import : difficulté inconnue d’une question refusée', any('difficulte' in x for x in e_inconnu), e_inconnu)
e_fiche, _, _ = importing.validate({**fiche_ok, 'difficulte': 'très difficile'})
check('import : une fiche entière ne peut pas être « très difficile »', any(x.startswith('difficulte') for x in e_fiche), e_fiche)

# ---------------------------------------------------------------- label d'un examen
check('label : 40 % des points en très difficile → difficile', importing.exam_difficulty(examen(q('très difficile', 8), q('moyen', 12))) == 'hard')
check('label : 40 % partagés entre difficile et très difficile → difficile',
      importing.exam_difficulty(examen(q('très difficile', 4), q('difficile', 4), q('moyen', 12))) == 'hard')
check('label : une seule question très difficile sur 20 points → reste moyen',
      importing.exam_difficulty(examen(q('très difficile', 1), q('moyen', 19))) == 'medium')

# ---------------------------------------------------------------- statistiques
structure = {'version': '2.1', 'blocks': [
    {'id': 'a', 'type': 'question', 'points': 2, 'meta': {'difficulty': 'very_hard'}},
    {'id': 'b', 'type': 'question', 'points': 1, 'meta': {'difficulty': 'easy'}},
    {'id': 'c', 'type': 'question', 'meta': {'difficulty': 'very_hard'}, 'subQuestions': [
        {'id': 's1', 'points': 1}, {'id': 's2', 'points': 1, 'meta': {'difficulty': 'medium'}}]},
    {'id': 'd', 'type': 'question', 'points': 1, 'meta': {'difficulty': 'nimporte'}},
]}
niveaux = {path: level for path, _p, _t, level in _questions_full(structure)}
check('stats : very_hard compte comme hard', niveaux['a'] == 'hard', niveaux)
check('stats : autres niveaux inchangés, valeur inconnue ignorée', niveaux['b'] == 'easy' and niveaux['d'] is None, niveaux)
check('stats : une sous-question hérite de sa question, ou garde son niveau', niveaux['c.s1'] == 'hard' and niveaux['c.s2'] == 'medium', niveaux)

# ---------------------------------------------------------------- API et enregistrement
auteur = User.objects.create_user('auteur_diff', 'a@x.fr', 'x', is_staff=True)
c = Content.objects.create(type='exercise', title='Exercice moyen', author=auteur, difficulty='medium', json_content=structure)
check('index des questions : les statistiques lisent le niveau ramené à hard', question_levels([c])[c.id]['a'] == 'hard')
eleve = User.objects.create_user('eleve_diff', 'e@x.fr', 'x')
client = APIClient()
client.force_authenticate(eleve)
r = client.get(f'/api/contents/{c.id}/')
blocs = (r.data.get('structure') or r.data.get('json_content') or {}).get('blocks') or [] if r.status_code == 200 else []
par_id = {b['id']: b for b in blocs}
check('API : l’élève reçoit la difficulté de chaque question', par_id.get('a', {}).get('meta', {}).get('difficulty') == 'very_hard', (r.status_code, list(par_id)))
check('API : la sous-question garde la sienne', par_id.get('c', {}).get('subQuestions', [{}, {}])[1].get('meta', {}).get('difficulty') == 'medium')
check('API : le contenu reste « moyen »', r.status_code == 200 and r.data.get('difficulty') == 'medium', r.status_code)

sys.exit(0 if all(results) else 1)
