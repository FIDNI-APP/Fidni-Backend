"""« Ma progression », la maîtrise d'abord (13/10/2026) : journal des évaluations et des aides, états des chapitres
(table de cas), scénarios d'élèves, évolution avec sa portée, prochain objectif, aperçu de l'accueil et son cache.
apps/interactions/journal.py, apps/users/maitrise.py, objectif.py, maitrise_seuils.py."""
import importlib
import os
import runpy
import sys
import tempfile
from datetime import timedelta
from types import SimpleNamespace

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-maitrise.sqlite3')
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
from django.core.cache import cache  # noqa: E402
from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.caracteristics.notions import NOTIONS  # noqa: E402
from apps.interactions.models import (AssessmentEvent, QuestionHelp, QuestionProgress, SolutionView,  # noqa: E402
                                      UpcomingTest)
from apps.things.models import Content  # noqa: E402
from apps.users import maitrise, maitrise_seuils as S, objectif  # noqa: E402
from apps.users.usage import FILTER_RE  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


today = timezone.localdate()
now = timezone.now()
ct = ContentType.objects.get_for_model(Content)
author = User.objects.create_user('Fidni', 'f@x.fr', None)
sm = ClassLevel.objects.get(name='2ème Bac SM')
CH = {name: Chapter.objects.filter(name=name, class_levels=sm).first()
      for name in ('Limites et continuité', 'Suites numériques', 'Nombres complexes', 'Probabilités', 'Calcul intégral')}
NOT = {name: list(NOTIONS[name])[:4] for name in CH}


def eleve(username, level=sm, teacher=False):
    u = User.objects.create_user(username, f'{username}@x.fr', 'Motdepasse-solide-42')
    u.profile.class_level = level
    if teacher:
        u.profile.user_type = 'teacher'
    u.profile.save()
    return u


def q(qid, skills=(), difficulty=None):
    b = {'id': qid, 'type': 'question', 'content': {'html': '<p>?</p>'}, 'meta': {'skills': list(skills)}}
    if difficulty:
        b['meta']['difficulty'] = difficulty
    return b


def make(title, chapter, blocks, kind='exercise', difficulty=None):
    c = Content.objects.create(type=kind, title=title, author=author, difficulty=difficulty,
                               json_content={'version': '2.1', 'blocks': blocks})
    c.class_levels.set([sm])
    c.chapters.set([chapter])
    return c


def jouer(user, c, path, status, days, aide='', reprise=False, source='question'):
    """Une évaluation datée : événement du journal + état courant (comme les vues, sans passer par elles)."""
    at = now - timedelta(days=days)
    AssessmentEvent.objects.create(user=user, object_id=c.id, question_path=path, status=status, aide=aide,
                                   reprise=reprise, source=source, at=at)
    if status is None:
        QuestionProgress.objects.filter(user=user, content_type=ct, object_id=c.id, question_path=path).delete()
    else:
        QuestionProgress.objects.update_or_create(user=user, content_type=ct, object_id=c.id, question_path=path,
                                                  defaults={'status': status, 'source': source})
        QuestionProgress.objects.filter(user=user, content_type=ct, object_id=c.id, question_path=path).update(
            assessed_at=at, created_at=at)
    maitrise.forget(user.id)


def evaluer(user):
    maitrise.forget(user.id)
    return maitrise.evaluer(user, user.profile.class_level)


def chap(data, name):
    return next(c for c in data['chapters'] if c['id'] == CH[name].id)


# ── 1. Table de cas : etat_du_chapitre (fonction pure) ─────────────────────────────────────────────────────────
def stats(**kw):
    base = dict(n=10, self_pct=90, pct=90, quiz_pct=None, recents_pct=None, recents_n=0, tendance=None,
                durable={'etat': 'confirmee', 'le': today - timedelta(days=2), 'a_partir_du': None, 'due': False},
                autonomie={'pct': 80, 'suivies': 6, 'sans_aide': 5, 'min': 5}, exercices_reussis=3,
                niveaux_reussis={'easy', 'medium', 'hard'}, synthese=True, notions_reussies=3, notions_dispo=4,
                notions_manquantes=[])
    base.update(kw)
    return SimpleNamespace(**base)


def etat(**kw):
    return maitrise.etat_du_chapitre(stats(**kw))


def crit(res, cle):
    return next(c for c in res[2] if c['cle'] == cle)


r = etat()
check('table : tous les critères → Maîtrisé', r[0] == 'maitrise' and all(c['etat'] == 'ok' for c in r[2]), r)
check('table : 3 questions (sans quiz) → Pas encore évalué, jamais une difficulté',
      etat(n=3, self_pct=None, pct=None)[0] == 'non_evalue' and 'point de départ' in etat(n=3, self_pct=None, pct=None)[1])
