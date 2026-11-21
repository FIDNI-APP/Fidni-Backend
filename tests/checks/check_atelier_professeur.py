"""Connexion navigateur → autorisation limitée → vérification et dépôt d'un seul brouillon."""
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import secrets
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'src'), str(root)]
temp = tempfile.TemporaryDirectory()
os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_ENV='development',
                  DB_ENGINE='sqlite', SQLITE_PATH=str(Path(temp.name) / 'test.sqlite3'), AWS_STORAGE_ENABLED='false')
import django
django.setup()
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework.test import APIClient
from apps.ia.models import IAJob
from apps.things.models import Content

call_command('migrate', verbosity=0)
runpy.run_path(str(root / 'tests/base_tables.py'))
admin = get_user_model().objects.create_user('prof-test', is_superuser=True)
eleve = get_user_model().objects.create_user('eleve-test')
secret = secrets.token_hex(32)
request = {'empreinte': hashlib.sha256(secret.encode()).hexdigest()}
client = APIClient()
client.force_authenticate(eleve)
assert client.post('/api/atelier/autoriser/', request).status_code == 403
client.force_authenticate(admin)
grant = client.post('/api/atelier/autoriser/', request).json()['autorisation']
client.force_authenticate(None)
client.credentials(HTTP_AUTHORIZATION='Atelier ' + grant + '.' + '0' * 64)
assert client.get('/api/atelier/etat/').status_code == 401
client.credentials(HTTP_AUTHORIZATION='Atelier ' + grant + '.' + secret)
assert client.get('/api/atelier/etat/').json() == {'compte': 'prof-test'}
assert client.get('/api/pilotage/brouillons/').status_code in (401, 403)
f = {'format':'fidni-fiche/1','cle':'exemple-atelier','type':'exercice','titre':'Une intégrale',
     'niveaux':['2ème Bac SM'],'chapitres':['Calcul intégral'],'difficulte':'facile',
     'source':{'document':'serie.pdf','origine':'autorise','note':'Accord du professeur','pages':'1'},
     'blocs':[{'type':'question','html':'<p>Calculer une intégrale.</p>','solution':'<p>Une primitive suffit.</p>',
               'difficulte':'facile','theoremes':[]}]}
original = b'%PDF-1.4 exemple'
def envoyer(action, avec_source=True):
    data = io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('fiche.json', json.dumps(f))
        if avec_source:
            z.writestr('document/serie.pdf', original)
    return client.post('/api/atelier/fiches/' + action + '/', {'fiche':SimpleUploadedFile('fiche.zip',data.getvalue())})
assert 'apercu' in envoyer('verifier').json()
assert envoyer('deposer', False).status_code == 400
first = envoyer('deposer').json()['id']
assert envoyer('deposer').json()['id'] == first
job = IAJob.objects.get(pk=first)
assert job.created_by == admin and bytes(job.files.get().data) == original and Content.objects.count() == 0
admin.is_superuser = False
admin.save()
assert client.get('/api/atelier/etat/').status_code == 401
print('OK : compte, portée, preuve du poste, révocation, validation et dépôt idempotent.')
