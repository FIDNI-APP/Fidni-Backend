"""Listes de contenus et page d'un contenu (C3-C7) : tri « du plus facile », « À faire », mode Cartes, progression
de l'élève, durée attendue, origine d'une évaluation, bandeau par chapitre, exercice suivant, note d'une épreuve."""
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-listes.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))  # taxonomie réelle
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress, StudyTimeDay, TimeSession  # noqa: E402
from apps.things import importing  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users.models import ViewHistory  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


ct = ContentType.objects.get_for_model(Content)
author = User.objects.create_user('Fidni', 'f@x.fr', None)
admin = User.objects.create_user('admin', 'a@x.fr', 'Motdepasse-solide-42', is_staff=True)
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
autre = User.objects.create_user('autre', 'o@x.fr', 'Motdepasse-solide-42')
sm = ClassLevel.objects.get(name='2ème Bac SM')
lim = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
der = Chapter.objects.filter(name__startswith='Dérivation', class_levels=sm).first()


def structure(n_blocks=2, seconds=(120, 240, 60)):
    blocks = [
        {'id': 'q1', 'type': 'question', 'content': {'html': '<p>a</p>'}, 'solution': {'html': '<p>S1</p>'},
         'meta': {'expected_seconds': seconds[0]} if seconds else {}},
        {'id': 'q2', 'type': 'question', 'content': {'html': '<p>b</p>'}, 'subQuestions': [
            {'id': 's1', 'content': {'html': '<p>c</p>'}, 'solution': {'html': '<p>S2</p>'},
             'meta': {'expected_seconds': seconds[1]} if seconds else {}},
            {'id': 's2', 'content': {'html': '<p>d</p>'}, 'solution': {'html': '<p>S3</p>'},
             'meta': {'expected_seconds': seconds[2]} if seconds else {}},
        ]},
    ]
    blocks += [{'id': f'c{i}', 'type': 'context', 'content': {'html': f'<p>contexte {i}</p>'}} for i in range(n_blocks)]
    return {'version': '2.1', 'blocks': blocks}


def make(title, difficulty='medium', kind='exercise', chapters=(lim,), **kw):
    c = Content.objects.create(type=kind, title=title, author=author, difficulty=difficulty if kind != 'lesson' else None,
                               json_content=kw.pop('json_content', structure()), **kw)
    c.class_levels.set([sm])
    c.chapters.set([ch for ch in chapters if ch])
    return c


def has_solution(value):
    if isinstance(value, dict):
        return 'solution' in value or any(has_solution(v) for v in value.values())
    if isinstance(value, list):
        return any(has_solution(v) for v in value)
    return False


dur = make('Difficile', 'hard')
moyen = make('Moyen', 'medium', json_content=structure(n_blocks=8))
facile_ancien = make('Facile ancien', 'easy')
facile = make('Facile récent', 'easy', json_content=structure(seconds=None))
sans = make('Sans difficulté', None)
Content.objects.filter(pk=facile_ancien.pk).update(created_at=timezone.now() - timedelta(days=30))

c = APIClient()


def ids(**params):
    r = c.get('/api/contents/', {'type': 'exercise', **params})
    return [x['id'] for x in r.data['results']] if r.status_code == 200 else r.status_code


# ── sort=easiest
check('tri « du plus facile » : facile → moyen → difficile → sans, puis les plus récents',
      ids(sort='easiest') == [facile.id, facile_ancien.id, moyen.id, dur.id, sans.id], ids(sort='easiest'))

# ── expected_minutes, slug du niveau
rows = {x['id']: x for x in c.get('/api/contents/', {'type': 'exercise'}).data['results']}
check('durée attendue : (120 + 240 + 60) s = 7 min', rows[dur.id]['expected_minutes'] == 7, rows[dur.id].get('expected_minutes'))
check('durée attendue : null sans expected_seconds', rows[facile.id]['expected_minutes'] is None)
check('niveau avec son slug', rows[dur.id]['class_levels'][0]['slug'] == '2eme-bac-sm', rows[dur.id]['class_levels'])
check('détail : durée attendue aussi', c.get(f'/api/contents/{dur.id}/').data['expected_minutes'] == 7)

# ── view=card
r = c.get('/api/contents/', {'type': 'exercise', 'view': 'card'})
card = {x['id']: x for x in r.data['results']}
check('mode Cartes : aucune solution', not any(has_solution(x['json_content']) for x in card.values()))
check('mode Cartes : 6 blocs au plus', len(card[moyen.id]['json_content']['blocks']) == 6
      and len(rows[moyen.id]['json_content']['blocks']) == 10, len(card[moyen.id]['json_content']['blocks']))
