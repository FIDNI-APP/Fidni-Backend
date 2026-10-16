"""Migration caracteristics/0003_programme_officiel sur une base remplie comme la production : seeder de 2025
(chapitre ln/exp, Physique, Chimie, niveaux d'ordre 1 et 2) puis seeder d'avant le 11/10/2026 (copies figées dans
fixtures/), contenus à plusieurs niveaux, cahiers, listes, devoirs, quiz, parcours, concours, temps d'étude, filtres
du Pilotage, fiches IA en attente. Répétition à blanc (rien ne bouge), migration, nouveau seeder, chaque règle de la
spécification vérifiée, deuxième passage sans effet. Base neuve : 0003 ne fait rien."""
import importlib
import io
import os
import runpy
import sys
import tempfile
from collections import defaultdict
from datetime import date, timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-migration-programme.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def silence(*_args, **_kw):
    pass


# ── Base neuve : la migration passe avant le seeder et ne fait rien
call_command('migrate', verbosity=0)
from apps.caracteristics.models import Chapter, ClassLevel, Subject, Subfield, Theorem  # noqa: E402
from apps.logging.models import SystemEvent  # noqa: E402
check('base neuve : 0003 sans effet', not ClassLevel.objects.exists() and not Chapter.objects.exists()
      and not SystemEvent.objects.filter(event_type='migration').exists())

# ── Base « production » : caracteristics en 0002, anciens seeders, données
call_command('migrate', 'caracteristics', '0002', verbosity=0)
FIXTURES = os.path.join(BACKEND, 'tests', 'checks', 'fixtures')
runpy.run_path(os.path.join(FIXTURES, 'seeder_2025.py'))
runpy.run_path(os.path.join(FIXTURES, 'ancien_base_tables.py'))

from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from apps.concours.models import ConcoursExam, ConcoursTip, SimulationAnswer, SimulationSession  # noqa: E402
from apps.ia.models import IAJob  # noqa: E402
from apps.interactions.models import (RevisionList, StudyTimeTracker, TaxonomyTimeSpent, UpcomingTest,  # noqa: E402
                                      update_taxonomy_time)
from apps.learningpath.models import LearningPath, PathChapter  # noqa: E402
from apps.notebooks.models import Notebook, NotebookLessonEntry, NotebookSection  # noqa: E402
from apps.skilliq.models import SkillAssessment, SkillQuestion  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users.models import UsageDaily, UserProfile  # noqa: E402
from apps.caracteristics import programme as P  # noqa: E402
from apps.caracteristics.programme_migration import appliquer  # noqa: E402

TC, SM1, SM2, PC = P.TC, P.SM1, P.SM2, P.PC
PC0 = '2ème Bac PC'  # nom du niveau dans la base « production » (renommé « 2ème Bac PC/SVT » par 0004, 12/10/2026)
TRIGO, ANA_PS, ANA_ESP = ('Trigonométrie (formules de transformation)', 'Étude analytique du produit scalaire dans le plan',
                          "Géométrie analytique de l'espace")
TAF_CH, LNEXP = 'Théorème des Accroissements Finis (TAF)', 'Fonctions logarithmiques et exponentielles'
lv = {n: ClassLevel.objects.get(name=PC0 if n == PC else n) for n in (TC, SM1, SM2, PC)}
maths = Subject.objects.get(name='Mathématiques')
physique = Subject.objects.get(name='Physique')
check('base ancienne : restes de 2025 présents', Chapter.objects.filter(name=LNEXP).exists()
      and Chapter.objects.filter(subject=physique, class_levels=lv[SM2]).count() == 8
      and Chapter.objects.filter(name='Dénombrement', class_levels=lv[SM2]).exists())


def ch(nom):
    return Chapter.objects.get(name=nom, subject=maths)


def th(nom):
    return Theorem.objects.get(name=nom)


auteur = User.objects.create_user('auteur', 'auteur@x.fr', 'x')
alice = User.objects.create_user('alice', 'alice@x.fr', 'x')  # 1ère Bac SM
bob = User.objects.create_user('bob', 'bob@x.fr', 'x')  # 2ème Bac SM
carl = User.objects.create_user('carl', 'carl@x.fr', 'x')  # sans niveau
UserProfile.objects.filter(user=alice).update(class_level=lv[SM1])
UserProfile.objects.filter(user=bob).update(class_level=lv[SM2])
_n = [0]


def q(*notions):
    _n[0] += 1
    return {'type': 'question', 'id': f'q{_n[0]}', 'meta': {'skills': list(notions)} if notions else {}}


def make(niveaux, chapitres, theoremes=(), questions=(), kind='exercise', subject=None, **kw):
    c = Content.objects.create(type=kind, title=f'Contenu {_n[0]}-{len(chapitres)}', author=auteur,
                               subject=subject or maths, json_content={'version': '2.1', 'blocks': list(questions)}, **kw)
    _n[0] += 1
    c.class_levels.set([lv[n] for n in niveaux])
    chs = [x if isinstance(x, Chapter) else Chapter.objects.get(name=x) for x in chapitres]
    c.chapters.set(chs)
    c.subfields.set({x.subfield for x in chs if x.subfield})
    c.theorems.set([th(t) for t in theoremes])
    return c


