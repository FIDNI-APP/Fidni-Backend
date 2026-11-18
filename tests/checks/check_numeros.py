"""Numéros des contenus par niveau et chapitre (things/numeros.py, 15/11/2026) et ordre des séries d'exercices
(RevisionListItem.position, reorder)."""
import importlib
import os
import runpy
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-numeros.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from io import StringIO  # noqa: E402
from django.apps import apps as django_apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Subject  # noqa: E402
from apps.interactions.models import RevisionList, RevisionListItem  # noqa: E402
from apps.things.models import Content, NumeroContenu  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
cache.clear()
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


auteur = User.objects.create_user('auteur_num', is_superuser=True, is_staff=True)
maths = Subject.objects.filter(name='Mathématiques').first() or Subject.objects.create(name='Mathématiques')
sm = ClassLevel.objects.get(name='2ème Bac SM')
pc = ClassLevel.objects.get(name='2ème Bac PC/SVT')
limites = Chapter.objects.create(name='Limites (test numéros)', subject=maths)
limites.class_levels.set([sm, pc])  # chapitre partagé par les deux niveaux
suites = Chapter.objects.create(name='Suites (test numéros)', subject=maths)
suites.class_levels.set([sm])


def contenu(titre, niveau, chapitre, type_='exercise'):
    c = Content.objects.create(type=type_, title=titre, author=auteur, subject=maths)
    c.class_levels.set([niveau])
    if chapitre:
        c.chapters.set([chapitre])
    return c


def num(c, niveau, chapitre):
    n = NumeroContenu.objects.filter(content=c, class_level=niveau, chapter=chapitre).first()
    return n.numero if n else None


# --- Une numérotation par chapitre, par niveau, par type
l1, l2, l3 = (contenu(f'Limites SM {i}', sm, limites) for i in (1, 2, 3))
s1 = contenu('Suites SM 1', sm, suites)
p1 = contenu('Limites PC 1', pc, limites)
d1 = contenu('Devoir limites SM', sm, limites, 'exam')
check('limites SM : 1, 2, 3', [num(c, sm, limites) for c in (l1, l2, l3)] == [1, 2, 3])
check('suites SM : repart à 1', num(s1, sm, suites) == 1)
check('chapitre partagé, autre niveau : repart à 1', num(p1, pc, limites) == 1)
check('devoirs : leur propre numérotation', num(d1, sm, limites) == 1)

# --- Changer de chapitre : nouveau numéro à la fin, l'ancien disparaît ; les autres ne bougent pas
l2.chapters.set([suites])
check('changé de chapitre : numéro à la fin du nouveau', num(l2, sm, suites) == 2 and num(l2, sm, limites) is None)
check('les autres gardent leur numéro', num(l1, sm, limites) == 1 and num(l3, sm, limites) == 3)
l4 = contenu('Limites SM 4', sm, limites)
check('nouveau contenu : suivant du plus grand', num(l4, sm, limites) == 4)

# --- Sans chapitre : numéroté dans son niveau ; leçon sur deux niveaux : un numéro par niveau
sans = contenu('Sans chapitre', sm, None)
check('sans chapitre : numéro dans le niveau', num(sans, sm, None) == 1)
lecon = Content.objects.create(type='lesson', title='Leçon limites', author=auteur, subject=maths)
lecon.class_levels.set([sm, pc])
lecon.chapters.set([limites])
check('leçon sur deux niveaux : un numéro par niveau', num(lecon, sm, limites) == 1 and num(lecon, pc, limites) == 1)

# --- Bac national : pas de numéro (sa rubrique par année), ni de trou chez les devoirs
national = Content.objects.create(type='exam', title='Bac national 2025', author=auteur, subject=maths, is_national_exam=True)
national.class_levels.set([sm])
national.chapters.set([limites])
d2 = contenu('Devoir limites SM 2', sm, limites, 'exam')
check('Bac national : pas de numéro', not NumeroContenu.objects.filter(content=national).exists())
check('devoir suivant : pas de trou', num(d2, sm, limites) == 2)
d2.is_national_exam = True
d2.save()
check('devoir passé en Bac national : numéro retiré', num(d2, sm, limites) is None)
d2.is_national_exam = False
d2.save()
check('repassé en devoir : renuméroté', num(d2, sm, limites) == 2)

