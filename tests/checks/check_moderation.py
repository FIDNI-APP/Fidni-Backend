"""Modération : l'administration peut supprimer tout contenu publié par un membre ; un autre membre non."""
import io
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-moderation.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false',
                   'MEDIA_ROOT': os.path.join(tempfile.gettempdir(), 'fidni-moderation-media')})
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
from django.core.files.base import ContentFile  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import ClassLevel, Subject  # noqa: E402
from apps.concours.models import ConcoursComment  # noqa: E402
from apps.things.models import Comment, Content, ProposedSolution  # noqa: E402
from apps.uploads.models import FileAttachment  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(user):
    cache.clear()  # limites anti-abus : chaque requête du test part d'un compteur neuf
    c = APIClient()
    c.force_authenticate(user)
    return c


PW = 'Motdepasse-solide-42'
alice = User.objects.create_user('alice', 'alice@x.fr', PW)
bob = User.objects.create_user('bob', 'bob@x.fr', PW)
admin = User.objects.create_user('chef', 'chef@x.fr', PW, is_staff=True, is_superuser=True)
level = ClassLevel.objects.create(name='2ème Bac SM', order=1)
subject = Subject.objects.create(name='Mathématiques')


def attach(obj, name):
    att = FileAttachment(content_type=ContentType.objects.get_for_model(type(obj)), object_id=obj.pk, uploaded_by=alice,
                         file_name=name, file_size=3, mime_type='image/png')
    att.file.save(name, ContentFile(b'png'), save=False)
    att.save()
    return att


def make_content():
    c = Content.objects.create(type='exercise', title='Exo', author=alice, subject=subject,
                               json_content={'version': '2.1', 'blocks': []})
    c.class_levels.add(level)
    return c


# ---- contenu (exercice) avec figure, commentaire photo, solution proposée photo
c = make_content()
fig = attach(c, 'figure.png')
com = Comment.objects.create(content_item=c, author=bob, content='Bravo')
com_img = attach(com, 'photo-com.png')
ps = ProposedSolution.objects.create(content_item=c, author=bob, body='<p>Ma solution</p>')
ps_img = attach(ps, 'photo-sol.png')
paths = [fig.file.path, com_img.file.path, ps_img.file.path]

r = client(bob).delete(f'/api/contents/{c.pk}/')
check('un autre membre ne peut pas supprimer le contenu d’alice', r.status_code == 403 and Content.objects.filter(pk=c.pk).exists(), r.status_code)
r = client(admin).delete(f'/api/contents/{c.pk}/')
check('l’administration supprime le contenu d’alice', r.status_code == 204 and not Content.objects.filter(pk=c.pk).exists(), r.status_code)
check('… ses commentaires et solutions proposées partent avec lui',
      not Comment.objects.filter(pk=com.pk).exists() and not ProposedSolution.objects.filter(pk=ps.pk).exists())
check('… et tous les fichiers liés (figure, photos) sont effacés',
      not FileAttachment.objects.filter(pk__in=[fig.pk, com_img.pk, ps_img.pk]).exists() and not any(os.path.exists(p) for p in paths))

# ---- commentaire et solution proposée d'un autre membre
c = make_content()
com = Comment.objects.create(content_item=c, author=bob, content='Spam')
r = client(alice).delete(f'/api/comments/{com.pk}/')
check('l’auteur du contenu ne supprime pas le commentaire de bob', r.status_code == 403, r.status_code)
r = client(admin).delete(f'/api/comments/{com.pk}/')
check('l’administration supprime le commentaire de bob', r.status_code == 204 and not Comment.objects.filter(pk=com.pk).exists(), r.status_code)

ps = ProposedSolution.objects.create(content_item=c, author=bob, body='<p>Hors sujet</p>')
r = client(alice).delete(f'/api/proposed-solutions/{ps.pk}/')
check('un autre membre ne supprime pas la solution proposée de bob', r.status_code in (403, 404), r.status_code)
r = client(admin).delete(f'/api/proposed-solutions/{ps.pk}/')
check('l’administration supprime la solution proposée de bob', r.status_code == 204 and not ProposedSolution.objects.filter(pk=ps.pk).exists(), r.status_code)

# ---- commentaire d'un concours
cc = ConcoursComment.objects.create(target_type='exam', target_id=1, author=bob, content='Hors sujet')
r = client(alice).delete(f'/api/concours/comments/{cc.pk}/')
check('un autre membre ne supprime pas un commentaire de concours', r.status_code == 403, r.status_code)
r = client(admin).delete(f'/api/concours/comments/{cc.pk}/')
check('l’administration supprime un commentaire de concours', r.status_code in (200, 204) and not ConcoursComment.objects.filter(pk=cc.pk).exists(), r.status_code)

# ---- l'auteur garde la main sur ses propres contenus
c = make_content()
r = client(alice).delete(f'/api/contents/{c.pk}/')
check('l’auteur supprime toujours son propre contenu', r.status_code == 204, r.status_code)

# ---- statistiques (onglet Activité) : à jour dès l'auto-évaluation, malgré le cache de 5 min
c = make_content()
c.json_content = {'version': '2.1', 'blocks': [{'id': 'q1', 'type': 'question', 'content': {'type': 'text', 'html': 'Q'}}]}
c.save()
cl = client(bob)
r1 = cl.get(f'/api/contents/{c.pk}/statistics/')
cl.post(f'/api/contents/{c.pk}/assess_question/', {'question_path': 'q1', 'status': 'success'}, format='json')
r2 = cl.get(f'/api/contents/{c.pk}/statistics/')
check('statistiques : l’auto-évaluation est prise en compte immédiatement',
      r1.status_code == 200 and r1.data.get('user_assessed') is False and r2.data.get('user_assessed') is True,
      (r1.data.get('user_assessed'), r2.data.get('user_assessed')))

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
