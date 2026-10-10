"""Commande « audit_usage » (apps/users/management/commands/audit_usage.py) : le rapport sort en Markdown et en
JSON sur une base peuplée, avec les bons chiffres (comptes maison exclus), et n'écrit RIEN — ni en base (nombre de
lignes de chaque table identique avant/après, aucune requête d'écriture) ni dans le cache."""
import json
import os
import runpy
import sys
import tempfile
from datetime import timedelta
from io import StringIO

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-audit-usage.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.core.cache import caches  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402
from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.utils import timezone  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Subject  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress, SolutionView, StudyTimeDay, TimeSession  # noqa: E402
from apps.notifications.models import Notification  # noqa: E402
from apps.things.models import Comment, Content, ContentDailyView, ContentReport, DifficultyFeedback  # noqa: E402
from apps.users.models import UsageDaily, ViewHistory  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


now = timezone.now()
today = timezone.localdate()
level = ClassLevel.objects.get(name='2ème Bac SM')
subject = Subject.objects.get(name='Mathématiques')
chapter = Chapter.objects.filter(class_levels=level).first()
ct = ContentType.objects.get_for_model(Content)

# ── Comptes : 3 comptes maison (exclus partout), 8 élèves, 1 prof
admin = User.objects.create_superuser('chef', 'chef@x.fr', 'Motdepasse-solide-42')
editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
tester = User.objects.create_user('fidni_test_claude', 'test@x.fr', 'Motdepasse-solide-42')
s = [User.objects.create_user(f'eleve{i}', f'eleve{i}@x.fr', 'Motdepasse-solide-42') for i in range(8)]
prof = User.objects.create_user('prof', 'prof@x.fr', 'Motdepasse-solide-42')
prof.profile.user_type = 'teacher'
prof.profile.save()
for u in s:
    u.profile.class_level = level
    u.profile.save()
s[0].profile.onboarding_completed = True
s[0].profile.onboarding_completed_at = now
s[0].profile.save()
s[5].is_active = False
s[5].save()
s[5].profile.email_verified = False
s[5].profile.save()
User.objects.filter(pk=s[6].pk).update(date_joined=now - timedelta(days=10))
User.objects.filter(pk=s[7].pk).update(date_joined=now - timedelta(days=40))

# ── Contenus
q = {'type': 'question', 'content': {'html': '<p>?</p>'}}
ex_easy = Content.objects.create(type='exercise', title='Affiché facile', difficulty='easy', author=editorial, subject=subject,
                                 json_content={'version': '2.1', 'blocks': [
                                     {**q, 'id': 'q1', 'meta': {'expected_seconds': 300, 'difficulty': 'easy'}},
                                     {**q, 'id': 'q2', 'meta': {'expected_seconds': 300}}]})
ex_med = Content.objects.create(type='exercise', title='Affiché moyen', difficulty='medium', author=editorial, subject=subject,
                                json_content={'version': '2.1', 'blocks': [{**q, 'id': 'q1'}, {**q, 'id': 'q2'}]})
exam = Content.objects.create(type='exam', title='Examen', difficulty='hard', duration_minutes=120, author=editorial,
                              subject=subject, json_content={'version': '2.1', 'blocks': [{**q, 'id': 'q1', 'points': 4}]})
lesson = Content.objects.create(type='lesson', title='Leçon jamais vue', author=editorial, subject=subject,
                                json_content={'version': '2.1', 'blocks': []})
for c in (ex_easy, ex_med, exam, lesson):
    c.class_levels.add(level)
    c.chapters.add(chapter)

# ── Travail : ex_easy raté par 6 élèves, réussi d'un clic (« Tout réussi ») par un 7e et par l'admin (exclu)
for u in s[:6]:
    for path in ('q1', 'q2'):
        QuestionProgress.objects.create(user=u, content_type=ct, object_id=ex_easy.id, question_path=path, status='review')
    Complete.objects.create(user=u, content_type=ct, object_id=str(ex_easy.id), status='review')
for u in (s[6], admin):
    for path in ('q1', 'q2'):
        QuestionProgress.objects.create(user=u, content_type=ct, object_id=ex_easy.id, question_path=path, status='success',
                                        source='tout')