avant = {nom: ch(nom).id for nom in (TAF_CH, LNEXP, 'Dénombrement', 'Calcul trigonométrique', 'Dérivation et étude des fonctions',
                                      'Probabilités', 'Limites et continuité')}
th_avant = {nom: th(nom).id for nom in ('Théorème de Moivre', 'Applications linéaires et matrices', 'Loi des grands nombres',
                                         'Théorème de Bolzano-Weierstrass')}
# Doublon d'administrateur (« probabilités » sans domaine), et lignes d'administrateurs sans niveau.
dup = Chapter.objects.create(name='probabilités ', subject=maths, subfield=None)
dup.class_levels.add(lv[SM2])
admin_ch = Chapter.objects.create(name='Exercices de synthèse', subject=maths,
                                  subfield=Subfield.objects.get(name='Analyse', subject=maths))
admin_th = Theorem.objects.create(name='Lemme maison', subject=maths, subfield=admin_ch.subfield)

C = {
    1: make([SM1], ['Calcul trigonométrique']),
    2: make([TC, SM1], ['Produit scalaire dans le plan']),
    3: make([TC], ["Géométrie dans l'espace"]),
    4: make([SM2], ['Espaces vectoriels', 'Structures algébriques'], kind='exam'),
    5: make([SM2, PC], ['Dénombrement']),
    6: make([SM2], ['Dénombrement']),
    7: make([PC], ['Calcul intégral'], questions=[q('primitives-usuelles'), q('primitives-usuelles'), q('primitives-usuelles')]),
    8: make([PC], ['Calcul intégral'], questions=[q('primitives-usuelles'), q('primitives-usuelles'), q()]),
    9: make([SM2], ['Calcul intégral'], questions=[q('primitives'), q('integrale')]),
    10: make([SM2], ['Calcul intégral'], ['Primitives des fonctions usuelles']),
    11: make([SM2], ['Calcul intégral'], questions=[q('integrale')]),
    12: make([SM2], [TAF_CH], ["Applications du TAF à l'étude des fonctions"]),
    13: make([SM2], [LNEXP], ["Dérivée et propriétés du logarithme et de l'exponentielle"],
             [q('logarithme', 'recurrence')], kind='lesson'),
    14: make([SM2], [LNEXP], questions=[q('exponentielle')]),
    15: make([SM2], [LNEXP], questions=[q('logarithme'), q('exponentielle')]),
    16: make([SM1], ["Vecteurs de l'espace"], questions=[q('produit-vectoriel')]),
    17: make([SM1], ["Produit scalaire dans l'espace"], ['Expression analytique du produit vectoriel']),
    18: make([SM1, PC], ["Produit scalaire dans l'espace"], questions=[q('produit-vectoriel')]),
    19: make([SM2], ['Limites et continuité'], ['Théorème de Bolzano-Weierstrass']),
    20: make([SM2], ['Nombres complexes'], ['Loi des grands nombres', 'Théorème de Moivre',
                                            'Méthode de variation de la constante', 'Produit scalaire et propriétés',
                                            'Formule de combinaison et permutation']),
    21: make([], ['Calcul trigonométrique']),
    22: make([SM2], ['Lois de Newton'], subject=physique),
    23: make([SM1], ["Géométrie dans l'espace"], questions=[q('representation-parametrique')], kind='exam',
             is_national_exam=True),
    24: make([SM2], [dup]),
}
L1, L2 = make([SM2], ['Dénombrement'], kind='lesson'), make([SM2], ['Probabilités'], kind='lesson')
L3 = make([SM1], ['Calcul trigonométrique'], kind='lesson')
L4 = make([SM2], [LNEXP], kind='lesson')

# Cahiers (sections créées comme l'API : chapitres de la matière au niveau, par nom)


def cahier(user, niveau):
    nb = Notebook.objects.create(user=user, subject=maths, class_level=lv[niveau], title=f'Maths {niveau} {user}')
    for i, chap in enumerate(Chapter.objects.filter(subject=maths, class_levels=lv[niveau]).exclude(pk=dup.pk).order_by('name')):
        NotebookSection.objects.create(notebook=nb, chapter=chap, order=i)
    return nb


nb2, nb1, nbtc = cahier(alice, SM2), cahier(alice, SM1), cahier(bob, TC)
sec = lambda nb, nom: NotebookSection.objects.get(notebook=nb, chapter=ch(nom))  # noqa: E731
s_den, s_pro = sec(nb2, 'Dénombrement'), sec(nb2, 'Probabilités')
NotebookSection.objects.filter(pk=s_den.pk).update(user_notes='notes D')
NotebookSection.objects.filter(pk=s_pro.pk).update(user_notes='notes P')
NotebookLessonEntry.objects.create(section=s_pro, lesson=L2, page_order=0, content_start=0, content_end=5)
NotebookLessonEntry.objects.create(section=s_den, lesson=L1, page_order=0, content_start=0, content_end=3)
NotebookLessonEntry.objects.create(section=s_den, lesson=L2, page_order=1, content_start=0, content_end=5)  # déjà là
NotebookLessonEntry.objects.create(section=sec(nb2, LNEXP), lesson=L4, page_order=0)
s_trig = sec(nb1, 'Calcul trigonométrique')
NotebookLessonEntry.objects.create(section=s_trig, lesson=L3, page_order=0)

