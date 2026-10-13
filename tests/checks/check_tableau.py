"""« Ma progression » en tableau de bord (apps/users/tableau.py) : questions par jour, notes d'examens (par examen et
par chapitre, dans le temps), temps chapitre › contenu, périodes et période précédente, détail d'un jour."""
import os
import runpy
import sys
import tempfile
from datetime import datetime, time, timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-tableau.sqlite3')
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
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.interactions.models import AssessmentEvent, StudyTimeDay  # noqa: E402
from apps.things.models import Content  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


author = User.objects.create_user('Fidni', 'f@x.fr', None)
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
autre = User.objects.create_user('autre', 'a@x.fr', 'Motdepasse-solide-42')
sm = ClassLevel.objects.get(name='2ème Bac SM')
eleve.profile.class_level = sm
eleve.profile.save()
lim = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
der = Chapter.objects.filter(name__startswith='Dérivation', class_levels=sm).first()
suites = Chapter.objects.filter(class_levels=sm, name__icontains='suite').exclude(id__in=[lim.id, der.id]).first()
TVI, TAF = 'Théorème des valeurs intermédiaires (TVI)', 'Théorème des accroissements finis (TAF)'
today = timezone.localdate()


def q(qid, points, theoremes=()):
    return {'id': qid, 'type': 'question', 'points': points, 'content': {'html': '<p>?</p>'}, 'meta': {'theorems': list(theoremes)}}


def make(kind, title, chapters, blocks):
    c = Content.objects.create(type=kind, title=title, author=author, difficulty='medium',
                               json_content={'version': '2.1', 'blocks': blocks})
    c.class_levels.set([sm])
    c.chapters.set(chapters)
    return c


def ev(c, path, status, days_ago, hour=10, user=eleve):
    at = timezone.make_aware(datetime.combine(today - timedelta(days=days_ago), time(hour)))
    AssessmentEvent.objects.create(user=user, object_id=c.id, question_path=path, status=status, at=at)


def temps(c, days_ago, seconds, user=eleve):
    StudyTimeDay.objects.create(user=user, object_id=c.id, date=today - timedelta(days=days_ago), seconds=seconds)


# Examen sur Limites (q1, TVI) et Dérivation (q2, TAF) ; q3 sans théorème : les deux chapitres. Barème 2 + 3 + 5.
exam = make('exam', 'DS 1', [lim, der], [q('q1', 2, [TVI]), q('q2', 3, [TAF]), q('q3', 5)])
exam2 = make('exam', 'DS 2 (à peine commencé)', [lim], [q('q1', 2), q('q2', 8)])
ex = make('exercise', 'Suites 1', [suites], [q('q1', 0), q('q2', 0), q('q3', 0)])

# J-10 : copie complète (14/20 ; Limites 20, Dérivation 12,5) ; J-8 : q2 réussie, même copie (moins de 3 jours) → 20.
ev(exam, 'q1', 'success', 10); ev(exam, 'q2', 'review', 10); ev(exam, 'q3', 'success', 10)  # noqa: E702
ev(exam, 'q2', 'success', 8)
# J-1 : il la refait, q1 ratée → nouvelle copie : (0 + 3 + 5) / 10 → 16 ; Limites (0 + 5) / 7 → 14,3.
ev(exam, 'q1', 'review', 1)
ev(exam2, 'q1', 'success', 1)  # 2 points sur 10 corrigés : pas de note
# Exercice J-2 : q1 réussie, q2 à revoir puis réussie (même jour : la dernière compte), q3 en partie.
ev(ex, 'q1', 'success', 2); ev(ex, 'q2', 'review', 2, hour=9); ev(ex, 'q2', 'success', 2, hour=11)  # noqa: E702
ev(ex, 'q3', 'partial', 2)
ev(ex, 'q1', None, 1)  # J-1 : évaluation retirée, ne compte pas
temps(ex, 2, 1200); temps(exam, 1, 600); temps(exam, 10, 900)  # noqa: E702
# Un autre élève : rien de ses données ne doit apparaître.
ev(ex, 'q1', 'review', 2, user=autre); temps(ex, 2, 999, user=autre)  # noqa: E702

c = APIClient()
check('visiteur : refusé', c.get('/api/stats/tableau/').status_code in (401, 403))
c.force_authenticate(eleve)
check('période invalide : refusée', c.get('/api/stats/tableau/?jours=12').status_code == 400)

r = c.get('/api/stats/tableau/?jours=30')
check('tableau 30 j', r.status_code == 200, r.status_code)
t = r.data
check('30 jours, un par jour', len(t['jours']) == 30 and t['periode']['pas'] == 'jour' and t['jours'][-1]['date'] == today.isoformat())
jour = {x['date']: x for x in t['jours']}
j2 = jour[(today - timedelta(days=2)).isoformat()]
check('jour : dernier statut de la journée (2 réussies, 1 en partie, 0 ratée)', (j2['reussies'], j2['partielles'], j2['ratees']) == (2, 1, 0), j2)
j1 = jour[(today - timedelta(days=1)).isoformat()]
check('évaluation retirée : non comptée ; temps du jour', j1['ratees'] == 1 and j1['reussies'] == 1 and j1['secondes'] == 600, j1)
check('notes : copies de l’examen (J-8 : 20, J-1 : 16), l’examen à peine commencé non noté',
      [(n['note'], n['titre']) for n in t['notes']] == [(20.0, 'DS 1'), (16.0, 'DS 1')], t['notes'])