QuestionProgress.objects.filter(user=s[6]).update(created_at=now - timedelta(days=2))   # J+8 : revenu la 2e semaine
QuestionProgress.objects.filter(user=s[0], question_path='q1').update(solution_validation='not-understood')
for u in s[:5]:   # ex_med : tout réussi, question par question
    for path in ('q1', 'q2'):
        QuestionProgress.objects.create(user=u, content_type=ct, object_id=ex_med.id, question_path=path, status='success')
QuestionProgress.objects.create(user=s[0], content_type=ct, object_id=exam.id, question_path='q1', status='partial')
# Chemin qui n'est plus une question de l'énoncé (contenu réorganisé) : ignoré dans la réussite.
QuestionProgress.objects.create(user=s[0], content_type=ct, object_id=ex_med.id, question_path='ancien', status='review')
# Avant le 10/10/2026 (pas encore de `source`) : deux « réussi » à la même seconde = un « Tout réussi » deviné.
for path in ('q1', 'q2'):
    QuestionProgress.objects.create(user=s[7], content_type=ct, object_id=ex_med.id, question_path=path, status='success')
QuestionProgress.objects.filter(user=s[7]).update(created_at=now.replace(year=2026, month=10, day=5))

for u in (s[0], s[1], admin):
    ViewHistory.objects.create(user=u, content_type=ct, object_id=ex_easy.id)
SolutionView.objects.create(user=s[0], content_type=ct, object_id=ex_easy.id)
SolutionView.objects.create(user=admin, content_type=ct, object_id=ex_easy.id)
for u in s[:5] + [admin]:
    DifficultyFeedback.objects.create(user=u, content=ex_easy, felt='harder', declared='easy')
ContentReport.objects.create(content=ex_easy, user=s[1], reason='solution', item_path='q1', item_label='Question 1')
ContentReport.objects.create(content=ex_easy, user=admin, reason='typo')
StudyTimeDay.objects.create(user=s[0], object_id=ex_easy.id, date=today - timedelta(days=1), seconds=900)
StudyTimeDay.objects.create(user=s[1], object_id=ex_easy.id, date=today - timedelta(days=2), seconds=3 * 3600)  # plafonné
StudyTimeDay.objects.create(user=s[2], object_id=ex_easy.id, date=today, seconds=600)
StudyTimeDay.objects.create(user=admin, object_id=ex_easy.id, date=today, seconds=60)
# Comme en production : la table du temps jour par jour date d'il y a 20 jours, et le cumul d'avant a été rattaché
# en bloc à ce jour-là (ici 5 h sur l'exercice moyen) — à écarter des durées.
from django.db.migrations.recorder import MigrationRecorder  # noqa: E402
MigrationRecorder.Migration.objects.filter(app='interactions', name='0019_studytimeday').update(applied=now - timedelta(days=20))
StudyTimeDay.objects.create(user=s[0], object_id=ex_med.id, date=today - timedelta(days=20), seconds=5 * 3600)
TimeSession.objects.create(user=s[0], content_type=ct, object_id=str(exam.id), session_duration=timedelta(minutes=100),
                           started_at=now - timedelta(minutes=100), ended_at=now, session_type='exam')
parent = Comment.objects.create(content_item=ex_easy, author=s[0], content='Je bloque')
Comment.objects.create(content_item=ex_easy, author=s[1], content='Pareil', parent=parent)
Notification.objects.create(recipient=s[0], actor=s[1], kind='reply', target=f'content:{ex_easy.id}', title='Réponse',
                            link=f'/exercises/{ex_easy.id}', read_at=now)

# ── Mesures du navigateur
ContentDailyView.objects.create(content=ex_easy, date=today, count=10, anon_count=4)
ContentDailyView.objects.create(content=ex_med, date=today, count=1)
for kind, name, count, anon in (('page', '/exercises/:id', 10, 4), ('page', '/route-inconnue', 1, 0),
                                ('action', 'voir-solution', 4, 1), ('action', 'partager', 2, 0),
                                ('filtre', 'auth:porte:vote', 3, 3), ('filtre', 'exercise:difficulte:hard', 2, 1),
                                ('site', 'visites', 12, 5)):
    UsageDaily.objects.create(date=today, kind=kind, name=name, count=count, visitors=count, anon_count=anon,
                              anon_visitors=anon)