check('mode Cartes : barème et nombre de questions calculés sur tout l’énoncé',
      card[moyen.id]['item_count'] == rows[moyen.id]['item_count'] == 4, card[moyen.id]['item_count'])
check('sans view=card : énoncé complet avec solutions', has_solution(rows[dur.id]['json_content']))
sujet = make('Sujet en 4 parties', 'hard', kind='exam', json_content={'version': '2.1', 'blocks': [
    blk for i in range(4) for blk in ({'id': f'p{i}', 'type': 'section', 'content': {'html': f'Exercice {i + 1}'}},
                                      {'id': f'q{i}', 'type': 'question', 'content': {'html': '<p>x</p>'}})]})
r = c.get('/api/contents/', {'type': 'exam', 'view': 'card'})
row = next(x for x in r.data['results'] if x['id'] == sujet.id)
check('mode Cartes : nombre de parties d’un examen sur tout l’énoncé (section_count)',
      row['section_count'] == 4 and len(row['json_content']['blocks']) == 6, row.get('section_count'))
sujet.delete()

# ── user_progress (visiteur : null ; élève : une requête groupée)
check('visiteur : user_progress null', rows[dur.id]['user_progress'] is None)
c.force_authenticate(eleve)
r = c.post(f'/api/contents/{dur.id}/assess_question/', {'question_path': 'q1', 'status': 'success'}, format='json')
check('évaluation sans source : « question »', r.status_code == 200
      and QuestionProgress.objects.get(user=eleve, object_id=dur.id, question_path='q1').source == 'question')
r = c.post(f'/api/contents/{dur.id}/assess_question/',
           {'question_path': 'q2.s1', 'status': 'review', 'source': 'apres_solution'}, format='json')
check('évaluation après la solution : source enregistrée', r.status_code == 200
      and QuestionProgress.objects.get(user=eleve, object_id=dur.id, question_path='q2.s1').source == 'apres_solution')
r = c.post(f'/api/contents/{dur.id}/assess_question/', {'question_path': 'q1', 'status': 'success', 'source': 'bidon'},
           format='json')
check('source inconnue : 400', r.status_code == 400)
r = c.post(f'/api/contents/{moyen.id}/assess_many/', {'assessments': {'q1': 'success', 'q2.s1': 'success', 'q2.s2': 'success'},
                                                      'completion': 'success', 'source': 'tout'}, format='json')
check('« Tout réussi » : source « tout » sur chaque question', r.status_code == 200 and set(
    QuestionProgress.objects.filter(user=eleve, object_id=moyen.id).values_list('source', flat=True)) == {'tout'})
r = c.post(f'/api/contents/{moyen.id}/assess_many/', {'assessments': {'q1': 'review'}, 'source': 'rattrapage'}, format='json')
check('mise à jour : la source suit la dernière évaluation',
      QuestionProgress.objects.get(user=eleve, object_id=moyen.id, question_path='q1').source == 'rattrapage')
r = c.post(f'/api/contents/{moyen.id}/assess_many/', {'assessments': {'q1': 'review'}, 'source': 'x'}, format='json')
check('assess_many : source inconnue → 400', r.status_code == 400)
r = c.post(f'/api/contents/{moyen.id}/assess_many/', {'assessments': {'q1': 'review'}, 'source': ['tout']}, format='json')
check('assess_many : source qui n’est pas un texte → 400', r.status_code == 400)
r = c.post(f'/api/contents/{facile.id}/assess_question/', {'question_path': 'q1', 'status': 'success'}, format='json')
r = c.post(f'/api/contents/{facile.id}/assess_many/', {'assessments': {'q1': 'success', 'q2.s1': 'success', 'q2.s2': 'success'},
                                                       'source': 'tout'}, format='json')
src = dict(QuestionProgress.objects.filter(user=eleve, object_id=facile.id).values_list('question_path', 'source'))
check('« Tout réussi » après une question jugée seule : elle garde « question »',
      r.status_code == 200 and src == {'q1': 'question', 'q2.s1': 'tout', 'q2.s2': 'tout'}, src)
c.post(f'/api/contents/{facile.id}/assess_many/', {'assessments': {'q1': None, 'q2.s1': None, 'q2.s2': None}}, format='json')
rows = {x['id']: x for x in c.get('/api/contents/', {'type': 'exercise'}).data['results']}
check('user_progress : 2 évaluées sur 3, 1 réussie', rows[dur.id]['user_progress'] == {'assessed': 2, 'success': 1, 'total': 3},
      rows[dur.id]['user_progress'])
