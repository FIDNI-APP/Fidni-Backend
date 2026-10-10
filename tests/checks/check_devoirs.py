"""« Mon prochain DS » (apps/interactions/devoirs.py) : annonce d'un DS, plan de révision ciblé
(chapitres les plus fragiles d'abord, exercices « Pour toi », quiz), DS blanc, préparation, note."""
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-devoirs.sqlite3')
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
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress, UpcomingTest  # noqa: E402
from apps.skilliq.models import SkillAssessment, SkillQuestion  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


author = User.objects.create_user('Fidni', 'f@x.fr', None)
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
autre_eleve = User.objects.create_user('autre', 'a@x.fr', 'Motdepasse-solide-42')
sm = ClassLevel.objects.get(name='2ème Bac SM')
eleve.profile.class_level = sm
eleve.profile.save()
lim = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
der = Chapter.objects.filter(name__startswith='Dérivation', class_levels=sm).first()
suites = Chapter.objects.filter(class_levels=sm, name__icontains='suite').exclude(id__in=[lim.id, der.id]).first() \
    or Chapter.objects.filter(class_levels=sm).exclude(id__in=[lim.id, der.id]).first()
maths = lim.subject
ct = ContentType.objects.get_for_model(Content)


def q(qid, skills, seconds=None):
    meta = {'skills': skills}
    if seconds:
        meta['expected_seconds'] = seconds
    return {'id': qid, 'type': 'question', 'content': {'html': '<p>?</p>'}, 'meta': meta}


def make(title, chapters, blocks, difficulty='medium'):
    c = Content.objects.create(type='exercise', title=title, author=author, difficulty=difficulty,
                               json_content={'version': '2.1', 'blocks': blocks})
    c.class_levels.set([sm])
    c.chapters.set(chapters)
    return c


def assess(c, statuses):
    for path, st in statuses.items():
        QuestionProgress.objects.create(user=eleve, content_type=ct, object_id=c.id, question_path=path, status=st)


# Limites : bien maîtrisé. Dérivation : fragile. Suites : jamais travaillé (quiz disponible).
lim1 = make('Limites 1', [lim], [q('q1', ['tvi']), q('q2', ['tvi']), q('q3', ['tvi'])])
lim2 = make('Limites 2 (pas encore ouvert)', [lim], [q('q1', ['tvi'], 600), q('q2', ['tvi'], 900)])
der1 = make('Dérivation 1', [der], [q('q1', ['derivee']), q('q2', ['derivee']), q('q3', ['derivee'])])
der2 = make('Dérivation 2 (pas encore ouvert)', [der], [q('q1', [])], difficulty='hard')
der3 = make('Dérivation 3 facile', [der], [q('q1', [])], difficulty='easy')
sui1 = make('Suites 1', [suites], [q('q1', [])])
hors = make('Hors programme du DS', [Chapter.objects.filter(class_levels=sm).exclude(id__in=[lim.id, der.id, suites.id]).first()], [q('q1', [])])
assess(lim1, {'q1': 'success', 'q2': 'success', 'q3': 'success'})
Complete.objects.create(user=eleve, content_type=ct, object_id=str(lim1.id), status='success')
assess(der1, {'q1': 'review', 'q2': 'failed', 'q3': 'success'})
Complete.objects.create(user=eleve, content_type=ct, object_id=str(der1.id), status='review')
SkillQuestion.objects.create(chapter=suites, question='?', options=['a', 'b'], correct_answer=0)

c = APIClient()
check('visiteur : refusé', c.get('/api/devoirs/').status_code in (401, 403))
c.force_authenticate(eleve)
today = timezone.localdate()

# ── Annonce
bad = c.post('/api/devoirs/', {'subject_id': maths.id, 'date': (today + timedelta(days=3)).isoformat(), 'chapter_ids': []}, format='json')
check('sans chapitre : refusé', bad.status_code == 400 and 'chapter_ids' in bad.data, bad.data)
r = c.post('/api/devoirs/', {'kind': 'ds', 'subject_id': maths.id, 'date': (today + timedelta(days=3)).isoformat(),
                             'chapter_ids': [lim.id, der.id, suites.id]}, format='json')
check('DS annoncé', r.status_code == 201 and r.data['days_left'] == 3 and r.data['subject']['name'] == maths.name
      and len(r.data['chapters']) == 3, r.data)
test_id = r.data['id']
check('niveau pris du profil', UpcomingTest.objects.get(id=test_id).class_level_id == sm.id)
far = c.post('/api/devoirs/', {'subject_id': maths.id, 'date': (today + timedelta(days=500)).isoformat(), 'chapter_ids': [lim.id]}, format='json')
check('date absurde : refusée', far.status_code == 400 and 'date' in far.data, far.data)

