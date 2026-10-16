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

# ── Plusieurs bonnes réponses (16/10/2026) : « 2 choix justes sur 5 proposés », tout ou rien
from apps.skilliq import constats  # noqa: E402
BONNES = ['$f$ est continue sur $[a\\,;b]$', '$f(a)$ et $f(b)$ sont de signes contraires']
FAUSSES = ['$f$ est dérivable sur $\\mathbb{R}$', '$f$ est paire', '$f(a) = f(b)$']
mq = lambda texte, **kw: {'question': texte, 'bonnes': BONNES, 'distracteurs': FAUSSES,  # noqa: E731
                          'explication': 'Les deux hypothèses du TVI.', 'difficulte': 'hard', 'cible': 'TVI',
                          'theoremes': [tvi.name], **kw}
bilan = constats.importer({'niveau': sm.name, 'chapitres': [{'chapitre': lim.name, 'questions': [
    mq('Hypothèses du TVI : coche les deux bonnes.'),
    mq('Une seule « bonnes »', bonnes=[BONNES[0]]),
    mq('Les deux formes', bonne=BONNES[0]),
    mq('Sept réponses', distracteurs=FAUSSES + ['a', 'b']),
    mq('Sans distracteur', distracteurs=[]),
    mq('Doublon', distracteurs=[BONNES[0], 'x', 'y']),
]}]})
raisons = ' | '.join(e['raison'] for e in bilan[0]['ecartees'])
check('import : 2 bonnes réponses sur 5 acceptées, formats invalides écartés', bilan[0]['creees'] == 1
      and len(bilan[0]['ecartees']) == 5 and 'au moins 2' in raisons and 'pas les deux' in raisons
      and 'de 3 à 6' in raisons and 'au moins 1 mauvaise' in raisons and 'identiques' in raisons, bilan)
mult = SkillQuestion.objects.get(question='Hypothèses du TVI : coche les deux bonnes.')
check('import : 5 réponses mélangées, bonnes retrouvées (correct_answers), correct_answer = la première',
      len(mult.options) == 5 and sorted(mult.options[i] for i in mult.correct_answers) == sorted(BONNES)
      and mult.correct_answer == mult.correct_answers[0] and mult.bonnes() == mult.correct_answers
      and mult.a_relire and [t.name for t in mult.theorems.all()] == [tvi.name], (mult.options, mult.correct_answers))
B = mult.bonnes()
F = [i for i in range(5) if i not in B]
check('est_juste : tout ou rien', mult.est_juste(B) and mult.est_juste(B[::-1]) and not mult.est_juste([B[0]])
      and not mult.est_juste(B[0]) and not mult.est_juste(B + [F[0]]) and not mult.est_juste([B[0], F[0]])
      and not mult.est_juste(-1) and not mult.est_juste(None) and not mult.est_juste([]))
simple = SkillQuestion.objects.get(pk=ordre[1])
check('question à une réponse : inchangée', simple.correct_answers == [] and simple.bonnes() == [simple.correct_answer]
      and simple.est_juste(simple.correct_answer) and simple.est_juste([simple.correct_answer])
      and not simple.est_juste((simple.correct_answer + 1) % 4))
SkillQuestion.objects.filter(pk=mult.pk).update(a_relire=False, is_active=True)

ma, cl_a = eleve('multi_a')
mb, cl_b = eleve('multi_b')
mc, cl_c = eleve('multi_c')
r = cl_a.get(url)
servie = next((x for x in r.data['questions'] if x['id'] == mult.id), None)
check('servie : « nb_bonnes » = 2, jamais lesquelles ; 1 pour les autres', servie and servie['nb_bonnes'] == 2
      and 'correct_answers' not in servie and 'correct_answer' not in servie
      and all(x['nb_bonnes'] == 1 for x in r.data['questions'] if x['id'] != mult.id), r.data['questions'])
cl_b.get(url)
cl_c.get(url)
check('réponse en double : 400', v(cl_a, mult.id, [B[0], B[0]]).status_code == 400)
check('index hors des choix : 400', v(cl_a, mult.id, [B[0], 7]).status_code == 400)
check('liste vide : 400', v(cl_a, mult.id, []).status_code == 400)
r = v(cl_a, mult.id, B[::-1])
check('les 2 bonnes réponses : juste ; correct_answers renvoyées', r.status_code == 200 and r.data['is_correct'] is True
      and r.data['correct_answers'] == B and r.data['correct_answer'] == B[0] and r.data['your_answer'] == B, r.data)
