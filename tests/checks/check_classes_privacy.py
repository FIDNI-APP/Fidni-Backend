"""Classes : confidentialité (un élève ne voit ni les e-mails, ni la liste, ni les stats de ses camarades)
et suivi d'un TD par le prof (élèves × exercices, questions à revoir, élèves qui ont fini, questions
les plus ratées)."""
import json
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-classes-privacy.sqlite3')
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
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def emails_in(data):
    """Toutes les adresses présentes dans une réponse, où qu'elles soient."""
    return '@' in json.dumps(data, default=str)


level = ClassLevel.objects.get(name='2ème Bac SM')
maths = Subject.objects.get(name='Mathématiques')
prof = User.objects.create_user('prof', 'prof@x.fr', 'Motdepasse-solide-42', first_name='Mme', last_name='Alaoui')
prof.profile.user_type = 'teacher'
prof.profile.save()
alice = User.objects.create_user('alice', 'alice@x.fr', 'Motdepasse-solide-42', first_name='Alice', last_name='Benali')
bob = User.objects.create_user('bob', 'bob@x.fr', 'Motdepasse-solide-42')
carol = User.objects.create_user('carol', 'carol@x.fr', 'Motdepasse-solide-42')  # pas dans la classe
ct = ContentType.objects.get_for_model(Content)


def client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


P, A, B, C = client(prof), client(alice), client(bob), client(carol)

# ── La classe : créée par le prof, une matière, deux élèves
r = P.post('/api/classrooms/', {'name': '2 Bac SM 1', 'class_level_id': level.id}, format='json')
check('le prof crée sa classe', r.status_code == 201, r.data)
cid, code = r.data['id'], r.data['join_code']
r = P.post(f'/api/classrooms/{cid}/subjects/', {'subject_id': maths.id}, format='json')
check('le prof ajoute une matière (il voit son e-mail)', r.status_code == 201 and r.data['teacher']['email'] == 'prof@x.fr', r.data)
r = A.post('/api/classrooms/join/', {'code': code}, format='json')
check('un élève rejoint : aucune adresse dans la réponse', r.status_code == 201 and not emails_in(r.data), r.data)
B.post('/api/classrooms/join/', {'code': code}, format='json')

# ── Ce que voit un élève
r = A.get(f'/api/classrooms/{cid}/')
check('élève : la classe sans aucun e-mail (ni du prof)', r.status_code == 200 and not emails_in(r.data)
      and r.data['student_count'] == 2 and not r.data['is_owner'], r.data)
r = A.get('/api/classrooms/')
rows = r.data['results'] if isinstance(r.data, dict) else r.data
check('élève : liste de ses classes sans e-mail', len(rows) == 1 and not emails_in(rows), rows)
r = A.get(f'/api/classrooms/{cid}/members/')
check('élève : seulement sa propre ligne dans les membres, sans e-mail',
      r.status_code == 200 and [m['student']['username'] for m in r.data] == ['alice'] and not emails_in(r.data), r.data)
r = A.get(f'/api/classrooms/{cid}/roster-stats/')
check('élève : seulement sa propre carte de stats', r.status_code == 200
      and [s['student']['username'] for s in r.data['students']] == ['alice'], r.data)
check('élève : pas les stats d’un camarade', A.get(f'/api/classrooms/{cid}/student-stats/?student_id={bob.id}').status_code == 403)
check('élève : ses propres stats', A.get(f'/api/classrooms/{cid}/student-stats/').status_code == 200)

# ── Ce que voit le prof
r = P.get(f'/api/classrooms/{cid}/members/')
check('prof : tous ses élèves, avec leur e-mail', r.status_code == 200
      and sorted((m['student']['username'], m['student']['email']) for m in r.data)
      == [('alice', 'alice@x.fr'), ('bob', 'bob@x.fr')], r.data)
r = P.get(f'/api/classrooms/{cid}/')
check('prof : sa classe avec les e-mails', r.data['owner']['email'] == 'prof@x.fr'
      and r.data['subjects'][0]['teacher']['email'] == 'prof@x.fr', r.data)
r = P.get(f'/api/classrooms/{cid}/roster-stats/')
check('prof : la carte de chaque élève', sorted(s['student']['username'] for s in r.data['students']) == ['alice', 'bob'], r.data)
check('prof : les stats d’un élève de sa classe', P.get(f'/api/classrooms/{cid}/student-stats/?student_id={bob.id}').status_code == 200)
check('prof : pas celles d’un inconnu', P.get(f'/api/classrooms/{cid}/student-stats/?student_id={carol.id}').status_code == 403)
check('matière invalide : 400 (et pas une erreur serveur)',
      P.get(f'/api/classrooms/{cid}/roster-stats/?subject_id=x').status_code == 400
      and A.get(f'/api/classrooms/{cid}/student-stats/?subject_id=x').status_code == 400)

# ── Hors de la classe
check('inconnu : pas la classe', C.get(f'/api/classrooms/{cid}/').status_code == 404)
check('inconnu : pas les membres', C.get(f'/api/classrooms/{cid}/members/').status_code == 404)
check('inconnu : pas les stats', C.get(f'/api/classrooms/{cid}/roster-stats/').status_code == 403)


# ── TD et suivi par le prof
def exo(title, blocks):
    c = Content.objects.create(type='exercise', title=title, author=prof, subject=maths,
                               json_content={'version': '2.1', 'blocks': blocks})
    c.class_levels.add(level)
    return c


