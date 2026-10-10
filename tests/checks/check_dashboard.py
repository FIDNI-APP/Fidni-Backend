"""Tableau de bord de l'accueil (/api/dashboard/overview/) : chiffres exacts sur des données connues ;
« Pour toi » de l'accueil (/api/dashboard/recommended/) ; quiz Skill IQ repassé (score précédent)."""
import os
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-dashboard.sqlite3')
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
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Subject  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress, UpcomingTest  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
limites = Chapter.objects.get(name='Limites et continuité')
u = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
u.profile.class_level = level
u.profile.save()
ct = ContentType.objects.get_for_model(Content)


def exo(title, n_questions, skills):
    blocks = [{'id': f'q{i}', 'type': 'question', 'content': {'type': 'text', 'html': 'Q'},
               'meta': {'skills': skills}} for i in range(1, n_questions + 1)]
    c = Content.objects.create(type='exercise', title=title, author=u, subject=subject,
                               json_content={'version': '2.1', 'blocks': blocks})
    c.class_levels.add(level)
    c.chapters.add(limites)
    return c


a = exo('Commencé', 4, ['tvi'])
b = exo('À revoir', 2, ['arctan'])
now = timezone.now()


def assess(c, path, status, days_ago):
    q = QuestionProgress.objects.create(user=u, content_type=ct, object_id=c.id, question_path=path, status=status)
    QuestionProgress.objects.filter(pk=q.pk).update(created_at=now - timedelta(days=days_ago),
                                                    assessed_at=now - timedelta(days=days_ago))


# a : 2 questions sur 4 évaluées (une réussie), aujourd'hui et hier → série de 2 jours
assess(a, 'q1', 'success', 0)
assess(a, 'q2', 'failed', 1)
# b : 2 questions échouées il y a 10 jours (semaine précédente), marqué « à revoir » il y a 5 jours
assess(b, 'q1', 'failed', 10)
assess(b, 'q2', 'review', 10)
Complete.objects.create(user=u, content_type=ct, object_id=str(b.id), status='review')
Complete.objects.filter(user=u, object_id=str(b.id)).update(updated_at=now - timedelta(days=5))
# c : marqué « à revoir » il y a 9 jours (le plus ancien) ; d : aujourd'hui (trop tôt pour le refaire)
c_old = exo('Raté il y a 9 jours', 1, [])
d_new = exo('Raté aujourd’hui', 1, [])
Complete.objects.create(user=u, content_type=ct, object_id=str(c_old.id), status='review')
Complete.objects.filter(user=u, object_id=str(c_old.id)).update(updated_at=now - timedelta(days=9))
Complete.objects.create(user=u, content_type=ct, object_id=str(d_new.id), status='review')

cl = APIClient()
cl.force_authenticate(u)
cache.clear()
r = cl.get('/api/dashboard/overview/')
d = r.data
check('répond 200', r.status_code == 200, r.status_code)
check('série en cours = 2 jours (aujourd’hui et hier)', d['streak']['current'] == 2, d['streak'])
check('calendrier de 52 semaines, se termine aujourd’hui', len(d['calendar']) == 364
      and d['calendar'][-1]['date'] == timezone.localdate().isoformat(), (len(d['calendar']), d['calendar'][-1]))
check('semaine : 2 questions, 50 % réussies', d['week']['questions'] == 2 and d['week']['success_rate'] == 50, d['week'])
check('semaine précédente : 2 questions, 0 %', d['previous_week']['questions'] == 2 and d['previous_week']['success_rate'] == 0, d['previous_week'])
check('reprendre : « Commencé » 2/4', [(x['title'], x['assessed'], x['total']) for x in d['resume']] == [('Commencé', 2, 4)], d['resume'])
check('à revoir : depuis au moins 2 jours, le plus ancien d’abord, avec « il y a N j »',
      [(x['title'], x['days_ago']) for x in d['review']] == [('Raté il y a 9 jours', 9), ('À revoir', 5)], d['review'])