k = t['kpis']
check('note moyenne de la période', k['note']['moyenne'] == 18.0 and k['note']['n'] == 2, k['note'])
check('temps et jours actifs', k['secondes']['total'] == 2700 and k['jours_actifs']['n'] == 4, (k['secondes'], k['jours_actifs']))
chap = {x['id']: x for x in t['chapitres']}
check('chapitres du programme, dans l’ordre', [x['id'] for x in t['chapitres']][:1] and lim.id in chap and suites.id in chap)
nl = chap[lim.id]['note']
check('note du chapitre : ses questions seulement (Limites : 20 puis 14,3)', [p['note'] for p in nl['serie']] == [20.0, 14.3]
      and nl['min'] == 14.3 and nl['max'] == 20.0 and nl['n'] == 2, nl)
nd = chap[der.id]['note']
check('Dérivation : 20 puis (3 + 5) / 8 → 20', [p['note'] for p in nd['serie']] == [20.0, 20.0], nd)
check('chapitre sans examen : pas de note', chap[suites.id]['note']['moyenne'] is None and chap[suites.id]['note']['n'] == 0)
check('questions par chapitre', (chap[suites.id]['reussies'], chap[suites.id]['partielles']) == (2, 1), chap[suites.id])
check('questions du chapitre jour par jour', chap[suites.id]['jours'] == [{'date': (today - timedelta(days=2)).isoformat(),
      'reussies': 2, 'partielles': 1, 'ratees': 0}], chap[suites.id]['jours'])
check('jours actifs marqués', j2['actifs'] == 1 and jour[(today - timedelta(days=5)).isoformat()]['actifs'] == 0)
check('liens du chapitre', chap[lim.id]['hub_url'] and chap[lim.id]['examens_url'] and chap[lim.id]['actif'])
tp = {x['id']: x for x in t['temps']}
check('temps partagé entre les chapitres d’un examen (900 + 600 → 750 chacun)', tp[lim.id]['secondes'] == 750 and tp[der.id]['secondes'] == 750
      and tp[suites.id]['secondes'] == 1200, {k_: v['secondes'] for k_, v in tp.items()})
cont = tp[lim.id]['contenus'][0]
check('temps : contenu, partage et jours', cont['id'] == exam.id and cont['partage'] == 2 and cont['url'] == f'/exams/{exam.id}'
      and [x['secondes'] for x in cont['jours']] == [900, 600], cont)

pf = {x['nom']: x for x in t['points_faibles']}
tvi = pf.get(TVI)
check('points faibles : par théorème, réussies / à revoir de la période', tvi and (tvi['reussies'], tvi['ratees']) == (1, 1)
      and tvi['taux'] == 50 and tvi['chapitre'] and tvi['chapitre']['id'] == lim.id and tvi['id'], tvi)
check('points faibles : questions encore à revoir, avec leur libellé', tvi and tvi['a_revoir'] == [{
    'id': exam.id, 'titre': 'DS 1', 'url': f'/exams/{exam.id}', 'question': 'Q1', 'statut': 'review',
    'date': (today - timedelta(days=1)).isoformat()}] and tvi['a_revoir_total'] == 1, tvi and tvi['a_revoir'])
check('points faibles : un théorème raté puis réussi depuis n’y est plus', TAF not in pf, list(pf))
r = c.get('/api/stats/tableau/?jours=7')
k = r.data['kpis']
check('7 j : la copie de J-1 seulement', [n['note'] for n in r.data['notes']] == [16.0], r.data['notes'])
check('7 j : période d’avant (copie de J-8, 900 s)', k['note']['avant'] == 20.0 and k['secondes']['avant'] == 900
      and k['questions']['avant'] == {'reussies': 3, 'partielles': 0, 'ratees': 1}, k)
r = c.get('/api/stats/tableau/?jours=0')
check('depuis le début : du premier jour d’activité, sans « avant »', r.data['periode']['debut'] == (today - timedelta(days=10)).isoformat()
      and r.data['kpis']['note']['avant'] is None and len(r.data['notes']) == 2, r.data['periode'])

r = c.get(f'/api/stats/tableau/jour/?date={(today - timedelta(days=2)).isoformat()}')
check('détail d’un jour', r.status_code == 200 and r.data['contenus'] == [{
    'id': ex.id, 'titre': 'Suites 1', 'type': 'exercise', 'url': f'/exercises/{ex.id}', 'chapitre': suites.name,
    'secondes': 1200, 'reussies': 2, 'partielles': 1, 'ratees': 0}], r.data)
check('détail d’un jour : date invalide refusée', c.get('/api/stats/tableau/jour/?date=hier').status_code == 400)

ev(ex, 'q1', 'success', 200)
r = c.get('/api/stats/tableau/?jours=0')
check('longue période : par semaine', r.data['periode']['pas'] == 'semaine' and len(r.data['jours']) <= 30
      and sum(x['reussies'] for x in r.data['jours']) == 7 and sum(x['actifs'] for x in r.data['jours']) == 5,
      (r.data['periode'], len(r.data['jours'])))

c.force_authenticate(autre)
r = c.get('/api/stats/tableau/?jours=30')
check('un autre élève : ses données seulement', r.data['notes'] == [] and r.data['kpis']['secondes']['total'] == 999
      and r.data['kpis']['questions']['ratees'] == 1, r.data['kpis'])

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