def q(qid, subs=None):
    b = {'id': qid, 'type': 'question', 'content': {'type': 'text', 'html': 'Q'}}
    if subs:
        b['subQuestions'] = [{'id': s, 'content': {'type': 'text', 'html': 'S'}} for s in subs]
    return b


ex1 = exo('Limites', [q('q1'), q('q2'), q('q3')])
ex2 = exo('Suites', [q('q1', ['a', 'b'])])
r = P.post(f'/api/classrooms/{cid}/td-lists/', {'title': 'TD 1', 'subject_id': maths.id}, format='json')
check('le prof crée un TD', r.status_code == 201, r.data)
td = r.data['id']
for ex in (ex1, ex2):
    P.post(f'/api/classrooms/{cid}/td-lists/{td}/items/', {'content_id': ex.id}, format='json')


def done(user, ex, st):
    Complete.objects.create(user=user, content_type=ct, object_id=str(ex.id), status=st)


def assess(user, ex, path, st):
    QuestionProgress.objects.create(user=user, content_type=ct, object_id=ex.id, question_path=path, status=st)


# alice a tout réussi (une question d'abord à revoir) ; bob a raté ex1 et commencé ex2 ;
# carol, hors de la classe, ne compte pas.
done(alice, ex1, 'success')
done(alice, ex2, 'success')
assess(alice, ex1, 'q2', 'review')
done(bob, ex1, 'review')
assess(bob, ex1, 'q2', 'review')
assess(bob, ex1, 'q3', 'failed')
assess(bob, ex2, 'q1.b', 'review')
assess(bob, ex2, 'q1.a', 'success')
assess(carol, ex1, 'q1', 'review')
done(carol, ex1, 'success')
done(carol, ex2, 'success')

r = P.get(f'/api/classrooms/{cid}/td-lists/{td}/suivi/')
s = r.data
check('suivi : répond au prof', r.status_code == 200, r.status_code)
check('suivi : élèves de la classe (nom complet)', [(x['username'], x['full_name']) for x in s['students']]
      == [('alice', 'Alice Benali'), ('bob', '')], s['students'])
check('suivi : exercices du TD dans l’ordre', [(x['object_id'], x['type'], x['title']) for x in s['items']]
      == [(ex1.id, 'exercise', 'Limites'), (ex2.id, 'exercise', 'Suites')], s['items'])
cells = s['cells']
a1, a2 = cells[str(alice.id)][str(ex1.id)], cells[str(alice.id)][str(ex2.id)]
b1, b2 = cells[str(bob.id)][str(ex1.id)], cells[str(bob.id)][str(ex2.id)]
check('suivi : statuts (réussi / à revoir / rien)', (a1['status'], a2['status'], b1['status'], b2['status'])
      == ('success', 'success', 'review', None), cells)
check('suivi : questions à revoir par exercice', (a1['review_questions'], a2['review_questions'], b1['review_questions'],
                                                   b2['review_questions']) == (1, 0, 2, 1), cells)
check('suivi : date de dernière activité', all(x['at'] for x in (a1, a2, b1, b2)), cells)
check('suivi : élèves qui ont tout réussi', s['summary'] == {'finished': 1, 'total': 2}, s['summary'])
check('suivi : questions les plus ratées (hors classe ignorés), libellés de la page',
      [(h['object_id'], h['question_path'], h['label'], h['review_count']) for h in s['hardest']]
      == [(ex1.id, 'q2', 'Q2', 2), (ex1.id, 'q3', 'Q3', 1), (ex2.id, 'q1.b', 'Q1b', 1)]
      and s['hardest'][0]['title'] == 'Limites', s['hardest'])
check('suivi : refusé à un élève', A.get(f'/api/classrooms/{cid}/td-lists/{td}/suivi/').status_code == 403)
check('suivi : refusé à un inconnu', C.get(f'/api/classrooms/{cid}/td-lists/{td}/suivi/').status_code == 403)

# ── Avancement sur la carte du TD : la classe pour le prof, le sien pour l'élève
td2 = P.post(f'/api/classrooms/{cid}/td-lists/', {'title': 'TD 2 (vide)'}, format='json').data['id']
r = P.get(f'/api/classrooms/{cid}/td-lists/')
rows = r.data['results'] if isinstance(r.data, dict) else r.data
by_td = {x['id']: x for x in rows}
check('TD (prof) : élèves qui ont fini, matière filtrable', by_td[td]['class_progress'] == {'finished': 1, 'total': 2}
      and by_td[td]['subject'] == maths.id and by_td[td]['subject_name'] == maths.name, by_td[td])
check('TD vide (prof) : personne n’a fini, sans matière', by_td[td2]['class_progress'] == {'finished': 0, 'total': 2}
      and by_td[td2]['subject'] is None, by_td[td2])
P.delete(f'/api/classrooms/{cid}/td-lists/{td2}/')
r = A.get(f'/api/classrooms/{cid}/td-lists/')
rows = r.data['results'] if isinstance(r.data, dict) else r.data
check('TD (élève) : son avancement, pas celui de la classe', rows[0]['class_progress'] is None
      and rows[0]['progress'] == {'completed': 2, 'total': 2}, rows[0])
r = B.get(f'/api/classrooms/{cid}/td-lists/{td}/')
check('TD (autre élève) : son propre avancement', r.data['progress'] == {'completed': 0, 'total': 2}
      and r.data['class_progress'] is None, r.data)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
