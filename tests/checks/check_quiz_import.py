"""Quiz écrits d'après les résultats des élèves : fiches exportées (quiz_constats), questions importées en
brouillon « à relire » (quiz_importer), validation dans Pilotage › Quiz.

On vérifie les constats (taux, comptes maison exclus, aucune donnée personnelle), la fiche, le contrôle des
questions (4 réponses, formules, doublons), et surtout qu'une question importée reste invisible des élèves tant
que l'administrateur ne l'a pas validée.
"""
import json
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-quiz-import.sqlite3')
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
from apps.caracteristics.models import Chapter, ClassLevel, Subject  # noqa: E402
from apps.interactions.models import QuestionProgress  # noqa: E402
from apps.skilliq import constats  # noqa: E402
from apps.skilliq.models import SkillAssessment, SkillQuestion  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


admin = User.objects.create_superuser('chef', 'chef@x.fr', 'Motdepasse-solide-42')
eleves = [User.objects.create_user(f'eleve{i}', f'e{i}@x.fr', 'Motdepasse-solide-42') for i in range(4)]
staff = User.objects.create_user('equipe', 'q@x.fr', 'Motdepasse-solide-42', is_staff=True)
sm = ClassLevel.objects.get(name='2ème Bac SM')
maths = Subject.objects.get(name='Mathématiques')
lim = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
vide = Chapter.objects.filter(class_levels=sm).exclude(id=lim.id).first()
check('chapitres de test trouvés', lim and vide)


def contenu(kind, titre, js, chapitre=lim):
    c = Content.objects.create(type=kind, title=titre, author=admin, subject=maths, json_content=js, difficulty='medium')
    c.class_levels.set([sm])
    c.chapters.set([chapitre])
    return c


exo = contenu('exercise', 'TVI et racines', {'version': '2.1', 'blocks': [
    {'type': 'question', 'id': 'q1', 'content': {'html': '<p>Soit $f$ continue sur $[a\\,;b]$.</p>'}, 'subQuestions': [
        {'id': 'a', 'content': {'html': '<p>Montrer que $f(x)=0$ admet une solution.</p>'},
         'meta': {'theorems': ['Théorème des valeurs intermédiaires (TVI)']}},
        {'id': 'b', 'content': {'html': '<p>Calculer $f(0)$.</p>'}}]},
]})
contenu('lesson', 'Cours : continuité', {'version': '2.1', 'sections': [
    {'id': 's1', 'content': {'html': '<p>Théorème des valeurs intermédiaires : si $f$ est <b>continue</b> sur '
                                     '$[a\\,;b]$ et $f(a)f(b)&lt;0$…</p>'}}]})
ct = ContentType.objects.get_for_model(Content)


def qp(user, path, st, **kw):
    QuestionProgress.objects.create(user=user, content_type=ct, object_id=exo.id, question_path=path, status=st, **kw)


# q1.a : 1 réussite sur 3 élèves réels (+ une solution « pas comprise ») ; le compte de l'équipe ne compte pas.
qp(eleves[0], 'q1.a', 'success')
qp(eleves[1], 'q1.a', 'failed', solution_validation='not-understood')
qp(eleves[2], 'q1.a', 'review')
qp(staff, 'q1.a', 'success')
qp(admin, 'q1.a', 'success')
# q1.b : réussie par tous → pas un constat.
for e in eleves[:3]:
    qp(e, 'q1.b', 'success')
# Quiz actuel : une question ratée par 2 élèves sur 3, qui choisissent surtout la réponse 2.
ancienne = SkillQuestion.objects.create(chapter=lim, question='Le TVI exige-t-il la continuité ?',
                                        options=['Oui, sur $[a\\,;b]$', 'Non', 'Seulement en $a$', 'Seulement en $b$'],
                                        correct_answer=0, is_active=True)
for i, rep in enumerate([0, 2, 2]):
    SkillAssessment.objects.create(user=eleves[i], chapter=lim, answers={str(ancienne.id): rep}, score=0, max_score=1)

c = constats.constats(lim, sm)
check('constats : 3 élèves réels (maison exclue)', c['eleves'] == 3, c['eleves'])
check('constats : la question peu réussie, son taux et son énoncé',
      len(c['questions']) == 1 and c['questions'][0]['reussite'] == 33 and c['questions'][0]['question'] == 'q1 · a'
      and 'f(x)=0' in c['questions'][0]['enonce'] and c['questions'][0]['incompris'] == 1, c['questions'])
