"""Ressenti des élèves sur la difficulté (apps/things/difficulty.py) et avis « plus facile / plus dur » (C1, C2)."""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-ressenti.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress  # noqa: E402
from apps.things import difficulty  # noqa: E402
from apps.things.models import Content, DifficultyFeedback  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


ct = ContentType.objects.get_for_model(Content)
editorial = User.objects.create_user('Fidni', 'f@x.fr', None)
prof = User.objects.create_user('prof', 'p@x.fr', 'Motdepasse-solide-42')
admin = User.objects.create_user('admin', 'a@x.fr', 'Motdepasse-solide-42', is_staff=True)
testeur = User.objects.create_user('fidni_test_claude', 't@x.fr', 'Motdepasse-solide-42')
HOUSE = [editorial, admin, testeur]
JS = {'version': '2.1', 'blocks': [
    {'id': 'q1', 'type': 'question', 'content': {'html': '<p>a</p>'}},
    {'id': 'q2', 'type': 'question', 'content': {'html': '<p>b</p>'},
     'subQuestions': [{'id': 's1', 'content': {'html': '<p>c</p>'}}, {'id': 's2', 'content': {'html': '<p>d</p>'}}]},
    {'id': 'q3', 'type': 'question', 'content': {'html': '<p>e</p>'}},
]}
PATHS = ['q1', 'q2.s1', 'q2.s2', 'q3']
_n = [0]


def students(k):
    out = []
    for _ in range(k):
        _n[0] += 1
        out.append(User.objects.create_user(f'eleve{_n[0]}', f'e{_n[0]}@x.fr', 'Motdepasse-solide-42'))
    return out


def make(title, diff='medium', kind='exercise', by=editorial):
    return Content.objects.create(type=kind, title=title, author=by, json_content=JS if kind != 'lesson' else {},
                                  difficulty=diff if kind != 'lesson' else None)


def assess(user, c, statuses, source='question'):
    for path, st in zip(PATHS, statuses):
        QuestionProgress.objects.create(user=user, content_type=ct, object_id=c.id, question_path=path, status=st,
                                        source=source)


def done(user, c, st):
    Complete.objects.create(user=user, content_type=ct, object_id=str(c.id), status=st)


def vote(user, c, felt, declared='same'):
    DifficultyFeedback.objects.create(user=user, content=c, felt=felt,
                                      declared=c.difficulty if declared == 'same' else declared)


def felt(c):
    return difficulty.felt_for([Content.objects.get(pk=c.pk)])[c.id]


# ── Règles de base
lo, hi = difficulty.wilson(0.5, 100)
check('Wilson 80 % : symétrique et étroit sur 100 élèves', abs((lo + hi) / 2 - 0.5) < 1e-9 and 0.06 < hi - 0.5 < 0.07, (lo, hi))
lo, hi = difficulty.wilson(0.0, 10)
check('Wilson 80 % : 0 réussite sur 10 → borne haute ≈ 0,14', lo < 1e-9 and 0.13 < hi < 0.15, (lo, hi))
check('bandes : 0,70 facile · 0,40 moyen · en dessous difficile',
      [difficulty.band(x) for x in (0.70, 0.6999, 0.40, 0.3999)] == ['easy', 'medium', 'medium', 'hard'])

# ── « Moyen » que les élèves ratent : 12 élèves à 12,5 %, comptes maison et auteur ignorés
rate = make('Moyen raté', by=prof)
for u in students(12):
    assess(u, rate, ['review', 'review', 'review', 'partial'])
for u in HOUSE + [prof]:
    assess(u, rate, ['success'] * 4)
    done(u, rate, 'success')
f = felt(rate)
check('réussite basse sûre : ressenti Difficile', f and f['level'] == 'hard' and f['basis'] == 'reussite' and f['differs'], f)
check('comptes maison et auteur exclus : n = 12, 12 %', f and f['n'] == 12 and f['success_pct'] == 12, f)
check('forme du ressenti (C1)', f and set(f) == {'level', 'declared', 'differs', 'n', 'success_pct', 'votes', 'basis'}
      and f['declared'] == 'medium' and f['votes'] == {'easier': 0, 'as_said': 0, 'harder': 0}, f)