check('page de niveau des exercices', d['level_hub_url'] == '/exercises/niveau/2eme-bac-sm', d.get('level_hub_url'))
lim = next(c for c in d['chapters'] if c['name'] == 'Limites et continuité')
check('chapitre : 4 questions, 25 % réussies, 4 contenus', (lim['assessed'], lim['success_pct'], lim['contents']) == (4, 25, 4), lim)
check('couverture : 1 chapitre sur 14', d['coverage'] == {'total': 14, 'touched': 1}, d['coverage'])
check('notions faibles avec libellés (arctan 0 %, tvi 50 %)',
      [(n['slug'], n['label'], n['mastery_pct']) for n in d['weak_notions']]
      == [('arctan', 'Fonction arc tangente', 0), ('tvi', 'Théorème des valeurs intermédiaires', 50)], d['weak_notions'])
check('notions faibles : chapitre de la notion (lien vers Ma progression)',
      all(n['chapter_id'] == limites.id for n in d['weak_notions']), d['weak_notions'])
check('un visiteur n’y a pas accès', APIClient().get('/api/dashboard/overview/').status_code in (401, 403))
other = User.objects.create_user('autre', 'o@x.fr', 'Motdepasse-solide-42')
cl2 = APIClient()
cl2.force_authenticate(other)
d2 = cl2.get('/api/dashboard/overview/').data
check('un autre élève ne voit rien des données du premier', d2['totals']['questions'] == 0 and not d2['resume'] and not d2['review'], d2['totals'])

# ── Skill IQ : quiz disponibles, pas de fuite de la réponse, correction après envoi, score au tableau de bord
from apps.skilliq.models import SkillQuestion  # noqa: E402
qs = [SkillQuestion.objects.create(chapter=limites, question=f'Q{i}', options=['a', 'b', 'c'], correct_answer=1,
                                   difficulty='easy', explanation=f'Parce que {i}') for i in range(3)]
cache.clear()
check('Skill IQ : quiz disponibles par chapitre', cl.get('/api/skill-assessments/available/').data == {str(limites.id): 3})
quiz = cl.get(f'/api/skill-assessments/quiz/{limites.id}/').data
check('Skill IQ : la bonne réponse n’est pas dans le quiz', all('correct_answer' not in q for q in quiz['questions']), quiz)
cache.clear()
res = cl.post(f'/api/skill-assessments/submit/{limites.id}/',
              {'answers': {str(qs[0].id): 1, str(qs[1].id): 0, str(qs[2].id): 1}}, format='json').data
check('Skill IQ : score 2/3 et correction détaillée après envoi',
      (res['score'], res['max_score']) == (2, 3) and len(res['correction']) == 3
      and sum(c['is_correct'] for c in res['correction']) == 2 and res['correction'][0]['explanation'].startswith('Parce que'), res)
cache.clear()
lim = next(c for c in cl.get('/api/dashboard/overview/').data['chapters'] if c['name'] == 'Limites et continuité')
check('Skill IQ : score repris au tableau de bord (67 %)', lim['skilliq_pct'] == 67, lim)
check('Skill IQ : premier passage, pas de score précédent', res['previous_score'] is None and res['previous_max'] is None
      and res['attempts'] == 1, res)
check('Skill IQ : page d’exercices du chapitre à son niveau (S’entraîner)',
      res['hub_url'] == '/exercises/niveau/2eme-bac-sm/limites-et-continuite', res.get('hub_url'))
res2 = cl.post(f'/api/skill-assessments/submit/{limites.id}/',
               {'answers': {str(qs[0].id): 1, str(qs[1].id): 1, str(qs[2].id): 1}}, format='json').data
check('Skill IQ refait : score précédent gardé (2/3 → 3/3), 2 passages',
      (res2['score'], res2['previous_score'], res2['previous_max'], res2['attempts']) == (3, 2, 3, 2), res2)
mine = cl.get('/api/skill-assessments/my/').data
again = cl.get(f'/api/skill-assessments/chapter/{limites.id}/').data
check('Skill IQ : score précédent relu (mes quiz, quiz du chapitre)', len(mine) == 1 and mine[0]['previous_score'] == 2
      and mine[0]['attempts'] == 2 and mine[0]['hub_url'] and again['previous_max'] == 3 and again['attempts'] == 2,
      (mine, again))

# Notion travaillée dans un chapitre hors de son programme : pas de lien vers Ma progression.
tcs = ClassLevel.objects.get(name='Tronc commun Sciences')
hors = Chapter.objects.filter(class_levels=tcs).exclude(class_levels=level).first()
x = Content.objects.create(type='exercise', title='Hors programme', author=u, subject=subject,
                           json_content={'version': '2.1', 'blocks': [
                               {'id': f'q{i}', 'type': 'question', 'content': {'type': 'text', 'html': 'Q'},
                                'meta': {'skills': ['notion-hors']}} for i in (1, 2)]})