# Listes de révision et devoirs


def liste(user, nom, niveaux, chapitres):
    r = RevisionList.objects.create(user=user, name=nom)
    r.class_levels.set([lv[n] for n in niveaux])
    r.chapters.set([ch(x) for x in chapitres])
    return r


RL = {1: liste(alice, 'l1', [SM1], ['Calcul trigonométrique']), 2: liste(carl, 'l2', [], ['Produit scalaire dans le plan']),
      3: liste(bob, 'l3', [TC], ["Géométrie dans l'espace"]), 4: liste(bob, 'l4', [SM2], ['Dénombrement']),
      5: liste(alice, 'l5', [SM1], ['Dénombrement']), 6: liste(carl, 'l6', [], [TAF_CH]),
      7: liste(bob, 'l7', [TC, SM1], ['Calcul trigonométrique'])}


def devoir(user, niveau, chapitres):
    u = UpcomingTest.objects.create(user=user, subject=maths, class_level=lv[niveau] if niveau else None,
                                    date=date.today() + timedelta(days=7))
    u.chapters.set([ch(x) for x in chapitres])
    return u


UT = {1: devoir(bob, SM2, ['Dénombrement', TAF_CH]), 2: devoir(alice, None, ['Calcul trigonométrique']),
      3: devoir(carl, None, ['Dénombrement'])}
tip = ConcoursTip.objects.create(title='Astuce', created_by=auteur)
tip.chapters.set([ch('Calcul trigonométrique'), ch(TAF_CH)])

# Quiz Skill IQ et résultats
sq = {k: SkillQuestion.objects.create(chapter=ch(nom), question=f'Question {k} sur {nom}', options=['a', 'b'], correct_answer=0)
      for k, nom in ((1, TAF_CH), (2, 'Calcul trigonométrique'), (3, 'Dénombrement'), (4, LNEXP))}
a1 = SkillAssessment.objects.create(user=alice, chapter=ch(TAF_CH), score=3, max_score=4, answers={'1': 0}, time_spent=30, attempts=1)
a2 = SkillAssessment.objects.create(user=alice, chapter=ch('Dérivation et étude des fonctions'), score=5, max_score=6,
                                    answers={'9': 1}, time_spent=50, attempts=2, previous_score=2, previous_max=6)
a3 = SkillAssessment.objects.create(user=bob, chapter=ch(TAF_CH), score=1, max_score=4, time_spent=10)


# Parcours
def parcours(titre, niveaux, chapitres):
    lp = LearningPath.objects.create(subject=maths, title=titre)
    lp.class_level.set([lv[n] for n in niveaux])
    return [PathChapter.objects.create(learning_path=lp, chapter=x if isinstance(x, Chapter) else ch(x), title=str(x), order=i)
            for i, x in enumerate(chapitres)]


pc1, = parcours('P1', [SM2], [TAF_CH])
pc2, = parcours('P2', [SM1], ['Calcul trigonométrique'])
pc3, = parcours('P3', [TC, SM1], ['Produit scalaire dans le plan'])
pc4, = parcours('P4', [SM2], ['Dénombrement'])
pc5a, pc5b = parcours('P5', [SM2], ['Probabilités', dup])

# Concours (identifiants de chapitre dans le JSON, en int ou en str)
exam = ConcoursExam.objects.create(concours_type='ensa', year=2024, created_by=auteur, json_content={'version': '1.0', 'questions': [
    {'id': 'q1', 'chapter_id': avant[TAF_CH]}, {'id': 'q2', 'chapter_id': str(avant[TAF_CH])},
    {'id': 'q3', 'chapter_id': avant['Limites et continuité']}]})
sess = SimulationSession.objects.create(user=bob, mode='exam', concours_type='ensa', exam=exam, duration_minutes=60,
                                        questions_snapshot=[{'exam_id': exam.id, 'position': 0,
                                                             'question': {'id': 'q1', 'chapter_id': avant[TAF_CH]}}])
SimulationAnswer.objects.create(session=sess, position=0, chapter_id=avant[TAF_CH])

# Temps d'étude (TaxonomyTimeSpent calculé comme en production)
ct_content = ContentType.objects.get_for_model(Content)
for user, c, s in ((alice, C[1], 600), (alice, C[2], 120), (bob, C[6], 300), (bob, C[5], 90), (bob, C[12], 200),
                   (bob, C[13], 100), (alice, C[16], 50), (bob, C[7], 70), (bob, C[20], 40), (bob, C[4], 30)):
    StudyTimeTracker.objects.create(user=user, content_type=ct_content, object_id=c.id, time_spent_seconds=s)
    update_taxonomy_time(user, c, timedelta(seconds=s))


