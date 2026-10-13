"""Pilotage › Quiz : écrire les questions d'un chapitre (brouillon), mettre en ligne, visible des élèves."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-quiz-admin.sqlite3')
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
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.skilliq.models import SkillQuestion  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


admin = User.objects.create_superuser('chef', 'chef@x.fr', 'Motdepasse-solide-42')
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
level = ClassLevel.objects.get(name='2ème Bac SM')
chapter = Chapter.objects.filter(class_levels=level).first()
cl, el = APIClient(), APIClient()
cl.force_authenticate(admin)
el.force_authenticate(eleve)
base = f'/api/pilotage/quiz/chapitre/{chapter.pk}/'
# Un quiz = (chapitre, niveau) depuis le 13/10/2026 : l'administrateur précise le niveau, l'élève a le sien.
N = f'?niveau={level.pk}'
eleve.profile.class_level = level
eleve.profile.save()

check('réservé aux administrateurs', el.get('/api/pilotage/quiz/').status_code == 403
      and el.post(base, {}, format='json').status_code == 403)
r = cl.get('/api/pilotage/quiz/', {'niveau': level.pk})
row = next((x for x in r.data if x['id'] == chapter.pk), None) if r.status_code == 200 else None
check('chapitres du niveau, quiz vide', row is not None and row['total'] == 0 and row['en_ligne'] == 0, r.status_code)

Q = {'question': 'Combien vaut $\\lim_{x \\to 0} \\frac{\\sin x}{x}$ ?', 'options': ['$0$', '$1$', '$+\\infty$', 'Elle n’existe pas'],
     'correct_answer': 1, 'difficulty': 'easy', 'explanation': 'Limite usuelle.'}
r = cl.post(base + N, Q, format='json')
check('question créée en brouillon', r.status_code == 201 and r.data['en_ligne'] is False, (r.status_code, r.data))
qid = r.data.get('id')
check('réponse vide refusée', cl.post(base + N, {**Q, 'options': ['a', '', 'c']}, format='json').status_code == 400)
check('bonne réponse hors liste refusée', cl.post(base + N, {**Q, 'correct_answer': 7}, format='json').status_code == 400)
check('réponses identiques refusées', cl.post(base + N, {**Q, 'options': ['a', 'a']}, format='json').status_code == 400)
check('question vide refusée', cl.post(base + N, {**Q, 'question': '  '}, format='json').status_code == 400)

r = el.get('/api/skill-assessments/available/')
check('brouillon : invisible des élèves', r.status_code == 200 and str(chapter.pk) not in r.data, r.data)
check('brouillon : le quiz ne se lance pas', el.get(f'/api/skill-assessments/quiz/{chapter.pk}/').status_code == 404)

r = cl.post(base + 'publier/' + N, {'en_ligne': True}, format='json')
check('mise en ligne refusée sous 5 questions', r.status_code == 400, r.status_code)
for i in range(5):
    cl.post(base + N, {**Q, 'question': f'Question {i} : $x^{i}$ ?'}, format='json')
r = cl.post(base + 'publier/' + N, {'en_ligne': True}, format='json')
check('mise en ligne (6 questions)', r.status_code == 200 and r.data['questions'] == 6, (r.status_code, r.data))
r = el.get('/api/skill-assessments/available/')
check('en ligne : visible des élèves', r.data.get(str(chapter.pk)) == 6, r.data)
r = el.get(f'/api/skill-assessments/quiz/{chapter.pk}/')
check('en ligne : quiz lancé, sans la bonne réponse', r.status_code == 200 and len(r.data['questions']) == 6
      and 'correct_answer' not in r.data['questions'][0], r.status_code)

r = cl.patch(f'/api/pilotage/quiz/question/{qid}/', {'correct_answer': 3}, format='json')
check('modifier la bonne réponse seule', r.status_code == 200 and SkillQuestion.objects.get(pk=qid).correct_answer == 3, r.data)
r = cl.patch(f'/api/pilotage/quiz/question/{qid}/', {'options': ['x', 'y']}, format='json')
check('moins de réponses que l’indice de la bonne : refusé', r.status_code == 400, r.status_code)
r = cl.patch(f'/api/pilotage/quiz/question/{qid}/', {'en_ligne': False}, format='json')
check('une question retirée seule', r.status_code == 200 and el.get('/api/skill-assessments/available/').data.get(str(chapter.pk)) == 5)
check('supprimer une question', cl.delete(f'/api/pilotage/quiz/question/{qid}/').status_code == 204
      and not SkillQuestion.objects.filter(pk=qid).exists())
r = cl.post(base + 'publier/' + N, {'en_ligne': False}, format='json')
check('quiz retiré : plus visible', r.status_code == 200 and str(chapter.pk) not in el.get('/api/skill-assessments/available/').data)
r = cl.get(base + N)
check('détail : chapitre, niveaux, questions', r.status_code == 200 and r.data['chapitre']['id'] == chapter.pk
      and len(r.data['questions']) == 5 and r.data['min_en_ligne'] == 5, r.status_code)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