x.class_levels.add(tcs)
x.chapters.add(hors)
assess(x, 'q1', 'failed', 0)
assess(x, 'q2', 'failed', 0)
cache.clear()
hors_notion = next(n for n in cl.get('/api/dashboard/overview/').data['weak_notions'] if n['slug'] == 'notion-hors')
check('notion hors programme : pas de chapitre', hors_notion['chapter_id'] is None, hors_notion)

# ── « Pour toi » de l'accueil (things/for_you.py) : ni réussis ni autre niveau, « à revoir » gardés,
# raison de chaque choix ; un DS dans les 14 jours : seulement ses chapitres.
derivation = Chapter.objects.filter(name__startswith='Dérivation', class_levels=level).first()
reussi = exo('Déjà réussi', 1, [])
Complete.objects.create(user=u, content_type=ct, object_id=str(reussi.id), status='success')
autre_niveau = Content.objects.create(type='exercise', title='Autre niveau', author=u, subject=subject,
                                      json_content={'version': '2.1', 'blocks': []})
autre_niveau.class_levels.add(tcs)
der_ex = Content.objects.create(type='exercise', title='Dérivation', author=u, subject=subject,
                                json_content={'version': '2.1', 'blocks': []})
der_ex.class_levels.add(level)
der_ex.chapters.add(derivation)
lecon = Content.objects.create(type='lesson', title='Cours limites', author=u, subject=subject,
                               json_content={'version': '2.1', 'blocks': []})
lecon.class_levels.add(level)
lecon.chapters.add(limites)
r = cl.get('/api/dashboard/recommended/')
rec = r.data
ex_ids = [x['id'] for x in rec['exercises']]
check('pour toi : répond, même forme (exercices, leçons, examens, niveau)', r.status_code == 200
      and set(rec) >= {'exercises', 'lessons', 'exams', 'level'} and rec['level'] == '2ème Bac SM', r.status_code)
check('pour toi : jamais un exercice réussi ni d’un autre niveau', reussi.id not in ex_ids and autre_niveau.id not in ex_ids
      and {a.id, b.id, der_ex.id} <= set(ex_ids), [x['title'] for x in rec['exercises']])
check('pour toi : « à revoir » gardé, avec sa raison', next(x for x in rec['exercises'] if x['id'] == b.id)['reason'] == 'À retravailler',
      [(x['title'], x['reason']) for x in rec['exercises']])
check('pour toi : raison sur chaque contenu, leçon du niveau', all('reason' in x for x in rec['exercises'] + rec['lessons'])
      and [x['id'] for x in rec['lessons']] == [lecon.id] and rec['exams'] == [], rec['lessons'])
ds = UpcomingTest.objects.create(user=u, subject=subject, class_level=level, date=timezone.localdate() + timedelta(days=5))
ds.chapters.set([derivation])
rec = cl.get('/api/dashboard/recommended/').data
check('pour toi : DS dans 5 jours → seulement ses chapitres', [(x['id'], x['reason']) for x in rec['exercises']]
      == [(der_ex.id, 'Au programme de ton DS')], [(x['title'], x['reason']) for x in rec['exercises']])
check('pour toi : rien dans les chapitres du DS → le reste du niveau', [x['id'] for x in rec['lessons']] == [lecon.id], rec['lessons'])
# Matières visées sans celle du DS : le DS l'emporte (ses chapitres disent déjà la matière).
physique, _ = Subject.objects.get_or_create(name='Physique-check')
u.profile.target_subjects.set([physique])
rec = cl.get('/api/dashboard/recommended/').data
check('pour toi : DS d’une matière hors de ses matières visées → ses chapitres quand même',
      [(x['id'], x['reason']) for x in rec['exercises']] == [(der_ex.id, 'Au programme de ton DS')],
      [(x['title'], x['reason']) for x in rec['exercises']])
u.profile.target_subjects.clear()
UpcomingTest.objects.filter(id=ds.id).update(date=timezone.localdate() + timedelta(days=20))
rec = cl.get('/api/dashboard/recommended/').data
check('pour toi : DS dans 20 jours → tout le niveau', {a.id, b.id, der_ex.id} <= {x['id'] for x in rec['exercises']},
      [x['title'] for x in rec['exercises']])

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