check('user_progress : rien d’évalué → 0 sur 3', rows[facile.id]['user_progress'] == {'assessed': 0, 'success': 0, 'total': 3})
rows = {x['id']: x for x in c.get('/api/contents/', {'type': 'exercise', 'sort': 'recommended'}).data['results']}
check('« Pour toi » : user_progress aussi', rows[moyen.id]['user_progress'] == {'assessed': 3, 'success': 2, 'total': 3},
      rows[moyen.id]['user_progress'])

# ── todo=true : tout sauf ses réussis
Complete.objects.create(user=autre, content_type=ct, object_id=str(dur.id), status='success')
check('« À faire » : ses réussis exclus (pas ceux des autres)',
      set(ids(todo='true')) == {dur.id, facile.id, facile_ancien.id, sans.id}, ids(todo='true'))
check('« À faire » + tri facile', ids(todo='true', sort='easiest') == [facile.id, facile_ancien.id, dur.id, sans.id])
c.force_authenticate(None)
check('« À faire » visiteur : tout', len(ids(todo='true')) == 5)
c.force_authenticate(eleve)

# ── /api/difficulty-counts/ et is_national_exam
national = make('Bac 2024', 'hard', kind='exam', is_national_exam=True, national_year=2024)
make('DS 1', 'hard', kind='exam')
make('DS 2', 'easy', kind='exam')
r = c.get('/api/difficulty-counts/', {'content_type': 'exam', 'is_national_exam': 'true'})
check('compteurs des examens nationaux seulement', r.data == {'hard': 1}, r.data)
r = c.get('/api/difficulty-counts/', {'content_type': 'exam', 'is_national_exam': 'false'})
check('compteurs des devoirs seulement', r.data == {'hard': 1, 'easy': 1}, r.data)
check('compteurs sans filtre : tout', c.get('/api/difficulty-counts/', {'content_type': 'exam'}).data == {'hard': 2, 'easy': 1})

# ── a-evaluer ?chapter
autre_chapitre = make('Dérivées travaillées', chapters=(der,))
for x in (facile, autre_chapitre):
    ViewHistory.objects.create(user=eleve, content_type=ct, object_id=x.id)
    StudyTimeDay.objects.create(user=eleve, object_id=x.id, date=timezone.localdate(), seconds=600)
r = c.get('/api/contents/a-evaluer/', {'type': 'exercise'})
check('bandeau : tous les chapitres', r.data['count'] == 2, r.data)
r = c.get('/api/contents/a-evaluer/', {'type': 'exercise', 'chapter': lim.id})
check('bandeau sur la page d’un chapitre : ce chapitre seulement',
      r.data['count'] == 1 and [x['title'] for x in r.data['items']] == ['Facile récent'], r.data)

# ── recommendations ?apres
lecon = make('Cours des limites', kind='lesson', json_content={'sections': []})
cache.delete('similar_index_v1')


def recos(src, apres=None):
    r = c.get(f'/api/contents/{src.id}/recommendations/', {'apres': apres} if apres else {})
    return [x['title'] for x in r.data['items']], r.data['items']


titles, items = recos(moyen, 'review')
check('après « À revoir » : le cours du chapitre d’abord', titles[0] == 'Cours des limites'
      and items[0]['reason'].startswith('Revois le cours'), titles)
check('après « À revoir » : rien de plus difficile avant le plus facile',
      titles.index('Facile récent') < titles.index('Difficile'), titles)
titles, _ = recos(moyen, 'success')
easy = [i for i, t in enumerate(titles) if t.startswith('Facile')]
check('après « Réussi » : rien de plus facile avant le plus difficile',
      titles[0] == 'Difficile' and all(i > titles.index('Sans difficulté') for i in easy), titles)
titles, items = recos(moyen)
check('sans apres : même forme qu’avant (+ felt), ordre de similarité', titles[0] == 'Difficile'
      and all('reason' in x and 'felt' in x and 'json_content' not in x for x in items), titles)

# ── Épreuve chronométrée : id de la session, note, historique
r = c.post(f'/api/contents/{national.id}/save_session/', {'duration_seconds': 3600, 'session_type': 'exam'}, format='json')
sid = r.data.get('id')
check('save_session : renvoie l’id', r.status_code == 201 and sid and r.data['session']['id'] == sid, r.data)
r = c.post(f'/api/contents/{national.id}/session_score/', {'session_id': sid, 'score': 13, 'max_score': 20}, format='json')
check('session_score : 200 {id, score, max_score}', r.status_code == 200 and r.data == {'id': sid, 'score': 13.0, 'max_score': 20.0},
      r.data)