def temps_attendu():
    out = defaultdict(lambda: [0, 0, 0, 0])
    for t in StudyTimeTracker.objects.filter(content_type=ct_content, time_spent_seconds__gt=0):
        c = Content.objects.get(pk=t.object_id)
        k = {'exercise': 1, 'lesson': 2, 'exam': 3}[c.type]
        for kind, objs in (('chapter', c.chapters.all()), ('theorem', c.theorems.all()), ('subfield', c.subfields.all())):
            for o in objs:
                e = out[(t.user_id, kind, o.id)]
                e[0] += t.time_spent_seconds
                e[k] += t.time_spent_seconds
    return {k: tuple(v) for k, v in out.items()}


def temps_reel():
    return {(r.user_id, r.taxonomy_type, r.object_id): tuple(int(x.total_seconds()) for x in (
        r.total_time, r.exercise_time, r.lesson_time, r.exam_time))
        for r in TaxonomyTimeSpent.objects.exclude(taxonomy_type='subject')}


check('temps : table de départ cohérente', temps_reel() == temps_attendu())

# Filtres du Pilotage
today = date.today()
UsageDaily.objects.create(date=today, kind='filtre', name=f'exercise:chapitre:{avant[TAF_CH]}', count=2, visitors=1, anon_count=1, anon_visitors=1)
UsageDaily.objects.create(date=today, kind='filtre', name=f"exercise:chapitre:{avant['Dérivation et étude des fonctions']}",
                          count=3, visitors=2)
UsageDaily.objects.create(date=today - timedelta(days=1), kind='filtre', name=f'exam:chapitre:{avant[TAF_CH]}', count=4, visitors=4)
UsageDaily.objects.create(date=today, kind='filtre', name=f"exercise:theoreme:{th_avant['Loi des grands nombres']}", count=1, visitors=1)
UsageDaily.objects.create(date=today, kind='filtre', name=f"exercise:theoreme:{th_avant['Théorème de Bolzano-Weierstrass']}", count=1, visitors=1)
UsageDaily.objects.create(date=today, kind='filtre', name=f"lesson:chapitre:{avant['Dénombrement']}", count=1, visitors=1)

# Fiches IA en attente (et une publiée, à laisser)
FICHES = [{'cle': 'a', 'niveaux': [SM1], 'chapitres': ['Calcul trigonométrique'],
           'theoremes': ['Théorème de Moivre', 'Loi des grands nombres']},
          {'cle': 'b', 'niveaux': [SM2, PC0], 'chapitres': ['Dénombrement', TAF_CH], 'theoremes': []},
          {'cle': 'c', 'niveaux': [TC, SM1], 'chapitres': ['Calcul trigonométrique', LNEXP]}]
job = IAJob.objects.create(kind='import', status='pret', result={'fiches': [dict(f) for f in FICHES], 'doutes': ['x']})
job_publie = IAJob.objects.create(kind='import', status='publie', result={'fiches': [dict(f) for f in FICHES]})

updated = dict(Content.objects.values_list('id', 'updated_at'))
nb_contenus = Content.objects.count()


def instantane():
    from django.apps import apps as A
    out = {}
    for label in ('caracteristics.Chapter', 'caracteristics.Theorem', 'caracteristics.Subfield', 'caracteristics.ClassLevel',
                  'caracteristics.Subject', 'things.Content', 'skilliq.SkillQuestion', 'skilliq.SkillAssessment',
                  'notebooks.NotebookSection', 'notebooks.NotebookLessonEntry', 'learningpath.PathChapter',
                  'users.UsageDaily', 'ia.IAJob', 'concours.ConcoursExam', 'concours.SimulationSession',
                  'concours.SimulationAnswer', 'logging.SystemEvent', 'interactions.RevisionList', 'interactions.UpcomingTest'):
        out[label] = sorted(map(repr, A.get_model(label).objects.values_list()))
    for M, champ in ((Content, 'chapters'), (Content, 'theorems'), (Content, 'subfields'), (Content, 'class_levels'),
                     (Chapter, 'class_levels'), (Theorem, 'chapters'), (Theorem, 'class_levels'), (Subject, 'class_levels'),
                     (Subfield, 'class_levels'), (RevisionList, 'chapters'), (UpcomingTest, 'chapters'),
                     (ConcoursTip, 'chapters')):
        through = getattr(M, champ).through
        out[f'{M.__name__}.{champ}'] = sorted(map(repr, through.objects.values_list()))
    out['temps'] = temps_reel()
    return out


# ── Répétition à blanc : rapport, vérifications conformes, puis tout est annulé
snap = instantane()
sortie = io.StringIO()
call_command('programme_officiel', '--a-blanc', stdout=sortie)
texte = sortie.getvalue()
check('à blanc : rapport et vérifications imprimés', 'À BLANC' in texte and 'Chapitres : conformes' in texte
      and 'Théorèmes : conformes' in texte and 'tout a été annulé' in texte, texte[-1500:])