check('table : 4 questions → évalué (mais pas Maîtrisé : 6 exigées)', etat(n=4)[0] == 'bonne_voie'
      and crit(etat(n=4), 'resultats')['etat'] == 'a_faire')
check('table : 80 % sur 6 questions → Maîtrisé (limite)', etat(n=6, self_pct=80, pct=80)[0] == 'maitrise')
r79 = etat(n=6, self_pct=79, pct=79)
check('table : 79 % → En bonne voie, la raison cite le seuil', r79[0] == 'bonne_voie' and '80 %' in r79[1], r79[1])
r = etat(durable={'etat': 'n_a_pas_tenu', 'le': today - timedelta(days=1), 'a_partir_du': None, 'due': False})
check('table : acquis qui n’a pas tenu → À consolider, même à 90 %', r[0] == 'a_consolider' and 'vérification' in r[1], r[1])
check('table : 30 % sans résultats récents → À renforcer', etat(self_pct=30, pct=30)[0] == 'a_renforcer')
r = etat(self_pct=30, pct=30, recents_pct=65, recents_n=10)
check('table : 30 % mais 65 % sur les 10 dernières → En bonne voie · en progrès', r[0] == 'bonne_voie' and r[3]
      and '30 %' in r[1] and '65 %' in r[1], r)
check('table : récents 65 % sur 5 questions seulement → pas comptés (À renforcer)',
      etat(self_pct=30, pct=30, recents_pct=None, recents_n=5)[0] == 'a_renforcer')
check('table : 50 % stable → À consolider (réussite partielle)', etat(self_pct=50, pct=50)[0] == 'a_consolider'
      and 'partielle' in etat(self_pct=50, pct=50)[1])
r = etat(self_pct=50, pct=50, tendance=12)
check('table : 50 % en hausse de 12 pts → En bonne voie · en progrès', r[0] == 'bonne_voie' and r[3] and '+12' in r[1], r)
for cle, kw, attendu in [
    ('exercices', {'exercices_reussis': 1}, 'a_faire'),
    ('difficultes', {'niveaux_reussis': {'easy'}}, 'a_faire'),
    ('difficultes', {'niveaux_reussis': {'medium'}}, 'a_faire'),
    ('synthese', {'synthese': False}, 'a_faire'),
    ('notions', {'notions_reussies': 1, 'notions_dispo': 4}, 'a_faire'),
    ('durable', {'durable': {'etat': 'a_verifier', 'le': None, 'a_partir_du': today + timedelta(days=2), 'due': False}},
     'en_attente'),
    ('autonomie', {'autonomie': {'pct': 40, 'suivies': 8, 'sans_aide': 3, 'min': 5}}, 'a_faire'),
]:
    r = etat(**kw)
    check(f'table : critère « {cle} » manquant → pas Maîtrisé ({attendu})', r[0] == 'bonne_voie'
          and crit(r, cle)['etat'] == attendu, (r[0], crit(r, cle)))
check('table : une seule notion présente dans les exercices, réussie → critère rempli',
      crit(etat(notions_reussies=1, notions_dispo=1), 'notions')['etat'] == 'ok')
check('table : autonomie inconnue mais vérification réussie sans aide → critère rempli',
      crit(etat(autonomie={'pct': None, 'suivies': 2, 'sans_aide': 2, 'min': 5}), 'autonomie')['etat'] == 'ok'
      and etat(autonomie={'pct': None, 'suivies': 2, 'sans_aide': 2, 'min': 5})[0] == 'maitrise')
r = etat(autonomie={'pct': None, 'suivies': 0, 'sans_aide': 0, 'min': 5},
         durable={'etat': 'a_verifier', 'le': None, 'a_partir_du': today, 'due': True})
check('table : autonomie et durable inconnus → jamais Maîtrisé', r[0] == 'bonne_voie'
      and crit(r, 'autonomie')['etat'] == 'en_attente', r[0])

# ── 2. Journal par l'API ─────────────────────────────────────────────────────────────────────────────────────
LIM, SUI, CPX, PRO, INT = (CH[n] for n in CH)
nl = NOT['Limites et continuité']
ex = make('Limites journal', LIM, [q('q1', nl[:1], 'easy'), q('q2', nl[1:2], 'medium'), q('q3', nl[2:3], 'hard')])
lecon = Content.objects.create(type='lesson', title='Cours', author=author, json_content={'version': '2.1', 'blocks': []})
u = eleve('journal')
api = APIClient()
api.force_authenticate(u)