# ── Plan
r = c.get(f'/api/devoirs/{test_id}/plan/')
check('plan', r.status_code == 200, r.status_code)
p = r.data
order = [x['id'] for x in p['chapters']]
check('chapitres : le plus fragile d’abord, le maîtrisé en dernier', order[0] == der.id and order[-1] == lim.id, order)
by_id = {x['id']: x for x in p['chapters']}
check('même maîtrise que Ma progression', by_id[lim.id]['mastery'] == 100 and by_id[der.id]['status'] == 'weak'
      and by_id[suites.id]['status'] == 'todo' and by_id[suites.id]['quiz_ready'], [(x['name'], x['status'], x['mastery']) for x in p['chapters']])
check('« S’entraîner » : page du chapitre à son niveau', by_id[lim.id]['hub_url'] == '/exercises/niveau/2eme-bac-sm/limites-et-continuite'
      and all(x['hub_url'] for x in p['chapters']), [x['hub_url'] for x in p['chapters']])
check('prêt à : moyenne des chapitres évalués', p['readiness'] == round((100 + by_id[der.id]['mastery']) / 2), p['readiness'])
ex_ids = [x['id'] for x in p['exercises']]
check('exercices pour toi : ceux des chapitres du DS, jamais déjà réussis', lim1.id not in ex_ids and hors.id not in ex_ids
      and {der2.id, lim2.id, sui1.id} <= set(ex_ids), [x['title'] for x in p['exercises']])
check('exercices pour toi : « à retravailler » en tête', p['exercises'][0]['id'] == der1.id and p['exercises'][0]['reason'] == 'À retravailler',
      p['exercises'][:2])
mock = p['mock']
mock_ids = [x['id'] for x in mock['exercises']]
check('DS blanc : 3 exercices, un par chapitre, le plus fragile d’abord', len(mock_ids) == 3
      and mock_ids[0] in (der2.id, der3.id) and sui1.id in mock_ids and lim2.id in mock_ids, [x['title'] for x in mock['exercises']])
check('DS blanc : pas encore ouvert et plutôt moyen/difficile', mock_ids[0] == der2.id, [x['title'] for x in mock['exercises']])
check('DS blanc : durée (temps cible, sinon difficulté)', next(x for x in mock['exercises'] if x['id'] == lim2.id)['minutes'] == 25
      and next(x for x in mock['exercises'] if x['id'] == der2.id)['minutes'] == 30 and mock['minutes'] == 25 + 30 + 20, mock)
check('DS blanc : pas d’énoncé dans le plan (léger)', 'structure' not in mock['exercises'][0])
prep = p['preparation']
check('préparation au départ', prep['exercises'] == 0 and prep['quizzes'] == 0 and prep['quizzes_total'] == 1 and not prep['mock'], prep)

# ── DS blanc
r = c.get(f'/api/devoirs/{test_id}/ds-blanc/')
check('DS blanc : énoncés', r.status_code == 200 and r.data['exercises'][0]['structure']['blocks'] and r.data['started_at'] is None, r.status_code)
r = c.post(f'/api/devoirs/{test_id}/ds-blanc/', {'action': 'finish', 'seconds': 10}, format='json')
check('terminer avant de commencer : refusé', r.status_code == 400)
r = c.post(f'/api/devoirs/{test_id}/ds-blanc/', {'action': 'start'}, format='json')
frozen = [x['id'] for x in r.data['exercises']]
check('commencer : exercices figés, horloge lancée', r.status_code == 200 and r.data['started_at'] and frozen == mock_ids
      and UpcomingTest.objects.get(id=test_id).mock_ids == mock_ids, r.data.get('started_at'))
# Il travaille un exercice du DS (hors DS blanc) : le DS blanc reste le même.
assess(der2, {'q1': 'success'})
check('DS blanc figé même après d’autres exercices', [x['id'] for x in c.get(f'/api/devoirs/{test_id}/ds-blanc/').data['exercises']] == mock_ids)
r = c.post(f'/api/devoirs/{test_id}/ds-blanc/', {'action': 'finish', 'seconds': 3000}, format='json')
check('terminer : temps enregistré', r.status_code == 200 and r.data['done_at'] and r.data['seconds'] == 3000, r.data.get('seconds'))
r = c.post(f'/api/devoirs/{test_id}/ds-blanc/', {'action': 'new'}, format='json')
new_ids = [x['id'] for x in r.data['exercises']]
check('un autre DS blanc : d’autres exercices', r.status_code == 200 and new_ids and not set(new_ids) & set(mock_ids)
      and r.data['done_at'] is None and r.data['started_at'] is None, [x['title'] for x in r.data['exercises']])