peu = make('Seulement 7 élèves')
for u in students(7):
    assess(u, peu, ['review'] * 4)
check('moins de 8 élèves et moins de 5 avis : pas de ressenti', felt(peu) is None, felt(peu))

flou = make('Facile à 60 %', diff='easy')
for u in students(8):
    assess(u, flou, ['success', 'success', 'partial', 'review'])  # 62,5 %
f = felt(flou)
check('intervalle qui touche la bande annoncée : comme annoncé', f and f['level'] == 'easy' and f['basis'] == 'annonce'
      and not f['differs'] and f['success_pct'] == 62, f)

tout = make('Tout réussi en un clic')
for u in students(8):
    assess(u, tout, ['success'] * 4, source='tout')
for u in students(8):
    assess(u, tout, ['review'] * 4)
f = felt(tout)
check('« Tout réussi » pèse moitié : R = 4/12 = 33 % (et non 50 %)', f and f['n'] == 16 and f['success_pct'] == 33, f)

complete = make('Facile resté À revoir', diff='easy')
for u in students(8):
    done(u, complete, 'review')
moitie = students(1)[0]
assess(moitie, complete, ['review'])  # 1 question sur 4 : pas assez, son « Réussi » compte
done(moitie, complete, 'success')
f = felt(complete)
check('sans évaluations suffisantes : Réussi = 1, À revoir = 0,25 → Difficile', f and f['n'] == 9 and f['success_pct'] == 33
      and f['level'] == 'hard' and f['basis'] == 'reussite', f)

# ── Avis
avis = make('Moyen jugé dur')
for u in students(5):
    vote(u, avis, 'harder')
vote(students(1)[0], avis, 'as_said')
vote(admin, avis, 'easier')                       # compte maison : ignoré
vote(students(1)[0], avis, 'easier', declared='easy')  # donné sur une autre difficulté affichée : ignoré
f = felt(avis)
check('5 avis « plus dur » sur 6 : un niveau au-dessus', f and f['level'] == 'hard' and f['basis'] == 'avis' and f['n'] == 0
      and f['votes'] == {'easier': 0, 'as_said': 1, 'harder': 5}, f)

partage = make('Avis partagés')
for felt_, k in (('harder', 3), ('easier', 2), ('as_said', 1)):
    for u in students(k):
        vote(u, partage, felt_)
f = felt(partage)
check('avis partagés (|3 − 2| / 6 < 0,4) : comme annoncé', f and f['level'] == 'medium' and f['basis'] == 'annonce'
      and not f['differs'], f)

dur = make('Difficile jugé encore plus dur', diff='hard')
for u in students(5):
    vote(u, dur, 'harder')
f = felt(dur)
check('déjà Difficile : reste Difficile', f and f['level'] == 'hard' and not f['differs'], f)

facile_rate = make('Facile jugé facile mais raté', diff='easy')
for u in students(5):
    vote(u, facile_rate, 'easier')
for u in students(10):
    assess(u, facile_rate, ['review'] * 4)
f = felt(facile_rate)
check('« plus facile » sur un Facile ne décale rien : les résultats décident (Difficile)',
      f and f['level'] == 'hard' and f['basis'] == 'reussite' and f['differs'], f)

lecon = make('Cours', kind='lesson')
check('leçon : jamais de ressenti', difficulty.felt_for([lecon]) == {lecon.id: None})

# ── Cache de 6 h, vidé par forget()
for u in students(30):
    assess(u, flou, ['success'] * 4)
check('ressenti gardé en cache', felt(flou)['n'] == 8, felt(flou))
difficulty.forget(flou)
f = felt(flou)
check('forget() : recalculé (38 élèves, 92 %)', f['n'] == 38 and f['success_pct'] == 92 and f['level'] == 'easy', f)

cache.clear()
partiel = Content.objects.only('id', 'type', 'difficulty').get(pk=rate.pk)
f = difficulty.felt_for([partiel], store=False)[rate.id]
check('store=False (audit en lecture seule) : même résultat, rien en cache, objets partiels acceptés',
      f and f['level'] == 'hard' and f['n'] == 12 and cache.get(difficulty._key(rate.id, 'medium')) is None, f)

