"""Tableau de bord de l'accueil (/api/dashboard/overview/) : chiffres exacts sur des données connues."""
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
from apps.interactions.models import Complete, QuestionProgress  # noqa: E402
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
# b : 2 questions échouées il y a 10 jours (semaine précédente), marqué « à revoir »
assess(b, 'q1', 'failed', 10)
assess(b, 'q2', 'review', 10)
Complete.objects.create(user=u, content_type=ct, object_id=str(b.id), status='review')

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
check('à revoir : « À revoir »', [x['title'] for x in d['review']] == ['À revoir'], d['review'])
lim = next(c for c in d['chapters'] if c['name'] == 'Limites et continuité')
check('chapitre : 4 questions, 25 % réussies, 2 contenus', (lim['assessed'], lim['success_pct'], lim['contents']) == (4, 25, 2), lim)
check('couverture : 1 chapitre sur 14', d['coverage'] == {'total': 14, 'touched': 1}, d['coverage'])
check('notions faibles avec libellés (arctan 0 %, tvi 50 %)',
      [(n['slug'], n['label'], n['mastery_pct']) for n in d['weak_notions']]
      == [('arctan', 'Fonction arc tangente', 0), ('tvi', 'Théorème des valeurs intermédiaires', 50)], d['weak_notions'])
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

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