def evs(path=None):
    qs = AssessmentEvent.objects.filter(user=u, object_id=ex.id)
    return list(qs.filter(question_path=path).order_by('at', 'id') if path else qs.order_by('at', 'id'))


r = api.post(f'/api/contents/{ex.id}/assess_question/', {'question_path': 'q1', 'status': 'success'}, format='json')
e = evs('q1')
check('journal : une évaluation → un événement (sans aide, rien avant)', r.status_code == 200 and len(e) == 1
      and e[0].status == 'success' and e[0].previous is None and e[0].aide == '' and not e[0].reprise, [(x.status, x.aide) for x in e])
api.post(f'/api/contents/{ex.id}/assess_question/', {'question_path': 'q1', 'status': 'success'}, format='json')
check('journal : même statut redonné aussitôt → rien de plus', len(evs('q1')) == 1)
api.post(f'/api/contents/{ex.id}/assess_question/', {'question_path': 'q1', 'status': 'review'}, format='json')
e = evs('q1')
check('journal : clic corrigé dans les 5 minutes → fusionné', len(e) == 1 and e[0].status == 'review' and e[0].previous is None,
      [(x.status, x.previous) for x in e])
api.post(f'/api/contents/{ex.id}/remove_assessment/', {'question_path': 'q1'}, format='json')
check('journal : retour à l’état d’avant dans les 5 minutes → l’observation disparaît', evs('q1') == [])
api.post(f'/api/contents/{ex.id}/assess_question/', {'question_path': 'q1', 'status': 'partial'}, format='json')
AssessmentEvent.objects.filter(user=u, object_id=ex.id, question_path='q1').update(at=now - timedelta(days=1))
api.post(f'/api/contents/{ex.id}/assess_question/', {'question_path': 'q1', 'status': 'success'}, format='json')
e = evs('q1')
check('journal : un jour après, un changement → nouvel événement avec le statut d’avant', len(e) == 2
      and (e[1].status, e[1].previous) == ('success', 'partial'), [(x.status, x.previous) for x in e])
AssessmentEvent.objects.filter(user=u, object_id=ex.id).update(at=now - timedelta(days=1))
api.post(f'/api/contents/{ex.id}/remove_assessment/', {'question_path': 'q1'}, format='json')
e = evs('q1')
check('journal : évaluation retirée → événement « retirée » (statut vide)', e[-1].status is None and e[-1].previous == 'success')
r = api.post(f'/api/contents/{ex.id}/assess_many/', {'assessments': {'q2': 'success', 'q3': 'success'}, 'source': 'tout'},
             format='json')
e2, e3 = evs('q2'), evs('q3')
check('journal : « Tout réussi » → un événement par question, source « tout »', r.status_code == 200 and len(e2) == 1
      and len(e3) == 1 and e2[0].source == 'tout' and e3[0].status == 'success')
AssessmentEvent.objects.filter(user=u, object_id=ex.id).update(at=now - timedelta(days=1))
api.post(f'/api/contents/{ex.id}/assess_many/', {'assessments': {'q2': None}}, format='json')
check('journal : « Tout réussi » annulé (null) → événement « retirée »', evs('q2')[-1].status is None)
r = api.post(f'/api/contents/{ex.id}/validate_solution/', {'question_path': 'q1', 'validation': 'compatible'}, format='json')
check('validate_solution sur une question pas évaluée : 404, aucune ligne sans statut', r.status_code == 404
      and not QuestionProgress.objects.filter(user=u, object_id=ex.id, question_path='q1').exists(), r.status_code)
r = api.post(f'/api/contents/{ex.id}/validate_solution/', {'question_path': 'q3', 'validation': 'compatible'}, format='json')
check('validate_solution sur une question évaluée : enregistrée, statut gardé', r.status_code == 200
      and QuestionProgress.objects.get(user=u, object_id=ex.id, question_path='q3').solution_validation == 'compatible'
      and QuestionProgress.objects.get(user=u, object_id=ex.id, question_path='q3').status == 'success')
avant_vide = api.get('/api/stats/progression/').data
QuestionProgress.objects.create(user=u, content_type=ct, object_id=ex.id, question_path='q1', status='')
maitrise.forget(u.id)
apres_vide = api.get('/api/stats/progression/').data
check('une ancienne ligne sans statut ne compte plus comme un échec', chap(apres_vide, 'Limites et continuité')['questions']
      == chap(avant_vide, 'Limites et continuité')['questions'] and apres_vide['summary']['questions']
      == avant_vide['summary']['questions'], (chap(apres_vide, 'Limites et continuité')['questions'],))
QuestionProgress.objects.filter(user=u, status='').delete()

