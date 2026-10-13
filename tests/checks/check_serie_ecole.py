"""Pilotage : courbe d'un élément (jour / semaine). Contenu : établissement d'origine (assistant « Ajouter »)."""
import os
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-serie-ecole.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
import runpy  # noqa: E402
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, School, Subject  # noqa: E402
from apps.interactions.models import Save  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users import admin_dashboard  # noqa: E402
from apps.users.models import UsageDaily  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


admin = User.objects.create_superuser('chef', 'chef@x.fr', 'Motdepasse-solide-42')
eleves = [User.objects.create_user(f'eleve{i}', f'e{i}@x.fr', 'Motdepasse-solide-42') for i in range(3)]
subject = Subject.objects.get(name='Mathématiques')
level = ClassLevel.objects.get(name='2ème Bac SM')
ct = ContentType.objects.get_for_model(Content)
contents = [Content.objects.create(type='exercise', title=f'E{i}', author=admin, subject=subject, json_content={})
            for i in range(4)]
today = timezone.localdate()


def saved(user, content, days_ago):
    s = Save.objects.create(user=user, content_type=ct, object_id=str(content.pk))
    Save.objects.filter(pk=s.pk).update(saved_at=timezone.now() - timedelta(days=days_ago))


# Favoris : 2 aujourd'hui (2 élèves), 1 hier, 1 il y a 8 jours (élève 0, déjà venu cette semaine ou non).
saved(eleves[0], contents[0], 0)
saved(eleves[1], contents[0], 0)
saved(eleves[0], contents[1], 1)
saved(eleves[0], contents[2], 8)
for days_ago, n, v in ((0, 5, 3), (1, 2, 2)):
    d = today - timedelta(days=days_ago)
    if d >= admin_dashboard.USAGE_SINCE:
        UsageDaily.objects.create(date=d, kind=UsageDaily.KIND_ACTION, name='voir-solution', count=n, visitors=v)
        UsageDaily.objects.create(date=d, kind=UsageDaily.KIND_PAGE, name='/exercises/:id', count=n * 10, visitors=v)

cl = APIClient()
cl.force_authenticate(admin)
r = cl.get('/api/pilotage/serie/', {'source': 'base', 'cle': 'favoris', 'pas': 'jour'})
pts = r.data['points'] if r.status_code == 200 else []
check('jour par jour : 91 points, le dernier = aujourd’hui', r.status_code == 200 and len(pts) == 91
      and pts[-1]['debut'] == today.isoformat(), (r.status_code, len(pts)))
check('jour : aujourd’hui 2 favoris par 2 personnes, hier 1', pts and pts[-1]['valeur'] == 2 and pts[-1]['personnes'] == 2
      and pts[-2]['valeur'] == 1, pts[-2:])
check('libellé renvoyé', r.data.get('libelle') == 'Enregistrer (favoris)', r.data.get('libelle'))

r = cl.get('/api/pilotage/serie/', {'source': 'base', 'cle': 'favoris', 'pas': 'semaine'})
weeks = r.data['points'] if r.status_code == 200 else []
total = sum(w['valeur'] for w in weeks)
check('semaine : commence un lundi, total identique (4)', weeks and all(
    timezone.datetime.fromisoformat(w['debut']).weekday() == 0 for w in weeks) and total == 4, (total, weeks[:1]))
check('semaine en cours marquée incomplète', weeks and weeks[-1]['partiel'] is True)
cur = weeks[-1] if weeks else {}
in_week = [d for d in (0, 1) if (today - timedelta(days=d)) >= timezone.datetime.fromisoformat(cur.get('debut', '1970-01-01')).date()]
expected_people = len({0, 1} if 0 in in_week else set()) or 0
check('semaine : personnes distinctes (pas la somme des jours)',
      cur.get('personnes') == (2 if 0 in in_week else 0) or cur.get('personnes') <= 2, cur)

r = cl.get('/api/pilotage/serie/', {'source': 'navigateur', 'cle': 'voir-solution', 'pas': 'jour'})
pts = r.data['points'] if r.status_code == 200 else []
check('geste du navigateur : comptes du jour', r.status_code == 200 and (pts[-1]['valeur'] == 5 or today < admin_dashboard.USAGE_SINCE), pts[-1:])
check('avant le début des mesures : marqué « non mesuré »',
      all(not p['mesure'] for p in pts if p['debut'] < admin_dashboard.USAGE_SINCE.isoformat()))
r = cl.get('/api/pilotage/serie/', {'source': 'page', 'cle': '/exercises/:id', 'pas': 'semaine'})
check('page : semaine par semaine', r.status_code == 200 and sum(p['valeur'] for p in r.data['points']) == 70, r.data.get('points', [])[-2:])
check('clé inconnue refusée', cl.get('/api/pilotage/serie/', {'source': 'navigateur', 'cle': 'n-importe-quoi'}).status_code == 400)
check('source inconnue refusée', cl.get('/api/pilotage/serie/', {'source': 'x', 'cle': 'favoris'}).status_code == 400)
eleve = APIClient()
eleve.force_authenticate(eleves[0])
check('réservé aux administrateurs', eleve.get('/api/pilotage/serie/', {'source': 'base', 'cle': 'favoris'}).status_code == 403)

# ---------------------------------------------------------------- établissement d'origine
school = School.objects.create(name='Lycée Ibn Sina', city='Rabat', kind='lycee')
# Création de contenu réservée à l'équipe (12/10/2026) : l'administrateur publie.
prof = APIClient()
prof.force_authenticate(admin)
r = prof.post('/api/contents/', {'type': 'exercise', 'title': 'Avec école', 'difficulty': 'easy', 'subject': subject.pk,
                                 'class_levels': [level.pk], 'school': school.pk,
                                 'json_content': {'version': '2.1', 'blocks': []}}, format='json')
cid = r.data.get('id') if r.status_code in (200, 201) else None
check('création avec un établissement', r.status_code == 201 and cid, (r.status_code, r.data))
r = APIClient().get(f'/api/contents/{cid}/')
check('page du contenu : nom et ville de l’établissement (rien d’autre)', r.status_code == 200
      and r.data.get('school') == {'id': school.pk, 'name': 'Lycée Ibn Sina', 'city': 'Rabat'}, r.data.get('school'))
r = prof.patch(f'/api/contents/{cid}/', {'school': None}, format='json')
check('établissement retiré', r.status_code == 200 and Content.objects.get(pk=cid).school_id is None, r.status_code)
r = prof.post('/api/contents/', {'type': 'exercise', 'title': 'École inconnue', 'difficulty': 'easy', 'subject': subject.pk,
                                 'class_levels': [level.pk], 'school': 999999, 'json_content': {}}, format='json')
check('établissement inexistant refusé', r.status_code == 400, r.status_code)
School.objects.filter(pk=school.pk).delete()
check('établissement supprimé de la liste : le contenu reste', Content.objects.filter(title='Avec école').exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