check('constats : théorème faible (nom exact)', c['theoremes'] and c['theoremes'][0]['theoreme'] == 'Théorème des valeurs intermédiaires (TVI)'
      and c['theoremes'][0]['reussite'] == 33, c['theoremes'])
check('constats : quiz raté et piège le plus choisi', c['quiz'] and c['quiz'][0]['piege'] == 'Seulement en $a$'
      and c['quiz'][0]['reussite'] == 33, c['quiz'])
check('constats : aucun nom ni identifiant d’élève', not any(u.username in json.dumps(c, ensure_ascii=False)
                                                           for u in eleves))
msg = constats.fiche(lim, sm)
check('fiche : constats, cours, programme, questions existantes', all(x in msg for x in (
    '33 % de réussite', 'Théorème des valeurs intermédiaires', 'Le TVI exige-t-il', 'Seulement en $a$')), msg[:300])
check('fiche : cours sans balises HTML', '<b>' not in msg and '&lt;' not in msg and 'f(a)f(b)<0' in msg)
check('fiche : chapitre sans résultat → le dit', 'Pas encore de résultats' in constats.fiche(vide, sm))
tout = constats.constats_niveau(sm)
check('fiches du niveau : seulement les chapitres avec un contenu en ligne', lim.name in tout and vide.name not in tout)
check('aucun nom d’élève dans les fiches', not any(u.username in tout for u in eleves))


def q(texte, bonne='$f$ continue sur $[a\\,;b]$', autres=None, **kw):
    return {'question': texte, 'bonne': bonne,
            'distracteurs': autres or ['$f$ dérivable sur $]a\\,;b[$', '$f$ continue sur $]a\\,;b[$', '$f$ monotone sur $[a\\,;b]$'],
            'explication': 'La continuité sur le fermé est indispensable.', 'difficulte': 'medium',
            'cible': '33 % de réussite à la question q1 · a',
            'theoremes': ['Théorème des valeurs intermédiaires (TVI)'], **kw}


fichier = {'niveau': '2ème Bac SM', 'chapitres': [
    {'chapitre': lim.name, 'questions': [q('Q1 : quelle hypothèse ?'), q('Q2 : laquelle ?'), q('Q3 : formule $x'),
                                         q('Le TVI exige-t-il la continuité ?'), q('Q6', autres=['a', 'a', 'b']),
                                         q('Q7', autres=['a', 'b']), q('Q9', theoremes=[]),
                                         q('Q10', theoremes=['Théorème de Pythagore'])]},
    {'chapitre': 'Chapitre inexistant', 'questions': [q('Q8')]},
]}
bilan = constats.importer(fichier, simulation=True)
check('simulation : rien d’écrit', bilan[0]['creees'] == 2 and not SkillQuestion.objects.filter(source='claude').exists())
chemin = os.path.join(tempfile.gettempdir(), 'fidni-quiz-import.json')
with open(chemin, 'w', encoding='utf-8') as f:
    json.dump(fichier, f, ensure_ascii=False)
import io  # noqa: E402
sortie = io.StringIO()
call_command('quiz_importer', chemin, stdout=sortie)
neuves = list(SkillQuestion.objects.filter(source='claude').order_by('id'))
check('2 questions importées (formule, doublon, réponses identiques, 2 réponses écartées)',
      [x.question for x in neuves] == ['Q1 : quelle hypothèse ?', 'Q2 : laquelle ?'], [x.question for x in neuves])
check('raisons des écarts affichées', all(x in sortie.getvalue() for x in (
    '$ impair', 'déjà présente', 'identiques', 'exactement 3', 'chapitre inconnu', 'aucun théorème',
    'théorème inconnu pour ce chapitre : Théorème de Pythagore')), sortie.getvalue())
check('théorème rattaché à l’import', all([t.name for t in x.theorems.all()] == ['Théorème des valeurs intermédiaires (TVI)']
                                          for x in neuves))
call_command('quiz_importer', chemin, stdout=io.StringIO())
check('import rejoué : aucun doublon', SkillQuestion.objects.filter(source='claude').count() == 2)
check('brouillons à relire, hors ligne', all(x.a_relire and not x.is_active for x in neuves))
check('bonne réponse retrouvée après mélange', all(x.options[x.correct_answer] == '$f$ continue sur $[a\\,;b]$'
                                                    and len(x.options) == 4 for x in neuves))
check('motif = la cible', neuves[0].motif.startswith('33 %'), neuves[0].motif)
f2 = os.path.join(tempfile.gettempdir(), 'fidni-quiz-import-bad.json')
with open(f2, 'w', encoding='utf-8') as f:
    json.dump({'niveau': 'Niveau inconnu', 'chapitres': []}, f)