# ── 3. Aides (indication, solution) ──────────────────────────────────────────────────────────────────────────
ex2 = make('Limites aides', LIM, [q('a', nl[:1], 'medium'), q('b', nl[1:2], 'medium'), q('c', nl[2:3], 'medium')])
for _ in range(2):
    r = api.post(f'/api/contents/{ex2.id}/aide/', {'path': 'a', 'kind': 'indice'}, format='json')
h = QuestionHelp.objects.filter(user=u, object_id=ex2.id)
check('aide : indication ouverte deux fois le même jour → une ligne, compte 2', r.status_code == 204 and h.count() == 1
      and h.first().count == 2 and h.first().kind == 'indice', [(x.question_path, x.kind, x.count) for x in h])
check('aide : type inconnu → 400', api.post(f'/api/contents/{ex2.id}/aide/', {'path': 'a', 'kind': 'triche'},
                                           format='json').status_code == 400)
check('aide : question inconnue → 400', api.post(f'/api/contents/{ex2.id}/aide/', {'path': 'zz', 'kind': 'indice'},
                                                format='json').status_code == 400)
check('aide : une leçon → 400', api.post(f'/api/contents/{lecon.id}/aide/', {'path': '*', 'kind': 'solution'},
                                        format='json').status_code == 400)
check('aide : visiteur → refusé', APIClient().post(f'/api/contents/{ex2.id}/aide/', {'path': 'a', 'kind': 'indice'},
                                                  format='json').status_code in (401, 403))
api.post(f'/api/contents/{ex2.id}/assess_question/', {'question_path': 'a', 'status': 'success'}, format='json')
check('aide : réussite après une indication → aide « indice »',
      AssessmentEvent.objects.get(user=u, object_id=ex2.id, question_path='a').aide == 'indice')
api.post(f'/api/contents/{ex2.id}/assess_question/', {'question_path': 'b', 'status': 'success'}, format='json')
check('aide : réussite sans rien ouvrir → aide vide (« sans aide »)',
      AssessmentEvent.objects.get(user=u, object_id=ex2.id, question_path='b').aide == '')
r = api.post(f'/api/contents/{ex2.id}/aide/', {'path': '', 'kind': 'solution'}, format='json')
check('aide : « toutes les solutions » → question « * », et « solution vue » du contenu', r.status_code == 204
      and QuestionHelp.objects.filter(user=u, object_id=ex2.id, question_path='*', kind='solution').exists()
      and SolutionView.objects.filter(user=u, object_id=ex2.id).exists())
api.post(f'/api/contents/{ex2.id}/assess_question/', {'question_path': 'c', 'status': 'success'}, format='json')
check('aide : « * » vaut pour toutes les questions → aide « solution »',
      AssessmentEvent.objects.get(user=u, object_id=ex2.id, question_path='c').aide == 'solution')
ex3 = make('Limites sous la solution', LIM, [q('a', nl[:1])])
api.post(f'/api/contents/{ex3.id}/assess_question/', {'question_path': 'a', 'status': 'success', 'source': 'apres_solution'},
         format='json')
check('aide : réponse sous la solution ouverte → aide « solution »',
      AssessmentEvent.objects.get(user=u, object_id=ex3.id).aide == 'solution')
from apps.things.views import AideThrottle  # noqa: E402
check('aide : limite de débit', AideThrottle.rate == '300/hour')

# ── 4. Reprise de l'existant (migration 0024) ────────────────────────────────────────────────────────────────
rep = eleve('reprise')
for path, st, src in (('q1', 'success', 'question'), ('q2', 'review', 'apres_solution'), ('q3', '', 'question')):
    QuestionProgress.objects.create(user=rep, content_type=ct, object_id=ex.id, question_path=path, status=st, source=src)
QuestionProgress.objects.filter(user=rep).update(assessed_at=now - timedelta(days=20))
m0024 = importlib.import_module('apps.interactions.migrations.0024_journal_reprise')
n1 = m0024.reprendre_existant(QuestionProgress, AssessmentEvent)
ev_rep = {e.question_path: e for e in AssessmentEvent.objects.filter(user=rep)}
check('reprise : un événement par évaluation, daté, aide inconnue, sans les lignes vides', set(ev_rep) == {'q1', 'q2'}
      and ev_rep['q1'].reprise and ev_rep['q1'].aide is None and ev_rep['q2'].aide == 'solution'
      and (now - ev_rep['q1'].at).days == 20, {k: (v.aide, v.reprise) for k, v in ev_rep.items()})
check('reprise : relancée, n’ajoute rien', m0024.reprendre_existant(QuestionProgress, AssessmentEvent) == 0 and n1 >= 2, n1)

