"""Quiz : passage gardé en base (14/10/2026). Un passage commencé est repris ; une question ne se corrige que dans son
passage, sa première réponse est verrouillée ; l'envoi note toutes les questions servies ; la correction du dernier
passage est figée et se rouvre (« Voir mon dernier résultat ») ; un seul passage gardé par quiz et par élève."""
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-quiz-passage.sqlite3')
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
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Theorem  # noqa: E402
from apps.skilliq.models import QuizEnCours, SkillAssessment, SkillQuestion  # noqa: E402
from apps.users.legal import export_user_data  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


sm = ClassLevel.objects.get(name='2ème Bac SM')
lim = Chapter.objects.get(name='Limites et continuité')
suites = Chapter.objects.get(name='Suites numériques')
tvi = Theorem.objects.get(name='Théorème des valeurs intermédiaires (TVI)')


def eleve(nom):
    u = User.objects.create_user(nom, f'{nom}@x.fr', 'Motdepasse-solide-42')
    u.profile.class_level = sm
    u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return u, c


QS = []
for i, diff in enumerate(['easy', 'medium', 'hard', 'easy', 'medium']):
    q = SkillQuestion.objects.create(chapter=lim, class_level=sm, question=f'Question {i} : $x^{i}$ ?',
                                     options=['A', 'B', 'C', 'D'], correct_answer=i % 4, difficulty=diff,
                                     explanation=f'Parce que {i}.')
    q.theorems.add(tvi)
    QS.append(q)
hors = SkillQuestion.objects.create(chapter=suites, class_level=sm, question='Hors quiz', options=['A', 'B'],
                                    correct_answer=1, difficulty='easy', explanation='…')
BON = {q.id: q.correct_answer for q in QS}

u, el = eleve('eleve')
u2, el2 = eleve('autre')
url = f'/api/skill-assessments/quiz/{lim.id}/'

# ── Tirage gardé
r = el.get(url)
ordre = [x['id'] for x in r.data['questions']]
p = QuizEnCours.objects.get(user=u, chapter=lim, class_level=sm)
check('passage gardé en base, dans l’ordre servi', r.status_code == 200 and r.data['reprise'] is False
      and p.questions == ordre and sorted(ordre) == sorted(BON), (r.status_code, p.questions, ordre))
check('jamais la bonne réponse dans le quiz', all('correct_answer' not in x for x in r.data['questions']))
check('commencé : visible dans « en cours »', el.get('/api/skill-assessments/en-cours/').data
      == [{'chapitre': lim.id, 'niveau': sm.id, 'repondues': 0, 'total': 5, 'maj': p.maj.isoformat()}])

# ── Correction d'une question : seulement dans son passage, première réponse verrouillée
v = lambda client, qid, rep, **kw: client.post(f'/api/skill-assessments/verifier/{qid}/', {'answer': rep, **kw},  # noqa: E731
                                               format='json')
check('question hors de son passage : 404 (plus de récupération des bonnes réponses)', v(el, hors.id, 0).status_code == 404)
check('question du passage d’un autre élève : 404', v(el2, ordre[0], 0).status_code == 404)
q0 = SkillQuestion.objects.get(pk=ordre[0])
faux = (q0.correct_answer + 1) % 4
r = v(el, q0.id, faux)
check('correction : bonne réponse, explication, théorèmes', r.status_code == 200 and r.data['is_correct'] is False
      and r.data['correct_answer'] == q0.correct_answer and r.data['explanation'] and r.data['theoremes'] == [tvi.name]
      and r.data['question'] == q0.question and r.data['options'] == q0.options, r.data)
r = v(el, q0.id, q0.correct_answer)
check('première réponse verrouillée : une nouvelle demande renvoie la même correction',
      r.data['your_answer'] == faux and r.data['is_correct'] is False, r.data)
check('réponse hors des choix : 400', v(el, ordre[1], 9).status_code == 400)
QuizEnCours.objects.filter(pk=p.pk).update(debut=timezone.now() - timedelta(minutes=10))
v(el, ordre[1], BON[ordre[1]], temps=100)

# ── Reprise
r = el.get(url)
check('reprise : mêmes questions, corrections déjà vues, temps restant', r.data['reprise'] is True
      and [x['id'] for x in r.data['questions']] == ordre
      and [(x['id'], x['your_answer']) for x in r.data['verifiees']] == [(ordre[0], faux), (ordre[1], BON[ordre[1]])]
      and r.data['restant_secondes'] == r.data['duree_secondes'] - 100, r.data)
check('le temps ne dépasse jamais le temps réel écoulé', (v(el, ordre[2], 0, temps=10 ** 6) and True)
      and QuizEnCours.objects.get(pk=p.pk).temps <= 10 * 60 + 5, QuizEnCours.objects.get(pk=p.pk).temps)