check('à blanc : base inchangée', instantane() == snap)
sortie = io.StringIO()
call_command('programme_officiel', stdout=sortie)
check('sans --a-blanc : écarts listés (base ancienne)', 'Dénombrement' in sortie.getvalue()
      and 'écart' in sortie.getvalue(), sortie.getvalue()[:500])

# ── Migration, puis nouveau seeder (comme l'entrypoint)
nb_pc = Notebook.objects.create(user=User.objects.order_by('id').first(), subject=maths, class_level=lv[PC])
check('cahier : titre généré avec l’ancien nom', nb_pc.title == f'{maths.name} - {PC0}', nb_pc.title)
call_command('migrate', 'caracteristics', '0003', verbosity=0)
check('0003 : le niveau garde son ancien nom', ClassLevel.objects.filter(name=PC0).exists()
      and not ClassLevel.objects.filter(name=PC).exists())
# 0004 : « 2ème Bac PC » → « 2ème Bac PC/SVT », même ligne (contenus, profils, classes suivent), avant le seeder.
call_command('migrate', 'caracteristics', '0004', verbosity=0)
check('0004 : niveau renommé, même id', ClassLevel.objects.get(pk=lv[PC].pk).name == PC
      and not ClassLevel.objects.filter(name=PC0).exists())
check('0004 : titre du cahier généré suit', Notebook.objects.get(pk=nb_pc.pk).title == f'{maths.name} - {PC}',
      Notebook.objects.get(pk=nb_pc.pk).title)
call_command('migrate', 'caracteristics', '0003', verbosity=0)
check('0004 réversible', ClassLevel.objects.get(pk=lv[PC].pk).name == PC0
      and Notebook.objects.get(pk=nb_pc.pk).title == f'{maths.name} - {PC0}')
call_command('migrate', 'caracteristics', '0004', verbosity=0)
Notebook.objects.filter(pk=nb_pc.pk).delete()
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
check('seeder après 0004 : pas de niveau en double', ClassLevel.objects.count() == 4,
      list(ClassLevel.objects.values_list('name', flat=True)))


def noms(c):
    return sorted(Content.objects.get(pk=c.pk).chapters.values_list('name', flat=True))


def noms_th(c):
    return sorted(Content.objects.get(pk=c.pk).theorems.values_list('name', flat=True))


ecarts = P.ecarts_base()
check('base = programme (chapitres)', ecarts['chapitres'] == [], ecarts['chapitres'])
check('base = programme (théorèmes)', ecarts['theoremes'] == [], ecarts['theoremes'])
for niveau, chapitres in P.PROGRAMME.items():
    got = set(Chapter.objects.filter(class_levels=lv[niveau], subject=maths).values_list('name', flat=True))
    check(f'{niveau} : exactement ses {len(chapitres)} chapitres', got == {c['nom'] for c in chapitres}, got ^ {c['nom'] for c in chapitres})
check('ordre des niveaux', [lv.name for lv in ClassLevel.objects.order_by('order')] == [TC, SM1, SM2, PC]
      and list(ClassLevel.objects.order_by('order').values_list('order', flat=True)) == [1, 2, 3, 4])
check('Physique et Chimie non touchées', Chapter.objects.filter(subject=physique, class_levels=lv[SM2]).count() == 8
      and noms(C[22]) == ['Lois de Newton'])
check('« Espaces vectoriels » gardé en 2ème Bac SM', Chapter.objects.filter(name='Espaces vectoriels', class_levels=lv[SM2]).exists()
      and noms(C[4]) == ['Espaces vectoriels', 'Structures algébriques']
      and sorted(ch('Espaces vectoriels').theorems.values_list('name', flat=True))
      == ["Base et dimension d'un espace vectoriel", 'Familles libres et génératrices', 'Sous-espaces vectoriels'])

# Contenus
check('aucun contenu supprimé ni enregistré', Content.objects.count() == nb_contenus
      and dict(Content.objects.values_list('id', 'updated_at')) == updated)