# ── 5. Scénarios d'élèves ────────────────────────────────────────────────────────────────────────────────────
ns = NOT['Suites numériques']
s_easy = make('Suites facile', SUI, [q('q1', ns[:1]), q('q2', ns[:1]), q('q3', ns[1:2])], difficulty='easy')
s_med = make('Suites moyen', SUI, [q('q1', ns[1:2]), q('q2', ns[2:3]), q('q3', ns[2:3])], difficulty='medium')
s_hard = make('Suites difficile', SUI, [q('q1', ns[3:4]), q('q2', ns[2:3])], difficulty='hard')
s_new = [make(f'Suites jamais fait {i}', SUI, [q('q1', ns[:1]), q('q2', ns[1:2])], difficulty=d)
         for i, d in enumerate(('easy', 'medium', 'medium', 'hard'))]
s_old = [make(f'Suites ancien {i}', SUI, [q('q1', ns[:1]), q('q2', ns[1:2]), q('q3', ns[2:3])], difficulty='medium')
         for i in range(4)]

# a) Progresse malgré une moyenne faible : 12 échecs il y a 35 à 45 jours, puis 7 réussites sur 9 récemment.
a = eleve('progres')
for i, c in enumerate(s_old):
    for path in ('q1', 'q2', 'q3'):
        jouer(a, c, path, 'failed', 45 - i * 3)
for c, path, st in [(s_easy, 'q1', 'success'), (s_easy, 'q2', 'success'), (s_easy, 'q3', 'failed'),
                    (s_med, 'q1', 'success'), (s_med, 'q2', 'success'), (s_med, 'q3', 'success'),
                    (s_hard, 'q1', 'failed'), (s_hard, 'q2', 'success'), (s_new[0], 'q1', 'success')]:
    jouer(a, c, path, st, 8)
x = chap(evaluer(a), 'Suites numériques')
check('scénario « progresse malgré une moyenne faible » → En bonne voie · en progrès', x['etat'] == 'bonne_voie'
      and x['en_progres'] and x['pct'] < S.SEUIL_RENFORCER and x['recents']['pct'] >= S.SEUIL_BONNE_VOIE,
      (x['etat'], x['pct'], x['recents'], x['raison']))

# b) Bonnes notes, mais la solution toujours ouverte : jamais Maîtrisé, autonomie « avec aide », objectif « sans aide ».
b = eleve('corrections')
for days, (c, paths) in zip((10, 7, 4), ((s_easy, ('q1', 'q2', 'q3')), (s_med, ('q1', 'q2', 'q3')), (s_hard, ('q1', 'q2')))):
    for path in paths:
        jouer(b, c, path, 'success', days, aide='solution')
db = evaluer(b)
x = chap(db, 'Suites numériques')
check('scénario « bonnes notes mais corrections ouvertes » → pas Maîtrisé', x['etat'] == 'bonne_voie'
      and x['pct'] == 100 and x['durable']['etat'] == 'a_verifier', (x['etat'], x['durable']))
check('… autonomie : 0 % sans aide, affichée (8 réussites suivies)', x['autonomie']['seul']['pct'] == 0
      and x['autonomie']['seul']['suivies'] == 8 and crit((0, 0, x['criteres']), 'autonomie')['etat'] == 'a_faire',
      x['autonomie'])
ob = db['objectif']
check('… objectif : vérifier sans indice ni solution', ob and ob['type'] == 'verifier' and 'sans indice ni solution' in ob['phrase']
      and ob['chapitre']['id'] == SUI.id, ob and (ob['type'], ob['phrase']))
ex_b = objectif.exercices(b, ob, sm)
check('… exercices de vérification : jamais faits, 3 au plus', 0 < len(ex_b) <= S.VERIFIER_EXERCICES
      and not {r['id'] for r in ex_b} & {s_easy.id, s_med.id, s_hard.id}, [r['title'] for r in ex_b])

# c) Nouvel élève sans historique.
cnew = eleve('nouveau')
dc = evaluer(cnew)
check('scénario « nouvel élève » → tout est « Pas encore évalué », pas de chiffre inventé',
      all(c['etat'] == 'non_evalue' for c in dc['chapters']) and dc['apercu']['maitrise'] is None
      and dc['apercu']['chapitres']['evalues'] == 0 and not dc['apercu']['evolution']['mesurable']
      and dc['apercu']['evolution']['delta'] is None, dc['apercu'])
check('… objectif : s’évaluer sur un chapitre qui a des exercices', dc['objectif']['type'] == 'evaluer'
      and next(c for c in dc['chapters'] if c['id'] == dc['objectif']['chapitre']['id'])['contents'] > 0,
      dc['objectif'] and dc['objectif']['type'])