# ── Envoi : toutes les questions servies sont notées
check('identifiant de question invalide : 400', el.post(f'/api/skill-assessments/submit/{lim.id}/',
                                                       {'answers': {'abc': 1}}, format='json').status_code == 400)
partiel = {str(ordre[0]): BON[ordre[0]], str(ordre[3]): BON[ordre[3]]}  # q0 : réponse verrouillée fausse
r = el.post(f'/api/skill-assessments/submit/{lim.id}/', {'answers': partiel, 'time_spent': 99999}, format='json')
justes = {c['id'] for c in r.data['correction'] if c['is_correct']}
check('envoi partiel : toutes les questions comptent (plus de 100 % en n’envoyant que ses bonnes réponses)',
      r.status_code == 200 and len(r.data['correction']) == 5 and r.data['max_score'] == 9
      and justes == {ordre[1], ordre[3]} | ({ordre[2]} if BON[ordre[2]] == 0 else set()), (r.status_code, justes))
check('réponse verrouillée prioritaire sur celle envoyée', r.data['correction'][0]['your_answer'] == faux
      and r.data['correction'][0]['is_correct'] is False)
check('sans réponse : -1, fausse', all(c['your_answer'] == -1 for c in r.data['correction']
                                       if c['id'] not in (ordre[0], ordre[1], ordre[2], ordre[3])))
a = SkillAssessment.objects.get(user=u, chapter=lim, class_level=sm)
check('temps passé borné au temps réel', a.time_spent <= 10 * 60 + 5, a.time_spent)
check('passage clos à l’envoi', not QuizEnCours.objects.filter(user=u).exists()
      and el.get('/api/skill-assessments/en-cours/').data == [])
check('envoi sans passage en cours : 409', el.post(f'/api/skill-assessments/submit/{lim.id}/',
                                                  {'answers': partiel}, format='json').status_code == 409)

# ── Dernier résultat : figé, rouvrable
premier = a.derniere_correction
check('correction figée dans l’ordre servi, avec énoncé et réponses', [c['id'] for c in premier] == ordre
      and all(c['question'] and len(c['options']) == 4 and 'correct_answer' in c for c in premier))
mine = el.get('/api/skill-assessments/my/').data
check('« mes quiz » : correction disponible, sans la charger', mine[0]['a_correction'] is True and 'correction' not in mine[0]
      and 'derniere_correction' not in mine[0])
q0.question, q0.correct_answer = 'Énoncé corrigé', (q0.correct_answer + 2) % 4
q0.save()
SkillQuestion.objects.filter(pk=ordre[4]).delete()
r = el.get(f'/api/skill-assessments/chapter/{lim.id}/')
c0 = r.data['correction'][0]
check('« Voir mon dernier résultat » : la correction telle qu’elle était (question modifiée ou supprimée depuis)',
      r.status_code == 200 and c0['question'] == f'Question {QS.index(next(q for q in QS if q.id == ordre[0]))} : '
      f'$x^{QS.index(next(q for q in QS if q.id == ordre[0]))}$ ?' and len(r.data['correction']) == 5
      and r.data['par_theoreme'] and r.data['score'] == a.score, r.data.get('correction', [None])[0])

# ── Deuxième passage : un seul gardé
r = el.get(url)
check('nouveau passage après l’envoi (4 questions restantes)', r.data['reprise'] is False and len(r.data['questions']) == 4)
v(el, r.data['questions'][0]['id'], 0)
r = el.get(url, {'nouveau': 1})
check('« Recommencer » (?nouveau=1) : nouveau tirage, réponses effacées', r.data['reprise'] is False
      and r.data['verifiees'] == [] and QuizEnCours.objects.get(user=u).reponses == {})
tout = {str(x['id']): SkillQuestion.objects.get(pk=x['id']).correct_answer for x in r.data['questions']}
r = el.post(f'/api/skill-assessments/submit/{lim.id}/', {'answers': tout}, format='json')
a.refresh_from_db()
check('seul le dernier passage est gardé (correction remplacée), score précédent conservé',
      r.data['score'] == r.data['max_score'] and len(a.derniere_correction) == 4 and a.attempts == 2
      and a.previous_score is not None and all(c['is_correct'] for c in a.derniere_correction))

# ── Passage oublié après 24 h
el.get(url)
QuizEnCours.objects.filter(user=u).update(maj=timezone.now() - timedelta(hours=25))
check('passage abandonné depuis plus de 24 h : oublié', el.get('/api/skill-assessments/en-cours/').data == []
      and el.get(url).data['reprise'] is False)

# ── Données personnelles
check('export RGPD : passage en cours inclus', 'skilliq.QuizEnCours' in export_user_data(u))
u.delete()
check('suppression du compte : passage supprimé', not QuizEnCours.objects.exists()
      and not SkillAssessment.objects.filter(chapter=lim).exclude(user=u2).exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