# --- Côté inverse (chapitre.content_items.add) et suppression
nouveau = Content.objects.create(type='exercise', title='Ajout inverse', author=auteur, subject=maths)
nouveau.class_levels.set([sm])
suites.content_items.add(nouveau)
check('ajout par le chapitre : numéroté', num(nouveau, sm, suites) == 3)
l4.delete()
check('contenu supprimé : son numéro part avec lui', not NumeroContenu.objects.filter(content_id=l4.pk).exists())

# --- API : champ « numeros » des listes et du détail
client = APIClient()
r = client.get(f'/api/contents/{l3.pk}/')
check('détail : numeros', r.status_code == 200 and r.data.get('numeros') == [{'niveau': sm.id, 'chapitre': limites.id, 'numero': 3}],
      (r.status_code, r.data.get('numeros')))
r = client.get('/api/contents/?type=exercise&page_size=50')
cartes = r.data['results'] if isinstance(r.data, dict) else r.data
carte = next((c for c in cartes if c['id'] == p1.pk), None)
check('liste : numeros sur la carte', carte and carte.get('numeros') == [{'niveau': pc.id, 'chapitre': limites.id, 'numero': 1}],
      carte and carte.get('numeros'))

# --- Recherche par numéro (17/11/2026) : « exercice 3 » dans un chapitre → l'exercice n° 3 de ce chapitre
from apps.things.numeros import numero_cherche  # noqa: E402
check('requête : formes reconnues', [numero_cherche(q) for q in ('48', '#48', 'exercice 48', 'Exercice n° 48', 'ex48',
                                                                   'numéro 12', 'n°7', 'DS 3', 'Devoir n° 2', 'leçon 5')]
      == [48, 48, 48, 48, 48, 12, 7, 3, 2, 5])
check('requête : un mot n’est pas un numéro', [numero_cherche(q) for q in ('dérivée', 'x 48', '48 limites', '')]
      == [None, None, None, None])


def ids(q, **extra):
    params = {'type': 'exercise', 'page_size': 50, 'search': q, **extra}
    r = client.get('/api/contents/', params)
    data = r.data['results'] if isinstance(r.data, dict) else r.data
    return {c['id'] for c in data}


check('chapitre : « 3 » → l’exercice n° 3 seul', ids('3', **{'class_levels[]': sm.id, 'chapters[]': limites.id}) == {l3.pk},
      ids('3', **{'class_levels[]': sm.id, 'chapters[]': limites.id}))
check('chapitre : « exercice n° 1 » dans un autre chapitre', ids('exercice n° 1', **{'class_levels[]': sm.id, 'chapters[]': suites.id})
      == {s1.pk})
check('autre niveau, même chapitre : sa propre numérotation', ids('#1', **{'class_levels[]': pc.id, 'chapters[]': limites.id})
      == {p1.pk})
tous = ids('1', **{'class_levels[]': sm.id})
check('niveau entier : les n° 1 de chaque chapitre', {l1.pk, s1.pk} <= tous and l3.pk not in tous, tous)
check('numéro absent : recherche dans le texte (rien ici)', ids('99', **{'chapters[]': limites.id}) == set())
check('recherche par mots inchangée', l3.pk in ids('Limites SM 3') and s1.pk in ids('suites'))