check('scission, 1ère seule : remplacé', noms(C[1]) == [TRIGO], noms(C[1]))
check('scission, TC + 1ère : ancien gardé, nouveau ajouté', noms(C[2]) == ['Produit scalaire dans le plan', ANA_PS], noms(C[2]))
check('scission, TC seul : inchangé', noms(C[3]) == ["Géométrie dans l'espace"])
check('scission, examen national de 1ère : remplacé', noms(C[23]) == [ANA_ESP], noms(C[23]))
check('scission, contenu sans niveau : inchangé', noms(C[21]) == ['Calcul trigonométrique'])
check('sous-domaine du nouveau chapitre ajouté', set(Content.objects.get(pk=C[1].pk).subfields.values_list('name', flat=True)) == {'Analyse'})
check('détachement, 2ème SM + PC : Dénombrement gardé, Probabilités ajouté', noms(C[5]) == ['Dénombrement', 'Probabilités'], noms(C[5]))
check('détachement, 2ème SM seul : Probabilités', noms(C[6]) == ['Probabilités'] and noms(L1) == ['Probabilités'], noms(C[6]))
check('primitives : entièrement étiqueté → Fonctions primitives seul', noms(C[7]) == ['Fonctions primitives'], noms(C[7]))
check('primitives : une question sans notion → les deux', noms(C[8]) == ['Calcul intégral', 'Fonctions primitives'], noms(C[8]))
check('primitives : notion d\'intégrale → les deux', noms(C[9]) == ['Calcul intégral', 'Fonctions primitives'], noms(C[9]))
check('primitives : seulement le théorème → ajouté', noms(C[10]) == ['Calcul intégral', 'Fonctions primitives'], noms(C[10]))
check('primitives : intégrale seule → inchangé', noms(C[11]) == ['Calcul intégral'])
check('fusion TAF → Dérivation (chapitre et théorème)', noms(C[12]) == ['Dérivation et étude des fonctions']
      and noms_th(C[12]) == ['Théorème des accroissements finis (TAF)'], (noms(C[12]), noms_th(C[12])))
check('ln/exp : notions du logarithme → Fonctions logarithmiques, les deux théorèmes', noms(C[13]) == ['Fonctions logarithmiques']
      and noms_th(C[13]) == ["Dérivée et propriétés de l'exponentielle", 'Dérivée et propriétés du logarithme'], (noms(C[13]), noms_th(C[13])))
check('ln/exp : exponentielle → Fonctions exponentielles', noms(C[14]) == ['Fonctions exponentielles'])
check('ln/exp : mélange → les deux', noms(C[15]) == ['Fonctions exponentielles', 'Fonctions logarithmiques'])
check('produit vectoriel : entièrement étiqueté → Vecteurs de l\'espace retiré', noms(C[16]) == ['Produit vectoriel'], noms(C[16]))
check('produit vectoriel : théorème seul → ajouté', noms(C[17]) == ["Produit scalaire dans l'espace", 'Produit vectoriel'], noms(C[17]))
check('produit vectoriel : 1ère + PC → chapitre de l\'espace gardé (justifié par le PC)',
      noms(C[18]) == ["Produit scalaire dans l'espace", 'Produit vectoriel'], noms(C[18]))
check('théorème supprimé avec remplaçant', noms_th(C[19]) == ["Image d'un intervalle par une fonction continue"])
check('théorèmes fusionnés, renommés, supprimés sans remplaçant',
      noms_th(C[20]) == ['Arrangements et combinaisons', 'Formule de Moivre', "Équation y' = ay + b"], noms_th(C[20]))
check('doublon d\'administrateur fusionné', noms(C[24]) == ['Probabilités'])
check('renommage en place (même identifiant)', th('Formule de Moivre').id == th_avant['Théorème de Moivre']
      and th("Matrices carrées d'ordre 2 et 3").id == th_avant['Applications linéaires et matrices'])
check('théorèmes retirés supprimés', not Theorem.objects.filter(name__in=[
    "Applications du TAF à l'étude des fonctions", 'Équations linéaires du premier ordre', 'Méthode de variation de la constante',
    'Formule de combinaison et permutation', 'Théorème de Bolzano-Weierstrass', 'Loi des grands nombres', 'Théorème central limite',
    'Produit scalaire et propriétés', "Dérivée et propriétés du logarithme et de l'exponentielle", 'Théorème de Moivre']).exists())

# Suppressions finales
check('chapitre TAF supprimé (plus aucune référence)', not Chapter.objects.filter(pk=avant[TAF_CH]).exists())
lnexp = Chapter.objects.filter(pk=avant[LNEXP]).first()
check('ancien ln/exp gardé (quiz), renommé et détaché', lnexp is not None
      and lnexp.name == f'{LNEXP} (ancien #{lnexp.id})' and not lnexp.class_levels.exists()
      and SkillQuestion.objects.get(pk=sq[4].pk).chapter_id == lnexp.id)
dupe = Chapter.objects.filter(pk=dup.pk).first()
check('doublon en conflit de parcours : gardé, renommé, détaché', dupe is not None and dupe.name == f'probabilités (ancien #{dup.pk})'
      and not dupe.class_levels.exists() and PathChapter.objects.get(pk=pc5b.pk).chapter_id == dup.pk, getattr(dupe, 'name', None))
check('lignes d\'administrateurs laissées', Chapter.objects.filter(pk=admin_ch.pk, name='Exercices de synthèse').exists()
      and Theorem.objects.filter(pk=admin_th.pk, name='Lemme maison').exists())

# Références
der, proba, trigo = ch('Dérivation et étude des fonctions'), ch('Probabilités'), ch(TRIGO)


def rl_noms(k):
    return sorted(RevisionList.objects.get(pk=RL[k].pk).chapters.values_list('name', flat=True))


def ut_noms(k):
    return sorted(UpcomingTest.objects.get(pk=UT[k].pk).chapters.values_list('name', flat=True))