try:
    call_command('quiz_importer', f2, stdout=io.StringIO())
    check('niveau inconnu refusé', False)
except Exception as exc:  # CommandError
    check('niveau inconnu refusé', 'niveau inconnu' in str(exc), exc)

cl, el = APIClient(), APIClient()
cl.force_authenticate(admin)
el.force_authenticate(eleves[0])
check('moniteur : questions de quiz à relire', cl.get('/api/pilotage/direct/').data['todo']['quiz_a_relire'] == 2)
rows = {x['id']: x for x in cl.get('/api/pilotage/quiz/', {'niveau': sm.id}).data}
check('liste des chapitres : à relire, contenu en ligne', rows[lim.id]['a_relire'] == 2 and rows[lim.id]['contenus']
      and not rows[vide.id]['contenus'], rows[lim.id])
detail = cl.get(f'/api/pilotage/quiz/chapitre/{lim.id}/').data
check('détail : source, à relire, motif', any(x['source'] == 'claude' and x['a_relire'] and x['motif']
                                             for x in detail['questions']))

# Les élèves ne voient JAMAIS une question à relire, même activée par erreur.
SkillQuestion.objects.filter(pk=neuves[0].pk).update(is_active=True)
ids = {x['id'] for x in el.get(f'/api/skill-assessments/quiz/{lim.id}/').data['questions']}
check('élève : question à relire jamais servie', neuves[0].id not in ids and ancienne.id in ids, ids)
check('élève : décompte des quiz sans les questions à relire',
      el.get('/api/skill-assessments/available/').data.get(str(lim.id)) == 1)
SkillQuestion.objects.filter(pk=neuves[0].pk).update(is_active=False)

for i in range(3):
    SkillQuestion.objects.create(chapter=lim, question=f'Manuelle {i}', options=['a', 'b'], correct_answer=0, is_active=False)
r = cl.post(f'/api/pilotage/quiz/chapitre/{lim.id}/publier/', {'en_ligne': True}, format='json')
check('mise en ligne : 4 validées + 2 à relire → refusée, la relecture est rappelée',
      r.status_code == 400 and 'attendent ta relecture' in r.data['detail'], r.data)
r = cl.patch(f'/api/pilotage/quiz/question/{neuves[0].id}/', {'valider': True}, format='json')
check('valider une question (quiz déjà en ligne) → validée et en ligne aussitôt',
      r.status_code == 200 and not r.data['a_relire'] and r.data['en_ligne'], r.data)
r = cl.post(f'/api/pilotage/quiz/chapitre/{lim.id}/publier/', {'en_ligne': True}, format='json')
neuves[1].refresh_from_db()
check('mise en ligne : seules les validées', r.status_code == 200 and r.data['questions'] == 5
      and not neuves[1].is_active and neuves[1].a_relire, r.data)
r = cl.post(f'/api/pilotage/quiz/chapitre/{lim.id}/valider/', {'ids': [neuves[1].id]}, format='json')
neuves[1].refresh_from_db()
check('valider sur un quiz en ligne → en ligne aussitôt', r.status_code == 200 and r.data['validees'] == 1
      and neuves[1].is_active and not neuves[1].a_relire, r.data)
check('valider : ids invalides refusés', cl.post(f'/api/pilotage/quiz/chapitre/{lim.id}/valider/', {'ids': 'x'},
                                                format='json').status_code == 400)
check('valider réservé aux administrateurs',
      el.post(f'/api/pilotage/quiz/chapitre/{lim.id}/valider/', {}, format='json').status_code == 403)
check('valider : true seulement', cl.patch(f'/api/pilotage/quiz/question/{neuves[0].id}/', {'valider': 1},
                                          format='json').status_code == 400)

# ---------------------------------------------------------------- théorèmes : tirage, niveau, bilan
from apps.caracteristics.models import Theorem  # noqa: E402
from apps.skilliq import tirage  # noqa: E402

TH = {t.name: t for t in Theorem.objects.filter(chapters=lim)}
check('10 théorèmes au chapitre, arc tangente réservé à la SM', len(TH) == 10
      and [lv.name for lv in TH['Fonction arc tangente'].class_levels.all()] == ['2ème Bac SM'], sorted(TH))
SkillQuestion.objects.filter(chapter=lim).delete()
SkillAssessment.objects.filter(chapter=lim).delete()