ex_c = objectif.exercices(cnew, dc['objectif'], sm)
check('… point de départ : 3 exercices, le premier facile', len(ex_c) <= S.EVALUER_EXERCICES and ex_c
      and ex_c[0]['difficulty'] in ('easy', None), [(r['title'], r['difficulty']) for r in ex_c])

# d) Perd un acquis : 6 réussites (moyen) il y a 12 jours, puis un échec (moyen) il y a 5 jours.
dd = eleve('rechute')
for c in s_old[:2]:
    for path in ('q1', 'q2', 'q3'):
        jouer(dd, c, path, 'success', 12)
jouer(dd, s_med, 'q1', 'review', 5)
x = chap(evaluer(dd), 'Suites numériques')
check('scénario « perd un acquis » → À consolider malgré 86 %', x['etat'] == 'a_consolider'
      and x['durable']['etat'] == 'n_a_pas_tenu' and x['pct'] >= S.SEUIL_MAITRISE, (x['etat'], x['pct'], x['durable']))
jouer(dd, s_hard, 'q1', 'failed', 2)
dd2 = eleve('plusdur')
for path in ('q1', 'q2', 'q3'):
    jouer(dd2, s_easy, path, 'success', 12)
jouer(dd2, s_hard, 'q1', 'failed', 5)
x = chap(evaluer(dd2), 'Suites numériques')
check('… échouer plus difficile que ce qu’on avait réussi n’est pas une rechute', x['durable']['etat'] != 'n_a_pas_tenu', x['durable'])

# e) DS dans 3 jours : l'objectif porte sur un chapitre du DS, même si un autre est plus faible.
e = eleve('ds')
nc = NOT['Nombres complexes']
cx = make('Complexes 1', CPX, [q(f'q{i}', nc[:1], 'medium') for i in range(5)])
for i in range(5):
    jouer(e, cx, f'q{i}', 'failed', 3)  # Nombres complexes : À renforcer, hors du DS
for path in ('q1', 'q2', 'q3'):
    jouer(e, s_med, path, 'success', 2)
jouer(e, s_easy, 'q1', 'success', 2)
t = UpcomingTest.objects.create(user=e, kind='ds', class_level=sm, date=today + timedelta(days=3))
t.chapters.set([SUI, PRO])
de = evaluer(e)
check('scénario « DS dans 3 jours » → objectif sur un chapitre du DS', de['objectif']['ds'] and de['objectif']['ds']['id'] == t.id
      and de['objectif']['chapitre']['id'] in (SUI.id, PRO.id) and 'DS' in de['objectif']['titre'],
      (de['objectif']['titre'], de['objectif']['chapitre']))
check('… sans DS, le chapitre À renforcer passe d’abord', objectif.choisir(e, [dict(c) for c in de['chapters']], sm, today + timedelta(days=30))['chapitre']['id'] == CPX.id)

# f) Maîtrise confirmée sans aide, sur d'autres questions, 3 jours après.
f = eleve('maitre')
for path in ('q1', 'q2', 'q3'):
    jouer(f, s_easy, path, 'success', 12, aide=None, reprise=True)
for path in ('q1', 'q2', 'q3'):
    jouer(f, s_med, path, 'success', 12, aide=None, reprise=True)
for path in ('q1', 'q2'):
    jouer(f, s_hard, path, 'success', 5, aide='')
x = chap(evaluer(f), 'Suites numériques')
check('scénario « maîtrise confirmée » → Maîtrisé', x['etat'] == 'maitrise' and x['durable']['etat'] == 'confirmee'
      and all(c['etat'] == 'ok' for c in x['criteres']), (x['etat'], [(c['cle'], c['etat']) for c in x['criteres']]))
check('… objectif « aller plus loin » sur un chapitre maîtrisé', objectif._objectif_chapitre(x, sm)['type'] == 'approfondir')

# g) Historique repris seulement (aide inconnue) : compte dans les résultats, ne confirme rien.
g = eleve('ancien')
for days, (c, paths) in zip((20, 10, 10), ((s_easy, ('q1', 'q2', 'q3')), (s_med, ('q1', 'q2', 'q3')), (s_hard, ('q1', 'q2')))):
    for path in paths:
        jouer(g, c, path, 'success', days, aide=None, reprise=True)
x = chap(evaluer(g), 'Suites numériques')
check('historique repris à 100 % → En bonne voie, « à revérifier », jamais Maîtrisé', x['etat'] == 'bonne_voie'
      and x['pct'] == 100 and x['a_confirmer'] and crit((0, 0, x['criteres']), 'durable')['etat'] == 'en_attente'
      and x['autonomie']['seul']['suivies'] == 0, (x['etat'], x['durable'], x['autonomie']))