check('listes : niveau 1ère → remplacé', rl_noms(1) == [TRIGO])
check('listes : niveau ambigu → ajouté', rl_noms(2) == ['Produit scalaire dans le plan', ANA_PS]
      and rl_noms(7) == ['Calcul trigonométrique', TRIGO], (rl_noms(2), rl_noms(7)))
check('listes : côté Tronc commun → rien', rl_noms(3) == ["Géométrie dans l'espace"])
check('listes : détachement 2ème SM → remplacé ; 1ère → rien', rl_noms(4) == ['Probabilités'] and rl_noms(5) == ['Dénombrement'])
check('listes : fusion TAF', rl_noms(6) == ['Dérivation et étude des fonctions'])
check('devoirs : niveau du devoir, du profil, ambigu', ut_noms(1) == ['Dérivation et étude des fonctions', 'Probabilités']
      and ut_noms(2) == [TRIGO] and ut_noms(3) == ['Dénombrement', 'Probabilités'], (ut_noms(1), ut_noms(2), ut_noms(3)))
check('astuce de concours : scission ajoutée, fusion remplacée',
      sorted(tip.chapters.values_list('name', flat=True)) == ['Calcul trigonométrique', 'Dérivation et étude des fonctions', TRIGO])
check('quiz : fusion repointée, scission et détachement laissés',
      SkillQuestion.objects.get(pk=sq[1].pk).chapter_id == der.id
      and SkillQuestion.objects.get(pk=sq[2].pk).chapter_id == avant['Calcul trigonométrique']
      and SkillQuestion.objects.get(pk=sq[3].pk).chapter_id == avant['Dénombrement'])
a2r = SkillAssessment.objects.get(pk=a2.pk)
check('résultats de quiz repliés (score, temps, tentatives, niveau, réponses)', not SkillAssessment.objects.filter(pk=a1.pk).exists()
      and (a2r.score, a2r.max_score, a2r.time_spent, a2r.attempts, a2r.level, a2r.previous_score) == (8, 10, 80, 2, 'advanced', 2)
      and a2r.answers == {'1': 0, '9': 1} and a2r.completed_at == a2.completed_at
      and SkillAssessment.objects.get(pk=a3.pk).chapter_id == der.id, (a2r.score, a2r.max_score, a2r.level, a2r.answers))
check('parcours : fusion et scission (niveau 1ère seul) repointées, autres laissés',
      PathChapter.objects.get(pk=pc1.pk).chapter_id == der.id and PathChapter.objects.get(pk=pc2.pk).chapter_id == trigo.id
      and PathChapter.objects.get(pk=pc3.pk).chapter.name == 'Produit scalaire dans le plan'
      and PathChapter.objects.get(pk=pc4.pk).chapter.name == 'Dénombrement')
jc = ConcoursExam.objects.get(pk=exam.pk).json_content['questions']
check('concours : sujets, sessions et réponses repointés', [x['chapter_id'] for x in jc] == [der.id, der.id, avant['Limites et continuité']]
      and SimulationSession.objects.get(pk=sess.pk).questions_snapshot[0]['question']['chapter_id'] == der.id
      and SimulationAnswer.objects.get(session=sess).chapter_id == der.id, jc)

# Cahiers


def sections(nb):
    return list(NotebookSection.objects.filter(notebook=nb).order_by('order').values_list('chapter__name', flat=True))


# Depuis 0003, la dérivation passe avant les suites en 2ème Bac SM : notebooks 0004 renumérote ensuite les sections
# (pas ici : la suite rejoue 0003, qui doit rester sans écriture). Sections du programme, dans son ordre après tri.
check('cahier 2ème SM : sections = programme, dans son ordre', sorted(sections(nb2), key=lambda n: P.rang(SM2)[n])
      == [c['nom'] for c in P.PROGRAMME[SM2]], sections(nb2))
check('cahier 1ère SM : section repointée, Produit vectoriel créé, ordre du programme',
      sections(nb1) == [c['nom'] for c in P.PROGRAMME[SM1]] and NotebookSection.objects.get(pk=s_trig.pk).chapter_id == trigo.id, sections(nb1))
check('cahier Tronc commun : ordre du programme', sections(nbtc) == [c['nom'] for c in P.PROGRAMME[TC]], sections(nbtc))
s_pro = NotebookSection.objects.get(pk=s_pro.pk)
entrees = list(NotebookLessonEntry.objects.filter(section=s_pro).order_by('page_order').values_list('lesson_id', 'page_order'))
check('cahier : leçons repliées sans doublon, notes jointes', not NotebookSection.objects.filter(pk=s_den.pk).exists()
      and entrees == [(L2.id, 0), (L1.id, 1)] and s_pro.user_notes == 'notes P\n\n— Dénombrement —\nnotes D', (entrees, s_pro.user_notes))
check('cahier : ancienne section ln/exp repliée dans Fonctions logarithmiques', NotebookLessonEntry.objects.filter(
    section__notebook=nb2, section__chapter__name='Fonctions logarithmiques', lesson=L4).exists())