def creer(nom, i):
    x = SkillQuestion.objects.create(chapter=lim, question=f'{nom} {i}', options=['a', 'b', 'c', 'd'], correct_answer=0)
    x.theorems.set([TH[nom]])
    return x


par_nom = {n: [creer(n, i) for i in range(3)] for n in TH}
pc = ClassLevel.objects.get(name='2ème Bac PC/SVT')
for u, lv in ((eleves[0], sm), (eleves[1], pc)):
    u.profile.class_level = lv
    u.profile.save()
el_pc = APIClient()
el_pc.force_authenticate(eleves[1])


def tires(client):
    return [SkillQuestion.objects.get(pk=x['id']) for x in client.get(f'/api/skill-assessments/quiz/{lim.id}/').data['questions']]


couverts = [{t.name for x in tires(el) for t in x.theorems.all()} for _ in range(5)]
check('SM : 10 questions, chaque théorème évalué à chaque passage', all(c == set(TH) for c in couverts),
      [len(c) for c in couverts])
vus_pc = [tires(el_pc) for _ in range(5)]
check('PC/SVT : jamais une question d’arc tangente, les 9 autres théorèmes couverts',
      all(not any(t.name == 'Fonction arc tangente' for x in v for t in x.theorems.all()) for v in vus_pc)
      and all({t.name for x in v for t in x.theorems.all()} == set(TH) - {'Fonction arc tangente'} for v in vus_pc))
check('quiz disponibles selon le niveau', el.get('/api/skill-assessments/available/').data.get(str(lim.id)) == 30
      and el_pc.get('/api/skill-assessments/available/').data.get(str(lim.id)) == 27)

servies = tires(el)
tvi = next(x for x in servies if x.theorems.first().name == 'Théorème des valeurs intermédiaires (TVI)')
reponses = {str(x.id): (1 if x.id == tvi.id else 0) for x in servies}
r = el.post(f'/api/skill-assessments/submit/{lim.id}/', {'answers': reponses}, format='json')
pt = r.data.get('par_theoreme') or {}
check('bilan : le TVI raté en tête (0 %), les autres à 100 %', r.status_code == 200
      and pt['theoremes'][0]['name'] == 'Théorème des valeurs intermédiaires (TVI)' and pt['theoremes'][0]['pct'] == 0
      and all(s['pct'] == 100 for s in pt['theoremes'][1:]) and len(pt['theoremes']) == 10, pt)
check('bilan : à revoir = le TVI, chapitre pas maîtrisé', pt['a_revoir'] == ['Théorème des valeurs intermédiaires (TVI)']
      and pt['complet'] is False and pt['non_evalues'] == [])
check('correction : théorème de chaque question', all(c['theoremes'] for c in r.data['correction']))
check('bilan gardé avec le résultat', SkillAssessment.objects.get(user=eleves[0], chapter=lim).par_theoreme == pt
      and el.get('/api/skill-assessments/my/').data[0]['par_theoreme'] == pt)
servies = tires(el)
r = el.post(f'/api/skill-assessments/submit/{lim.id}/', {'answers': {str(x.id): 0 for x in servies}}, format='json')
check('tout juste → chapitre maîtrisé à 100 %', r.data['par_theoreme']['complet'] is True
      and r.data['par_theoreme']['a_revoir'] == [])
deux = par_nom['Théorème des gendarmes'][0]
b = tirage.bilan([deux], {str(deux.id): 0}, [deux, par_nom['Méthode de dichotomie'][0]])
check('théorème non tiré → « non évalué », chapitre pas déclaré maîtrisé',
      b['non_evalues'] == [{'id': TH['Méthode de dichotomie'].id, 'name': 'Méthode de dichotomie'}] and b['complet'] is False)

d = cl.get(f'/api/pilotage/quiz/chapitre/{lim.id}/').data
check('admin : théorèmes du chapitre et de chaque question', len(d['chapitre']['theoremes']) == 10
      and all(x['theoremes'] for x in d['questions']))
autre = Theorem.objects.exclude(chapters=lim).first()
r = cl.patch(f'/api/pilotage/quiz/question/{deux.id}/', {'theoremes': [TH['Méthode de dichotomie'].id]}, format='json')
check('admin : changer le théorème d’une question', r.status_code == 200
      and [t['name'] for t in r.data['theoremes']] == ['Méthode de dichotomie'], r.data)
check('admin : théorème d’un autre chapitre refusé', cl.patch(f'/api/pilotage/quiz/question/{deux.id}/',
                                                             {'theoremes': [autre.id]}, format='json').status_code == 400)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