r = v(cl_b, mult.id, [B[1]])
check('une seule des 2 bonnes : faux', r.status_code == 200 and r.data['is_correct'] is False
      and r.data['correct_answers'] == B, r.data)
r = v(cl_c, mult.id, [B[0], F[0]])
check('une bonne et une fausse : faux', r.status_code == 200 and r.data['is_correct'] is False, r.data)
r = v(cl_c, mult.id, B)
check('réponse verrouillée (plusieurs bonnes réponses)', r.data['your_answer'] == sorted([B[0], F[0]])
      and r.data['is_correct'] is False, r.data)
r = cl_a.get(url)
check('reprise : la réponse multiple verrouillée revient', [x['your_answer'] for x in r.data['verifiees']
                                                           if x['id'] == mult.id] == [B], r.data['verifiees'])

autres = {str(x.id): x.correct_answer for x in SkillQuestion.objects.filter(chapter=lim, class_level=sm, is_active=True,
                                                                            a_relire=False).exclude(pk=mult.pk)}
pts = {'easy': 1, 'medium': 2, 'hard': 3}
maxi = sum(pts[x.difficulty] for x in SkillQuestion.objects.filter(chapter=lim, class_level=sm, is_active=True,
                                                                  a_relire=False))


def envoi(client, reponse_multiple):
    rep = client.post(f'/api/skill-assessments/submit/{lim.id}/', {'answers': {**autres, str(mult.id): reponse_multiple}},
                      format='json')
    c = next((x for x in rep.data.get('correction', []) if x['id'] == mult.id), {})
    th = next((x for x in (rep.data.get('par_theoreme') or {}).get('theoremes', []) if x['id'] == tvi.id), {})
    return rep, c, th


r, c, th = envoi(cl_a, B)
check('envoi : tout juste (liste) → 100 %, bilan TVI complet', r.status_code == 200 and r.data['score'] == maxi
      and r.data['max_score'] == maxi and c.get('is_correct') is True and c.get('correct_answers') == B
      and th.get('justes') == th.get('total') == len(autres) + 1, (r.status_code, r.data.get('score'), maxi, c, th))
r, c, th = envoi(cl_b, B)  # réponse verrouillée (partielle) prioritaire
check('envoi : réponse partielle verrouillée → fausse, score sans ses 3 points, bilan TVI à revoir',
      r.status_code == 200 and r.data['score'] == maxi - 3 and c.get('is_correct') is False
      and c.get('your_answer') == [B[1]] and th.get('justes') == th.get('total', 0) - 1
      and tvi.name in r.data['par_theoreme']['a_revoir'], (r.data.get('score'), c, th))
cl_d = eleve('multi_d')[1]
cl_d.get(url)
r, c, th = envoi(cl_d, [B[0], B[0]])
check('envoi : réponse en double = sans réponse (fausse), sans erreur', r.status_code == 200
      and c.get('your_answer') == -1 and c.get('is_correct') is False, (r.status_code, c))
r = cl_c.post(f'/api/skill-assessments/submit/{lim.id}/', {'answers': {str(mult.id): [True]}}, format='json')
check('envoi : réponse illisible : 400', r.status_code == 400, r.status_code)
derniere = SkillAssessment.objects.get(user=ma, chapter=lim, class_level=sm).derniere_correction
check('correction figée : correct_answers gardées', any(x['id'] == mult.id and x['correct_answers'] == B
                                                        and x['your_answer'] == B for x in derniere))
cq = constats.constats_quiz(lim, maison=set())
ligne = next((x for x in cq if x['question'] == mult.question), None)
check('constats du quiz : réussite et « bonnes » réponses (plusieurs)', ligne is not None and ligne['reussite'] == 33
      and all(b in ligne['bonne'] for b in BONNES) and ligne['eleves'] == 3, cq)
User.objects.filter(username__startswith='multi_').delete()  # la suite ne compte que les élèves du début

# ── Données personnelles
check('export RGPD : passage en cours inclus', 'skilliq.QuizEnCours' in export_user_data(u))
u.delete()
check('suppression du compte : passage supprimé', not QuizEnCours.objects.exists()
      and not SkillAssessment.objects.filter(chapter=lim).exclude(user=u2).exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