check('note enregistrée', TimeSession.objects.get(pk=sid).score == 13)
for bad in ({'session_id': sid, 'score': 21, 'max_score': 20}, {'session_id': sid, 'score': -1, 'max_score': 20},
            {'session_id': sid, 'score': 'x', 'max_score': 20}, {'score': 1, 'max_score': 20}):
    if c.post(f'/api/contents/{national.id}/session_score/', bad, format='json').status_code != 400:
        check('note invalide : 400', False, bad)
        break
else:
    check('note invalide : 400', True)
check('session d’un autre contenu : 404', c.post(f'/api/contents/{dur.id}/session_score/',
                                                 {'session_id': sid, 'score': 1, 'max_score': 20}, format='json').status_code == 404)
c.force_authenticate(autre)
check('session d’un autre élève : 404', c.post(f'/api/contents/{national.id}/session_score/',
                                               {'session_id': sid, 'score': 1, 'max_score': 20}, format='json').status_code == 404)
c.force_authenticate(eleve)
h = c.get(f'/api/contents/{national.id}/session_history/').data['sessions']
check('historique : score et max_score', h[0]['score'] == 13 and h[0]['max_score'] == 20, h)
s = c.get(f'/api/contents/{national.id}/session_stats/').data
check('session_stats : score et max_score', s['sessions'][0]['score'] == 13 and s['stats']['last_session']['max_score'] == 20)
r = c.post(f'/api/contents/{national.id}/save_session/', {'duration_seconds': 60, 'score': 15, 'max_score': 20}, format='json')
check('save_session : note directement', r.status_code == 201 and TimeSession.objects.get(pk=r.data['id']).score == 15)

# ── Statistiques d'un contenu : comptes maison exclus, l'utilisateur qui regarde garde les siens
cache.clear()
Complete.objects.create(user=admin, content_type=ct, object_id=str(dur.id), status='review')
QuestionProgress.objects.create(user=admin, content_type=ct, object_id=dur.id, question_path='q1', status='review')
c.force_authenticate(admin)
st = c.get(f'/api/contents/{dur.id}/statistics/').data
q1 = next(q for q in st['per_question'] if q['path'] == 'q1')
check('statistiques : comptes maison exclus', st['total_participants'] == 1 and st['success_count'] == 1
      and st['review_count'] == 0 and q1['total'] == 1, (st['total_participants'], st['review_count'], q1))
check('statistiques : l’admin voit son propre statut', st['user_completed'] == 'review' and q1['user_status'] == 'review')
from apps.interactions.models import SolutionView  # noqa: E402
cache.clear()
SolutionView.objects.create(user=autre, content_type=ct, object_id=dur.id)  # vue, puis « Réussi » 5 min après
SolutionView.objects.create(user=admin, content_type=ct, object_id=dur.id)
Complete.objects.filter(user=autre, object_id=str(dur.id)).update(created_at=timezone.now() + timedelta(minutes=5))
st = c.get(f'/api/contents/{dur.id}/statistics/').data
check('statistiques : solution vue avant la réussite (comptes maison exclus)',
      st['solution_views_before_success'] == 1 and st['user_viewed_solution'], st['solution_views_before_success'])

# ── Éditeur : un exercice sans difficulté reste accepté (l'éditeur la demande ; pas de 400 inexpliqué)
c.force_authenticate(eleve)
base = {'type': 'exercise', 'title': 'Nouvel exercice', 'json_content': structure(), 'class_levels': [sm.id]}
r = c.post('/api/contents/', base, format='json')
check('création sans difficulté : acceptée comme avant', r.status_code == 201, (r.status_code, r.data))
r = c.post('/api/contents/', {**base, 'difficulty': 'easy'}, format='json')
check('création avec difficulté : 201', r.status_code == 201, (r.status_code, r.data))

# ── Examen importé : label tiré des questions, pondéré par les points
FICHE = {'type': 'examen', 'blocs': [
    {'type': 'question', 'points': 8, 'difficulte': 'difficile'},
    {'type': 'question', 'sous_questions': [{'points': 6, 'difficulte': 'facile'}, {'points': 6, 'difficulte': 'moyen'}]},
]}
check('examen : 40 % des points en difficile → hard', importing.exam_difficulty(FICHE) == 'hard')
FICHE['blocs'][0]['points'] = 6
FICHE['blocs'][1]['sous_questions'][0]['points'] = 8
check('examen : 30 % difficile, 40 % facile → medium', importing.exam_difficulty(FICHE) == 'medium')
FICHE['blocs'][0].update(points=2, difficulte='facile')
FICHE['blocs'][1]['sous_questions'][0]['points'] = 12
check('examen : 70 % facile → easy', importing.exam_difficulty(FICHE) == 'easy')
del FICHE['blocs'][0]['difficulte']
check('examen : une question sans difficulté → label de la fiche', importing.exam_difficulty(FICHE) is None)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