# h) Réussite par difficulté et notions.
x = chap(evaluer(f), 'Suites numériques')
pdiff = x['reussite']['par_difficulte']
check('réussite par difficulté : facile, moyen, difficile (meta de la question sinon du contenu)',
      set(pdiff) == {'easy', 'medium', 'hard'} and pdiff['hard']['questions'] == 2, pdiff)
check('notions couvertes : réussies et présentes dans les exercices', x['notions_couvertes']['reussies'] >= 3
      and x['notions_couvertes']['dispo'] >= 4, x['notions_couvertes'])

# i) Autonomie : « je m'en passe de plus en plus » (transfert).
tr = eleve('transfert')
cs = [make(f'Proba {i}', PRO, [q('q1', NOT['Probabilités'][:1], 'medium'), q('q2', NOT['Probabilités'][1:2], 'medium')])
      for i in range(4)]
for i, c in enumerate(cs[:3]):
    jouer(tr, c, 'q1', 'success', 10 - i * 3, aide='indice')
    jouer(tr, c, 'q2', 'success', 10 - i * 3 - 0.01, aide='')
x = chap(evaluer(tr), 'Probabilités')
check('transfert : après une indication, la question suivante réussie seul (3 fois sur 3)',
      x['autonomie']['transfert']['essais'] == 3 and x['autonomie']['transfert']['reussis'] == 3
      and x['autonomie']['transfert']['visible'], x['autonomie'])

# ── 6. Évolution sur 30 jours : portée, seuils, mises en garde ────────────────────────────────────────────────
ev1 = eleve('evolution')
lims = [make(f'Lim évo {i}', LIM, [q(f'q{j}', nl[:1], 'easy') for j in range(4)], difficulty='easy') for i in range(2)]
pros = [make(f'Pro évo {i}', PRO, [q(f'q{j}', NOT['Probabilités'][:1], 'easy') for j in range(4)], difficulty='easy') for i in range(2)]
for c in (lims[0], pros[0]):
    for j in range(4):
        jouer(ev1, c, f'q{j}', 'success' if j < 2 else 'failed', 40)
for j in range(4):  # Limites : tout réussi maintenant (questions refaites), Probabilités : inchangé
    jouer(ev1, lims[0], f'q{j}', 'success', 4)
for j in range(4):
    jouer(ev1, lims[1], f'q{j}', 'success', 3)
dv = evaluer(ev1)['apercu']
evo = dv['evolution']
check('évolution : mesurée sur les chapitres évalués aux deux dates', evo['mesurable'] and evo['chapitres_compares'] == 2
      and evo['delta'] == 25, evo)
check('évolution : portée et détail renvoyés', {d['name'] for d in evo['detail']} == {'Limites et continuité', 'Probabilités'}
      and evo['questions_periode'] >= S.MIN_QUESTIONS_PERIODE, evo['detail'])
cles = {m['cle'] for m in evo['mises_en_garde']}
check('évolution : mises en garde « surtout grâce à un chapitre » et « surtout facile »', {'concentre', 'surtout_facile'} <= cles,
      evo['mises_en_garde'])
check('courbe : 8 semaines, la dernière = maîtrise estimée', len(dv['serie']) == S.SERIE_SEMAINES
      and dv['serie'][-1]['pct'] == dv['maitrise'], (dv['serie'][-1], dv['maitrise']))
check('aperçu : chapitres évalués / programme', dv['chapitres']['evalues'] == 2
      and dv['chapitres']['total'] == len([c for c in evaluer(ev1)['chapters']]), dv['chapitres'])
ev2 = eleve('debutant')
for j in range(4):
    jouer(ev2, lims[0], f'q{j}', 'success', 10)
evo2 = evaluer(ev2)['apercu']['evolution']
check('évolution : pas assez de recul → pas de chiffre, date de disponibilité', not evo2['mesurable'] and evo2['delta'] is None
      and evo2['disponible_le'] == (today + timedelta(days=20)).isoformat(), evo2)
check('évolution : estimation signalée si la période remonte avant le journal', any(
    m['cle'] == 'estimee' for m in evaluer(g)['apercu']['evolution']['mises_en_garde']) or not evaluer(g)['apercu']['evolution']['mesurable'])

# ── 7. Objectifs : à renforcer, prof, sans niveau ────────────────────────────────────────────────────────────
rf = eleve('renforcer')
for c in s_old[:2]:
    for path in ('q1', 'q2', 'q3'):
        jouer(rf, c, path, 'failed', 2)
drf = evaluer(rf)
o = drf['objectif']
check('objectif « À renforcer » : reprendre les bases, le cours d’abord', o['type'] == 'renforcer' and o['action']['kind'] == 'cours'
      and o['chapitre']['id'] == SUI.id and o['pourquoi'], o)