# ── Écarts pour le Pilotage
gaps = difficulty.difficulty_gaps()
titles = [g['content'].title for g in gaps]
check('écarts : le plus gros d’abord, puis le plus d’élèves',
      titles == ['Facile jugé facile mais raté', 'Facile resté À revoir', 'Moyen raté', 'Moyen jugé dur'], titles)
check('écarts : seulement ceux qui diffèrent',
      set(titles) == {'Facile jugé facile mais raté', 'Facile resté À revoir', 'Moyen raté', 'Moyen jugé dur'}, titles)
check('écarts : forme {content, declared, felt, n, success_pct, votes}',
      all({'content', 'declared', 'felt', 'n', 'success_pct', 'votes'} <= set(g) for g in gaps)
      and gaps[0]['declared'] == 'easy' and gaps[0]['felt'] == 'hard', gaps[:1])

# ── Endpoint POST/DELETE /api/contents/<id>/ressenti/
c = APIClient()
url = f'/api/contents/{partage.id}/ressenti/'
check('visiteur : refusé', c.post(url, {'felt': 'harder'}, format='json').status_code in (401, 403))
eleve = students(1)[0]
c.force_authenticate(eleve)
check('leçon : 400', c.post(f'/api/contents/{lecon.id}/ressenti/', {'felt': 'harder'}, format='json').status_code == 400)
check('valeur inconnue : 400', c.post(url, {'felt': 'dur'}, format='json').status_code == 400)

seuil = make('Quatre avis « plus dur »')
for u in students(4):
    vote(u, seuil, 'harder')
check('4 avis : pas encore de ressenti (et mis en cache)', felt(seuil) is None)
r = c.post(f'/api/contents/{seuil.id}/ressenti/', {'felt': 'harder'}, format='json')
check('POST : 200 {felt, declared, ressenti}', r.status_code == 200 and r.data['felt'] == 'harder'
      and r.data['declared'] == 'medium' and r.data['ressenti'] and r.data['ressenti']['level'] == 'hard', r.data)
fb = DifficultyFeedback.objects.filter(user=eleve, content=seuil)
check('avis enregistré avec la difficulté affichée', fb.count() == 1 and fb.first().declared == 'medium')
r = c.post(f'/api/contents/{seuil.id}/ressenti/', {'felt': 'as_said'}, format='json')
check('nouvel avis : remplace le précédent (cache vidé)', r.status_code == 200 and fb.count() == 1 and fb.first().felt == 'as_said'
      and r.data['ressenti']['votes'] == {'easier': 0, 'as_said': 1, 'harder': 4}, r.data)
r = c.delete(f'/api/contents/{seuil.id}/ressenti/')
check('DELETE : 204, avis retiré, ressenti recalculé', r.status_code == 204 and not fb.exists() and felt(seuil) is None)

# ── Ressenti dans la liste et le détail
c.force_authenticate(None)
r = c.get('/api/contents/', {'type': 'exercise', 'page_size': 50})
rows = {x['id']: x for x in r.data['results']}
check('liste : chaque ligne porte felt', r.status_code == 200 and all('felt' in x for x in rows.values()))
check('liste : « Facile resté À revoir » ressenti Difficile', rows[complete.id]['felt']['level'] == 'hard', rows[complete.id]['felt'])
check('liste : pas assez de données → null', rows[peu.id]['felt'] is None)
r = c.get('/api/contents/', {'type': 'exercise', 'sort': 'recommended'})
check('liste « Pour toi » : felt aussi', r.status_code == 200 and all('felt' in x for x in r.data['results']))
r = c.get(f'/api/contents/{complete.id}/')
check('détail : felt', r.status_code == 200 and r.data['felt']['level'] == 'hard' and r.data['felt']['n'] == 9, r.data.get('felt'))
check('détail d’une leçon : felt null', c.get(f'/api/contents/{lecon.id}/').data['felt'] is None)

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