# --- Migration 0030 : contenus déjà en ligne numérotés par date d'arrivée ; commande de rattrapage
NumeroContenu.objects.all().delete()
migration = importlib.import_module('apps.things.migrations.0030_numeros_contenus')
migration.numeroter(django_apps, None)
check('migration : ordre d’arrivée', [num(c, sm, limites) for c in (l1, l3)] == [1, 2] and num(p1, pc, limites) == 1
      and num(l2, sm, suites) == 1 and num(s1, sm, suites) == 2 and num(lecon, pc, limites) == 1)  # l2 est arrivé avant s1
avant = dict(NumeroContenu.objects.values_list('content_id', 'numero').order_by('id'))
Content.chapters.through.objects.filter(content_id=s1.pk).delete()  # retrait sans signal
out = StringIO()
call_command('numeroter_contenus', stdout=out)
check('commande : rattrape le contenu changé sans signal', num(s1, sm, None) is not None and '1 contenu' in out.getvalue(),
      out.getvalue())
check('commande : les autres numéros ne bougent pas', all(
    NumeroContenu.objects.filter(content_id=cid, numero=n).exists() for cid, n in avant.items() if cid != s1.pk))

# --- Série d'exercices : ordre gardé, réordonnable
eleve = User.objects.create_user('eleve_serie')
client.force_authenticate(eleve)
r = client.post('/api/revision-lists/', {'name': 'Ma série'}, format='json')
lid = r.data['id']
for c in (l1, l3, s1):
    client.post(f'/api/revision-lists/{lid}/add_item/', {'content_type': 'exercise', 'object_id': c.pk}, format='json')
d = client.get(f'/api/revision-lists/{lid}/').data
check('série : ordre d’ajout (le premier ajouté en premier)', [i['object_id'] for i in d['items']] == [l1.pk, l3.pk, s1.pk],
      [i['object_id'] for i in d['items']])
ids = [i['id'] for i in d['items']]
r = client.post(f'/api/revision-lists/{lid}/reorder/', {'item_ids': [ids[2], ids[0], ids[1]]}, format='json')
d = client.get(f'/api/revision-lists/{lid}/').data
check('série : nouvel ordre enregistré', r.status_code == 200 and [i['object_id'] for i in d['items']] == [s1.pk, l1.pk, l3.pk])
lst = next(x for x in client.get('/api/revision-lists/').data if x['id'] == lid)
check('série : même ordre dans « mes listes »', [i['object_id'] for i in lst['items']] == [s1.pk, l1.pk, l3.pk])
r = client.post(f'/api/revision-lists/{lid}/reorder/', {'item_ids': ids[:2]}, format='json')
check('série : ordre incomplet refusé (409)', r.status_code == 409, r.status_code)
client.post(f'/api/revision-lists/{lid}/add_item/', {'content_type': 'exercise', 'object_id': p1.pk}, format='json')
d = client.get(f'/api/revision-lists/{lid}/').data
check('série : un ajout se met à la fin', [i['object_id'] for i in d['items']][-1] == p1.pk)
autre = User.objects.create_user('autre_serie')
client.force_authenticate(autre)
r = client.post(f'/api/revision-lists/{lid}/reorder/', {'item_ids': ids}, format='json')
check('série d’un autre : 404', r.status_code == 404, r.status_code)
client.force_authenticate(eleve)
r = client.post('/api/revision-lists/quick_add/', {'object_ids': [l1.pk, l3.pk]}, format='json')
rl = RevisionList.objects.get(pk=r.data['list_id'])
check('ajout en lot : positions 1, 2', list(rl.items.values_list('position', flat=True)) == [1, 2])

# --- Migration 0025 : positions des séries existantes dans l'ordre d'ajout
RevisionListItem.objects.update(position=0)
importlib.import_module('apps.interactions.migrations.0025_revisionlistitem_position').remplir(django_apps, None)
check('migration 0025 : positions par ordre d’ajout', list(RevisionListItem.objects.filter(revision_list_id=lid)
      .order_by('added_at', 'id').values_list('position', flat=True)) == [1, 2, 3, 4])

print(f'{sum(results)}/{len(results)} vérifications OK')
if not all(results):
    sys.exit(1)