exs = objectif.exercices(rf, o, sm)
check('… jusqu’à 5 exercices, faciles d’abord, jamais un exercice réussi', 0 < len(exs) <= 5 and exs[0]['difficulty'] == 'easy'
      and all(r['status'] != 'success' for r in exs), [(r['title'], r['difficulty']) for r in exs])
check('… priorité : le chapitre à renforcer passe avant les autres', min(drf['chapters'], key=lambda c: c['priorite'])['id'] == SUI.id)
prof = eleve('prof', teacher=True)
check('prof : pas d’objectif', evaluer(prof)['objectif'] is None)
sans = eleve('sansniveau', level=None)
check('sans niveau : pas d’objectif, pas d’erreur', evaluer(sans)['objectif'] is None)

# ── 8. /api/stats/apercu/ (accueil) et cache ─────────────────────────────────────────────────────────────────
api.force_authenticate(rf)
maitrise.forget(rf.id)
r = api.get('/api/stats/apercu/')
check('aperçu : réponse légère, objectif sans exercices', r.status_code == 200 and r.data['objectif']['type'] == 'renforcer'
      and 'exercices' not in r.data['objectif'] and 'detail' not in r.data['apercu']['evolution']
      and set(r.data['apercu']) >= {'chapitres', 'maitrise', 'evolution', 'etats'}, r.data)
with CaptureQueriesContext(connection) as ctx:
    api.get('/api/stats/apercu/')
check('aperçu : deuxième appel servi par le cache (3 requêtes au plus)', len(ctx.captured_queries) <= 3, len(ctx.captured_queries))
avant_m = r.data['apercu']['maitrise']
for path in ('q1', 'q2', 'q3'):
    api.post(f'/api/contents/{s_new[1].id}/assess_question/', {'question_path': path if path != 'q3' else 'q2',
                                                               'status': 'success'}, format='json')
for path in ('q1', 'q2'):
    api.post(f'/api/contents/{s_new[2].id}/assess_question/', {'question_path': path, 'status': 'success'}, format='json')
r2 = api.get('/api/stats/apercu/')
check('aperçu : une évaluation efface le cache (la maîtrise change)', r2.data['apercu']['maitrise'] != avant_m,
      (avant_m, r2.data['apercu']['maitrise']))
r3 = api.get('/api/stats/progression/')
check('progression : objectif avec exercices, aperçu, régularité, champs par chapitre', r3.status_code == 200
      and isinstance(r3.data['objectif'].get('exercices'), list) and r3.data['regularite']['sur'] == S.REGULARITE_JOURS
      and {'etat', 'raison', 'criteres', 'priorite', 'durable', 'autonomie', 'reussite'} <= set(r3.data['chapters'][0])
      and 'status' in r3.data['chapters'][0] and 'mastery' in r3.data['chapters'][0], r3.status_code)
check('régularité : jours actifs (évaluations du jour)', r3.data['regularite']['jours_actifs'] >= 1
      and r3.data['regularite']['jours'][-1]['actif'], r3.data['regularite']['jours'][-1])
r = api.post('/api/revision-lists/quick_add/', {'object_ids': [s_new[3].id], 'name': 'Objectif : Suites numériques'}, format='json')
check('« En faire une fiche » : liste nommée d’après l’objectif', r.status_code in (200, 201)
      and r.data['list_name'] == 'Objectif : Suites numériques', r.data)

# ── 9. Avis « Ce diagnostic te semble juste ? » et suppression du compte ─────────────────────────────────────
check('avis : noms acceptés', all(FILTER_RE.match(n) for n in ('prog:avis:a_consolider:oui', 'prog:avis:objectif-verifier:non'))
      and not FILTER_RE.match('prog:avis:a_consolider:peut-etre'))
from apps.users.admin_dashboard import _avis_diagnostics  # noqa: E402
from apps.users.models import UsageDaily  # noqa: E402
UsageDaily.objects.create(date=today, kind=UsageDaily.KIND_FILTER, name='prog:avis:a_consolider:oui', count=3, visitors=3)
UsageDaily.objects.create(date=today, kind=UsageDaily.KIND_FILTER, name='prog:avis:a_consolider:non', count=1, visitors=1)
av = {x['sujet']: x for x in _avis_diagnostics(today - timedelta(days=7))}
check('Pilotage : accord par état', av['a_consolider']['accord'] == 75 and av['a_consolider']['total'] == 4, av)
uid = u.id
u.delete()
check('suppression du compte : journal et aides supprimés', not AssessmentEvent.objects.filter(user_id=uid).exists()
      and not QuestionHelp.objects.filter(user_id=uid).exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