# Temps, Pilotage, IA, rapport
check('temps par chapitre/théorème/domaine reconstruit exactement', temps_reel() == temps_attendu())
check('temps : plus rien sur les chapitres et théorèmes supprimés', not TaxonomyTimeSpent.objects.filter(
    taxonomy_type='chapter', object_id=avant[TAF_CH]).exists())
U = {u.name: u for u in UsageDaily.objects.filter(kind='filtre')}
k_der = f'exercise:chapitre:{der.id}'
check('Pilotage : filtres fusionnés (somme, max des visiteurs), renommés, supprimés',
      (U[k_der].count, U[k_der].visitors, U[k_der].anon_count) == (5, 2, 1) and f'exam:chapitre:{der.id}' in U
      and f'exercise:chapitre:{avant[TAF_CH]}' not in U
      and f"exercise:theoreme:{th_avant['Loi des grands nombres']}" not in U
      and f"exercise:theoreme:{th("Image d'un intervalle par une fonction continue").id}" in U
      and f"lesson:chapitre:{avant['Dénombrement']}" in U, sorted(U))
fiches = IAJob.objects.get(pk=job.pk).result['fiches']
attendu = [
    {'cle': 'a', 'niveaux': [SM1], 'chapitres': [TRIGO], 'theoremes': ['Formule de Moivre']},
    {'cle': 'b', 'niveaux': [SM2, PC0], 'chapitres': ['Dénombrement', 'Probabilités', 'Dérivation et étude des fonctions'],
     'theoremes': []},
    {'cle': 'c', 'niveaux': [TC, SM1], 'chapitres': ['Calcul trigonométrique', TRIGO, 'Fonctions logarithmiques',
                                                      'Fonctions exponentielles']}]
check('fiches IA en attente réécrites', fiches == attendu, fiches)
check('fiches IA : même traduction que programme.traduire_noms (import)', all(
    P.traduire_noms(f['chapitres'], f.get('theoremes', []), f['niveaux'])[:2] == (a['chapitres'], a.get('theoremes', []))
    for f, a in zip(FICHES, attendu)))
check('fiche IA publiée non touchée', IAJob.objects.get(pk=job_publie.pk).result['fiches'] == FICHES
      and IAJob.objects.get(pk=job.pk).result['doutes'] == ['x'])
ev = SystemEvent.objects.filter(event_type='migration').order_by('-id').first()
r = ev.metadata if ev else {}
ops = {(o['op'], o.get('de') or o.get('chapitre')): o for o in r.get('operations', [])}
check('rapport enregistré (SystemEvent)', ev is not None and SystemEvent.objects.filter(event_type='migration').count() == 1
      and 'Programme officiel' in ev.description)
check('rapport : matières hors maths en tête, avec leurs contenus', len(r.get('hors_maths', [])) == 9 and next(
    h for h in r['hors_maths'] if h['chapitre'] == 'Lois de Newton')['contenus'] == 1, r.get('hors_maths'))
check('rapport : quiz à réaffecter listés', [x['id'] for x in ops[('scission', 'Calcul trigonométrique')].get('quiz_a_reaffecter', [])] == [sq[2].pk]
      and [x['id'] for x in ops[('detachement', 'Dénombrement')].get('quiz_a_reaffecter', [])] == [sq[3].pk]
      and ops[('detachement', 'Dénombrement')].get('parcours_laisses') == [pc4.pk])
check('rapport : administrateurs, sans niveau, conflits', {x['nom'] for x in r['administrateurs']['chapitres']} == {'Exercices de synthèse'}
      and {x['nom'] for x in r['administrateurs']['theoremes']} == {'Lemme maison'} and C[21].pk in r['contenus_sans_niveau']
      and {x['id'] for x in r['suppressions']['chapitres_gardes']} == {avant[LNEXP], dup.pk}, r.get('suppressions'))
check('rapport : règles primitives et produit vectoriel listées', set(ops[('primitives', 'Calcul intégral')]['contenus_remplaces']) == {C[7].pk}
      and set(ops[('primitives', 'Calcul intégral')]['contenus_ajoutes']) == {C[8].pk, C[9].pk, C[10].pk}
      and set(ops[('produit_vectoriel', None)]['contenus_ajoutes']) == {C[16].pk, C[17].pk, C[18].pk})

# ── Deuxième passage : rien ne change ; seeder rejoué : rien ne change
snap = instantane()
apps_0003 = MigrationExecutor(connection).loader.project_state(('caracteristics', '0003_programme_officiel')).apps
donnees = importlib.import_module('apps.caracteristics.migrations.0003_programme_officiel').DONNEES
# Base déjà renommée par 0004 : les données figées (ancien nom du niveau) ne trouvent plus ce niveau et n'y écrivent rien.
r2 = appliquer(apps_0003, donnees, log=silence)
check('2e passage de la migration : aucune écriture', r2['changements'] == 0, r2.get('changements'))
check('2e passage : base identique', instantane() == snap)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
check('seeder rejoué : base identique', instantane() == snap)

print(f'\n{sum(results)}/{len(results)} vérifications OK')
sys.exit(0 if all(results) else 1)