check('action inconnue : refusée', c.post(f'/api/devoirs/{test_id}/ds-blanc/', {'action': 'x'}, format='json').status_code == 400)

# ── Préparation depuis l'annonce : exercices travaillés, quiz passé, DS blanc fait
SkillAssessment.objects.create(user=eleve, chapter=suites, score=6, max_score=10)
UpcomingTest.objects.filter(id=test_id).update(mock_done_at=timezone.now())
prep = c.get(f'/api/devoirs/{test_id}/plan/').data['preparation']
check('préparation : exercice travaillé, quiz passé, DS blanc fait', prep['exercises'] == 1 and prep['quizzes'] == 1 and prep['mock'], prep)
old = UpcomingTest.objects.get(id=test_id)
UpcomingTest.objects.filter(id=test_id).update(created_at=timezone.now() + timedelta(hours=1))
prep = c.get(f'/api/devoirs/{test_id}/plan/').data['preparation']
check('préparation : seulement ce qui suit l’annonce', prep['exercises'] == 0 and prep['quizzes'] == 0, prep)
UpcomingTest.objects.filter(id=test_id).update(created_at=old.created_at)

# ── Liste, rappel de l'accueil, note, autres élèves
past = c.post('/api/devoirs/', {'subject_id': maths.id, 'date': (today - timedelta(days=5)).isoformat(), 'chapter_ids': [lim.id]}, format='json')
later = c.post('/api/devoirs/', {'kind': 'controle', 'subject_id': maths.id, 'date': (today + timedelta(days=20)).isoformat(), 'chapter_ids': [der.id]}, format='json')
r = c.get('/api/devoirs/')
check('liste : à venir (le plus proche d’abord) puis passés', [x['id'] for x in r.data] == [test_id, later.data['id'], past.data['id']], [x['id'] for x in r.data])
fresh = c.get(f'/api/devoirs/{test_id}/plan/').data['readiness']  # a bougé : il a travaillé depuis
check('liste : préparation des DS à venir', r.data[0]['readiness'] == fresh != p['readiness'] and der.name in r.data[0]['weak_chapters']
      and 'readiness' not in r.data[2], r.data[0])
r = c.get('/api/devoirs/prochain/')
check('rappel : le DS dans 3 jours', r.data['test'] and r.data['test']['id'] == test_id, r.data)
r = c.patch(f'/api/devoirs/{past.data["id"]}/', {'grade': 14.5}, format='json')
check('note du DS passé', r.status_code == 200 and float(r.data['grade']) == 14.5, r.data)
check('note > 20 : refusée', c.patch(f'/api/devoirs/{past.data["id"]}/', {'grade': 21}, format='json').status_code == 400)
r = c.patch(f'/api/devoirs/{test_id}/', {'chapter_ids': [lim.id, der.id]}, format='json')
t = UpcomingTest.objects.get(id=test_id)
check('chapitres modifiés : DS blanc à retirer', r.status_code == 200 and t.mock_ids == [] and t.mock_done_at is None, (t.mock_ids, t.mock_done_at))
# Chapitre d'un autre niveau (DS de rattrapage, par ex.) : pas de page à son niveau, l'ancien lien sert.
tcs_ch = Chapter.objects.filter(class_levels__name='Tronc commun Sciences', subject=maths).exclude(class_levels=sm).first()
r = c.post('/api/devoirs/', {'subject_id': maths.id, 'date': (today + timedelta(days=8)).isoformat(),
                             'chapter_ids': [tcs_ch.id, lim.id]}, format='json')
hubs = {x['id']: x['hub_url'] for x in c.get(f'/api/devoirs/{r.data["id"]}/plan/').data['chapters']}
check('chapitre hors de son niveau : pas de hub_url', hubs == {tcs_ch.id: None, lim.id: by_id[lim.id]['hub_url']}, hubs)
c.delete(f'/api/devoirs/{r.data["id"]}/')
c.force_authenticate(autre_eleve)
check('un autre élève ne voit pas ses DS', c.get('/api/devoirs/').data == [] and c.get(f'/api/devoirs/{test_id}/plan/').status_code == 404)
check('rappel : rien pour un élève sans DS', c.get('/api/devoirs/prochain/').data == {'test': None})
c.force_authenticate(eleve)
check('suppression', c.delete(f'/api/devoirs/{later.data["id"]}/').status_code == 204 and not UpcomingTest.objects.filter(id=later.data['id']).exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
