"""Signalements d'erreurs sur les contenus : envoi par un élève, question désignée, suivi par l'admin."""
import os
import sys
import tempfile


BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-reports.sqlite3')
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
from rest_framework.test import APIClient  # noqa: E402
from apps.things.models import Content, ContentReport  # noqa: E402
from apps.users.account_deletion import delete_account  # noqa: E402
from apps.users.legal import export_user_data  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


editorial = User.objects.create_user('Fidni', 'fidni@x.fr', None)
alice = User.objects.create_user('alice', 'alice@x.fr', 'Motdepasse-solide-42')
admin = User.objects.create_superuser('patron', 'patron@x.fr', 'Motdepasse-solide-42')

exo = Content.objects.create(type='exercise', title='Limites', author=editorial, json_content={'version': '2.1', 'blocks': [
    {'type': 'context', 'id': 'ctx', 'content': {'html': '<p>Soit f…</p>'}},
    {'type': 'question', 'id': 'q1', 'content': {'html': '<p>Calculer</p>'}},
    {'type': 'question', 'id': 'q2', 'content': {'html': '<p>Étudier</p>'}, 'subQuestions': [{'id': 'sq1'}, {'id': 'sq2'}]},
]})
lecon = Content.objects.create(type='lesson', title='Cours', author=editorial, json_content={'version': '1', 'sections': [
    {'id': 's1', 'title': 'Définitions', 'subSections': [{'id': 'ss1', 'title': 'Limite finie'}]},
]})
url = f'/api/contents/{exo.id}/report/'

anon = APIClient()
r = anon.post(url, {'reason': 'statement'}, format='json')
check('visiteur : connexion demandée', r.status_code in (401, 403), r.status_code)

c = APIClient()
c.force_authenticate(alice)
r = c.post(url, {'reason': 'solution', 'item_path': 'q2.sq1', 'item_label': 'Question 2.1', 'description': 'Le signe est faux.'}, format='json')
check('signalement complet (raison, question, description)', r.status_code == 201, (r.status_code, r.data))
rep = ContentReport.objects.get(pk=r.data['id'])
check('enregistré tel quel', (rep.reason, rep.item_path, rep.item_label, rep.description, rep.status, rep.user_id)
      == ('solution', 'q2.sq1', 'Question 2.1', 'Le signe est faux.', 'open', alice.id))

r = c.post(url, {'reason': 'statement'}, format='json')
check('question et description facultatives', r.status_code == 201 and ContentReport.objects.get(pk=r.data['id']).item_path == '', r.data)
r = c.post(url, {'reason': 'typo', 'item_path': 'ctx', 'item_label': 'Énoncé'}, format='json')
check('énoncé général désignable', r.status_code == 201, r.data)

r = c.post(url, {'reason': 'solution', 'item_path': 'q2.sq1', 'description': 'Et la 2.2 aussi.'}, format='json')
check('même signalement en double : complété, pas doublé', r.status_code == 200 and r.data['duplicate']
      and ContentReport.objects.filter(content=exo, reason='solution').count() == 1
      and ContentReport.objects.get(content=exo, reason='solution').description == 'Et la 2.2 aussi.', r.data)

r = c.post(url, {'reason': 'nimportequoi'}, format='json')
check('raison inconnue refusée', r.status_code == 400 and 'reason' in r.data, r.status_code)
r = c.post(url, {'reason': 'scale'}, format='json')
check('barème refusé hors examen', r.status_code == 400, r.status_code)
r = c.post(url, {'reason': 'statement', 'item_path': 'q9'}, format='json')
check('question inexistante refusée', r.status_code == 400 and 'item_path' in r.data, r.status_code)
r = c.post(url, {'reason': 'other', 'description': 'x' * 1001}, format='json')
check('description trop longue refusée', r.status_code == 400, r.status_code)
r = c.post(f'/api/contents/{lecon.id}/report/', {'reason': 'statement', 'item_path': 's1.ss1', 'item_label': 'Partie 1.1'}, format='json')
check('leçon : sous-partie désignable', r.status_code == 201, r.data)
r = c.post('/api/contents/99999/report/', {'reason': 'statement'}, format='json')
check('contenu inexistant : 404', r.status_code == 404, r.status_code)

# Suivi par les administrateurs
r = c.get('/api/pilotage/signalements/')
check('liste réservée aux administrateurs', r.status_code == 403, r.status_code)
a = APIClient()
a.force_authenticate(admin)
r = a.get('/api/pilotage/signalements/')
check('admin : signalements à traiter', r.status_code == 200 and r.data['counts']['open'] == 4 and len(r.data['results']) == 4, r.data)
first = next(x for x in r.data['results'] if x['reason'] == 'solution')
check('admin : contenu, question, élève, lien', first['content']['url'] == f'/exercises/{exo.id}'
      and first['item_label'] == 'Question 2.1' and first['user'] == 'alice' and first['reason_label'] == 'Erreur dans la solution', first)

r = a.patch(f"/api/pilotage/signalements/{first['id']}/", {'status': 'resolved'}, format='json')
check('marquer corrigé', r.status_code == 200 and r.data['status'] == 'resolved' and r.data['handled_by'] == 'patron', r.data)
r = a.get('/api/pilotage/signalements/')
check('corrigé : sort de la file', r.data['counts'] == {'open': 3, 'resolved': 1, 'dismissed': 0}, r.data['counts'])
r = a.get('/api/pilotage/signalements/?statut=all')
check('historique complet', len(r.data['results']) == 4, len(r.data['results']))
r = a.patch(f"/api/pilotage/signalements/{first['id']}/", {'status': 'open'}, format='json')
check('rouvrir', r.status_code == 200 and r.data['handled_at'] is None, r.data)
r = c.patch(f"/api/pilotage/signalements/{first['id']}/", {'status': 'dismissed'}, format='json')
check('un élève ne traite pas les signalements', r.status_code == 403, r.status_code)

# Bandeau « correction à vérifier » : validé par un administrateur depuis le site
Content.objects.filter(pk=exo.pk).update(json_content={**exo.json_content, 'a_verifier': True})
r = c.post(f'/api/contents/{exo.id}/verification/', {'verifie': True}, format='json')
check('vérification : réservée aux administrateurs', r.status_code == 403, r.status_code)
r = a.post(f'/api/contents/{exo.id}/verification/', {'verifie': True}, format='json')
exo.refresh_from_db()
check('vérification : bandeau retiré', r.status_code == 200 and 'a_verifier' not in exo.json_content
      and exo.json_content.get('blocks'), r.data)
r = a.post(f'/api/contents/{exo.id}/verification/', {'verifie': False}, format='json')
exo.refresh_from_db()
check('vérification : bandeau remis', r.status_code == 200 and exo.json_content.get('a_verifier') is True, r.data)
check('vérification : booléen exigé', a.post(f'/api/contents/{exo.id}/verification/', {'verifie': 'oui'}, format='json').status_code == 400)

# RGPD : dans l'export, effacés avec le compte
check('export des données : signalements inclus', len(export_user_data(alice).get('things.ContentReport', [])) == 4)
delete_account(alice, keep_contributions=True)
check('compte supprimé : signalements effacés', ContentReport.objects.count() == 0, ContentReport.objects.count())

print(f'{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
