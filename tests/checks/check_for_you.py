"""« Pour toi » : ordre par défaut des listes de contenus (apps/things/for_you.py)."""
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-for-you.sqlite3')
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
from apps.interactions.models import Complete, Vote  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users.models import ViewHistory  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


author = User.objects.create_user('Fidni', 'f@x.fr', None)
eleve = User.objects.create_user('eleve', 'e@x.fr', 'Motdepasse-solide-42')
fans = [User.objects.create_user(f'fan{i}', f'fan{i}@x.fr', None) for i in range(8)]
sm = ClassLevel.objects.get(name='2ème Bac SM')
tc = ClassLevel.objects.get(name='Tronc commun Sciences')
eleve.profile.class_level = sm
eleve.profile.save()
lim = Chapter.objects.filter(name='Limites et continuité', class_levels=sm).first()
der = Chapter.objects.filter(name__startswith='Dérivation', class_levels=sm).first()
autres = list(Chapter.objects.filter(class_levels=sm).exclude(id__in=[lim.id, der.id])[:3])
ct = ContentType.objects.get_for_model(Content)
now = timezone.now()


def make(title, chapter, level=sm, days=60, likes=0):
    c = Content.objects.create(type='exercise', title=title, author=author, difficulty='medium',
                               json_content={'version': '2.1', 'blocks': []})
    c.class_levels.set([level])
    c.chapters.set([chapter])
    Content.objects.filter(id=c.id).update(created_at=now - timedelta(days=days))
    for u in fans[:likes]:
        Vote.objects.create(user=u, value=Vote.UP, content_type=ct, object_id=str(c.id))
    return c


def act(content, status=None, days=1, spent=900):
    ViewHistory.objects.create(user=eleve, content_type=ct, object_id=content.id, time_spent=spent)
    ViewHistory.objects.filter(user=eleve, object_id=content.id).update(viewed_at=now - timedelta(days=days))
    if status:
        Complete.objects.create(user=eleve, content_type=ct, object_id=str(content.id), status=status)
        Complete.objects.filter(user=eleve, object_id=str(content.id)).update(updated_at=now - timedelta(days=days))


# Les « plus aimés » sont tous dans Limites et continuité.
lim_ex = [make(f'Limites {i}', lim, likes=8 - i) for i in range(6)]
der_ex = [make(f'Dérivation {i}', der, likes=1) for i in range(4)]
autres_ex = [make(f'Autre {i}', ch) for i, ch in enumerate(autres)]
tc_ex = make('Tronc commun', lim, level=tc, likes=8)
neuf_lim = make('Limites tout neuf', lim, days=1)

c = APIClient()


def titles(params='', client=c):
    r = client.get('/api/contents/?type=exercise&sort=recommended&page_size=100' + params)
    assert r.status_code == 200, r.status_code
    return [x['title'] for x in r.data['results']], {x['title']: x['recommendation_reason'] for x in r.data['results']}


# --- Visiteur : popularité + nouveauté + variété.
t, _ = titles()
check('visiteur : tous les contenus listés', len(t) == Content.objects.count(), len(t))
check('visiteur : le nouveau contenu remonte (top 5)', 'Limites tout neuf' in t[:5], t[:6])
check('visiteur : variété — la 1ère page n\'est pas qu\'un chapitre',
      any(not x.startswith('Limites') for x in t[:4]), t[:6])

# --- Élève qui a travaillé Limites et continuité, presque tout réussi, et commence la Dérivation.
for ex in lim_ex[:5]:
    act(ex, 'success', days=10)
act(lim_ex[5], 'review', days=3)
act(der_ex[0], days=1)
c.force_authenticate(eleve)
t, why = titles()
check('réussi : tout en bas', set(t[-5:]) == {e.title for e in lim_ex[:5]}, t[-6:])
check('réussi : pas d\'étiquette', all(why[e.title] is None for e in lim_ex[:5]), why)
check('à retravailler : en haut (top 3) avec la raison', 'Limites 5' in t[:3] and why['Limites 5'] == 'À retravailler',
      (t[:4], why.get('Limites 5')))
check('nouveau dans son chapitre : en haut (top 3)', 'Limites tout neuf' in t[:3], t[:4])
check('chapitre en cours (Dérivation) avant les chapitres jamais ouverts',
      t.index('Dérivation 1') < min(t.index(e.title) for e in autres_ex), t)
check('raison « Suite de ton travail »', (why['Dérivation 1'] or '').startswith('Suite de ton travail'), why)
check('autre niveau : derrière tout ce qui reste à faire de son niveau',
      t.index('Tronc commun') > max(t.index(e.title) for e in der_ex + autres_ex), t)

# --- Les filtres s'appliquent toujours.
t, _ = titles(f'&chapters[]={der.id}')
check('filtre chapitre respecté', sorted(t) == sorted(e.title for e in der_ex), t)

# --- Pagination stable : pas de doublon ni de trou entre les pages.
p1 = c.get('/api/contents/?type=exercise&sort=recommended&page_size=5').data
p2 = c.get('/api/contents/?type=exercise&sort=recommended&page_size=5&page=2').data
ids = [x['id'] for x in p1['results']] + [x['id'] for x in p2['results']]
check('pages sans doublon', len(ids) == len(set(ids)) == 10, ids)
check('compte total', p1['count'] == Content.objects.count(), p1['count'])

# --- Réussir un contenu le fait descendre aussitôt (la 1ère page recalcule).
Complete.objects.create(user=eleve, content_type=ct, object_id=str(neuf_lim.id), status='success')
t, _ = titles()
check('réussi à l\'instant : descend', t.index('Limites tout neuf') > t.index('Tronc commun'), t)

# --- Recherche : la pertinence prime, pas d'erreur.
r = c.get('/api/contents/?type=exercise&sort=recommended&search=Dérivation')
check('recherche + Pour toi : 200 et résultats filtrés',
      r.status_code == 200 and all('Dérivation' in x['title'] for x in r.data['results']) and r.data['count'] == 4,
      (r.status_code, r.data.get('count')))

# --- Les autres tris ne bougent pas.
r = c.get('/api/contents/?type=exercise&sort=most_upvoted')
check('« Plus aimés » inchangé', r.data['results'][0]['title'] in ('Limites 0', 'Tronc commun'), r.data['results'][0]['title'])

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