def table_counts():
    with connection.cursor() as cur:
        out = {}
        for table in connection.introspection.table_names():
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            out[table] = cur.fetchone()[0]
        return out


cache = caches['default']
cache.clear()
before = table_counts()
WRITES = ('INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'CREATE', 'DROP', 'ALTER')
with CaptureQueriesContext(connection) as ctx:
    md = StringIO()
    call_command('audit_usage', stdout=md)
    js = StringIO()
    call_command('audit_usage', '--format', 'json', '--jours', '30', '--top', '5', '--min-eleves', '5', stdout=js)
    out_file = os.path.join(tempfile.gettempdir(), 'fidni-audit-usage.md')
    call_command('audit_usage', '--sortie', out_file, '--jours', '7', stdout=StringIO())
writes = [q['sql'][:80] for q in ctx.captured_queries if q['sql'].lstrip().upper().startswith(WRITES)]
check('aucune requête d’écriture', not writes, writes[:3])
after = table_counts()
check('nombre de lignes de chaque table inchangé', before == after,
      {t: (before.get(t), after.get(t)) for t in set(before) | set(after) if before.get(t) != after.get(t)})
check('cache : rien écrit pendant le rapport', len(getattr(cache, '_cache', {})) == 0, len(getattr(cache, '_cache', {})))
cache.set('apres-rapport', 1)
check('cache : de nouveau utilisable après la commande', cache.get('apres-rapport') == 1)

text = md.getvalue()
check('markdown : titre et 10 sections', text.startswith('# Audit d’usage Fidni')
      and all(f'## {i}. ' in text for i in range(1, 11)), text[:200])
check('markdown : aucun e-mail ni nom d’élève', '@x.fr' not in text and 'eleve' not in text and 'chef' not in text)
check('markdown : tableaux', '| Fonctionnalité | Membres |' in text and '|---|' in text)
check('fichier --sortie écrit', os.path.exists(out_file) and open(out_file, encoding='utf-8').read().startswith('# Audit'))

rep = json.loads(js.getvalue())
sec = rep['sections']
check('json : période et paramètres', rep['days'] == 30 and rep['top'] == 5 and rep['min_students'] == 5
      and rep['to'] == today.isoformat(), {k: rep[k] for k in ('days', 'top', 'min_students', 'to')})
pop = sec['couverture']['population']
check('population : 9 membres réels (3 comptes maison exclus), 1 prof', pop['members'] == 9 and pop['teachers'] == 1
      and pop['students'] == 8, pop)
check('couverture : jours mesurés par source', any(x['since'] == '2026-10-06' for x in sec['couverture']['sources'])
      and all(0 <= x['measured_days'] <= 30 for x in sec['couverture']['sources']), sec['couverture']['sources'])

f = sec['fonctionnalites']
g = {x['key']: x for x in f['gestures']}
check('gestes : comptés, nouveaux gestes à 0 listés', g['partager']['count'] == 2 and g['voir-solution']['anon'] == 1
      and 'cloche' in f['gestures_never_used'] and 'partager' not in f['gestures_never_used'], g.get('partager'))
check('gestes : les moins utilisés en tête', [x['count'] for x in f['gestures']] == sorted(x['count'] for x in f['gestures']))
base = {x['key']: x for x in f['base']}
check('fonctionnalités en base : comptes maison exclus', base['solution_vue']['users'] == 1 and base['ressenti']['users'] == 5
      and base['signalement']['actions'] == 1, (base.get('solution_vue'), base.get('ressenti')))
check('fonctionnalités en base : sources ajoutées (réponses, notifications lues, temps d’étude)',
      base['reponse']['actions'] == 1 and base['notif_lue']['users'] == 1 and base['temps_etude']['users'] == 3,
      (base.get('reponse'), base.get('notif_lue'), base.get('temps_etude')))
check('portes d’inscription', [(x['source'], x['count']) for x in f['auth_doors']] == [('vote', 3)], f['auth_doors'])
check('valeurs des filtres', [(x['label'], x['count']) for x in f['filter_values']] == [('Difficile', 2)], f['filter_values'])

pg = sec['pages']
pages = {x['page']: x for x in pg['pages']}
check('pages : vues et part des visiteurs', pages['/exercises/:id']['views'] == 10 and pages['/exercises/:id']['anon'] == 4)
FRONT = os.path.join(os.path.dirname(BACKEND), 'Fidni-Frontend', 'src', 'lib', 'usage.ts')
if os.path.exists(FRONT):
    import re  # noqa: E402
    from apps.users.management.commands.audit_usage import PAGE_PATTERNS  # noqa: E402
    front = open(FRONT, encoding='utf-8').read()
    front_pages = re.findall(r"pattern: '([^']+)'", front[front.index('export const PAGES'):])
    check('PAGE_PATTERNS = PAGES du front (lib/usage.ts)', [p for p, _ in PAGE_PATTERNS] == front_pages,
          set(front_pages) ^ {p for p, _ in PAGE_PATTERNS})
check('pages ajoutées le 10/10 : mesurées depuis le 10/10', pages['/revisions/ds/:id']['measured_since'] == '2026-10-10'
      and pages['/saved']['measured_since'] == '2026-10-06')
check('pages : jamais vues listées, motif inconnu signalé', '/saved' in pg['never_viewed']
      and '/exercises/:id' not in pg['never_viewed']
      and pages['/route-inconnue']['label'] == '(motif inconnu du front)', pg['never_viewed'][:5])
check('visiteurs non connectés', pg['site']['anon_visits'] == 5 and pg['anonymous']['current']['visits'] == 5,
      (pg['site'], pg['anonymous']['current']))

fu = sec['entonnoir']
check('entonnoir : cohorte de la période, comptes maison exclus',
      {k: fu[k] for k in ('signups', 'verified', 'onboarded', 'first_view', 'first_work', 'back_d7', 'd7_eligible')}
      == {'signups': 8, 'verified': 7, 'onboarded': 1, 'first_view': 2, 'first_work': 7, 'back_d7': 1, 'd7_eligible': 1}, fu)
check('entonnoir : étapes d’onboarding des profils inachevés', sum(x['members'] for x in fu['onboarding_steps_unfinished']) == 7,
      fu['onboarding_steps_unfinished'])
check('rétention : 8 cohortes hebdomadaires × 5 semaines', len(sec['retention']['cohorts']) == 8
      and all(len(c['weeks']) == 5 for c in sec['retention']['cohorts']))
# eleve6, inscrit il y a 10 jours (seul de sa semaine), revenu à J+8 : semaine 0 finie (pas active), semaine 1 pas finie.
week6 = today - timedelta(days=10)
week6 -= timedelta(days=week6.weekday())
coh6 = next((x for x in sec['retention']['cohorts'] if x['week_of'] == week6.isoformat()), {})
check('rétention : seules les semaines entièrement écoulées comptent', coh6.get('signups') == 1
      and coh6['weeks'][0] == {'week': 0, 'eligible': 1, 'active': 0, 'rate': 0}
      and coh6['weeks'][1] == {'week': 1, 'eligible': 0, 'active': 0, 'rate': None}, coh6)

co = sec['contenus']
check('contenus les plus vus', co['viewed'][0]['id'] == ex_easy.id and co['viewed'][0]['views'] == 10
      and co['viewed'][0]['readers'] == 2 and co['viewed'][-1]['id'] == ex_med.id, co['viewed'][:2])
check('contenus jamais vus, par type et par chapitre', co['unviewed_by_type'].get('lesson') == 1
      and co['unviewed_by_chapter'][0]['unviewed'] == 2, (co['unviewed_by_type'], co['unviewed_by_chapter'][:1]))

d = sec['difficulte']
rows = {x['id']: x for x in d['contents']}
e = rows[ex_easy.id]
check('réussite : admin exclu, lot « Tout réussi » à moitié', e['n'] == 7 and e['batch_students'] == 1
      and e['success'] == round(0.5 / 6.5, 2) and e['success_without_batch'] == 0.0, e)
check('réussite : un chemin qui n’est plus une question de l’énoncé est ignoré', rows[ex_med.id]['success'] == 1.0,
      rows.get(ex_med.id))
gaps = {x['id']: x for x in d['gaps']}
check('écart : « facile » raté par la plupart → plus dur', gaps.get(ex_easy.id, {}).get('gap', {}).get('direction') == 'harder'
      and gaps[ex_easy.id]['observed'] == 'hard', d['gaps'])
check('écart : « moyen » réussi par tous → plus facile ; lot d’avant le 10/10 deviné',
      gaps.get(ex_med.id, {}).get('gap', {}).get('direction') == 'easier' and rows[ex_med.id]['n'] == 6
      and rows[ex_med.id]['batch_students'] == 1, rows.get(ex_med.id))
check('pas d’écart sous le minimum d’élèves (examen : 1 élève)', exam.id not in gaps and rows[exam.id]['n'] == 1)
check('par difficulté affichée', any(x['type'] == 'exercise' and x['declared'] == 'easy' and x['with_min_students'] == 1
                                     and x['review_share'] == 100 for x in d['by_difficulty']), d['by_difficulty'])
check('questions les moins réussies (hors « Tout réussi »)', d['hardest_questions'][0]['id'] == ex_easy.id
      and d['hardest_questions'][0]['label'] in ('Q1', 'Q2') and d['hardest_questions'][0]['n'] == 6, d['hardest_questions'][:1])
check('origine des auto-évaluations (période)', d['assessment_sources']['tout'] == 2
      and d['assessment_sources']['question'] == 26,
      d['assessment_sources'])
fb = d['feedback']
check('ressenti donné : 5 avis d’élèves (admin exclu)', fb['total'] == 5 and fb['students_period'] == 5
      and fb['by_declared'] == [{'declared': 'easy', 'easier': 0, 'as_said': 0, 'harder': 5}], fb)
check('ressenti calculé (things/difficulty.py) branché ou raison donnée',
      d['felt_error'] is not None or fb['top_contents'][0]['felt'] in ('easy', 'medium', 'hard', None), d['felt_error'])

so = sec['solutions']
check('solutions : ouvertures pour 100 pages', so['global']['show_solution'] == 4 and so['global']['per_100_pages'] == 40.0,
      so['global'])
check('solutions ouvertes par contenu (membres)', so['per_content'][0]['id'] == ex_easy.id
      and so['per_content'][0]['members'] == 1
      and so['per_content'][0]['readers'] == 2, so['per_content'])
check('« solution pas comprise »', so['not_understood'] == [{**so['not_understood'][0], 'id': ex_easy.id, 'question_path': 'q1',
                                                             'n': 1}], so['not_understood'])
r = sec['signalements']
check('signalements : période (admin exclu), pour 100 vues, à traiter', r['period_total'] == 1
      and r['per_100_views'][0]['per_100_views'] == 10.0 and len(r['open']) == 2, r)
t = sec['temps']
easy_time = next((x for x in t['by_difficulty'] if x['type'] == 'exercise' and x['declared'] == 'easy'), {})
check('temps : médiane, plafond de 2 h, admin exclu, durée attendue', easy_time.get('pairs') == 3
      and easy_time.get('median_minutes') == 15.0 and easy_time.get('p75_minutes') == 67.5
      and easy_time.get('expected_minutes') == 10.0, easy_time)
check('temps : le cumul rattaché le jour de la migration est écarté',
      t['clean_since'] == (today - timedelta(days=19)).isoformat()
      and not any(x['declared'] == 'medium' and x['type'] == 'exercise' for x in t['by_difficulty']), t)
check('chrono : épreuve d’examen', t['chrono'] == [{'session_type': 'exam', 'n': 1, 'median_minutes': 100.0}], t['chrono'])

try:
    call_command('audit_usage', '--jours', '0', stdout=StringIO())
    check('--jours 0 refusé', False)
except CommandError:
    check('--jours 0 refusé', True)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
