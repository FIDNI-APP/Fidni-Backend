"""Notifications de commentaires (apps/notifications) : qui est prévenu, regroupement, réponses, lecture."""
import os
import runpy
import sys
import tempfile
from datetime import date

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-notifications.sqlite3')
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
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.concours.models import ConcoursExam, SimulationSession  # noqa: E402
from apps.interactions.models import Complete, QuestionProgress, Save, StudyTimeDay, Vote  # noqa: E402
from apps.notifications.models import Notification  # noqa: E402
from apps.things.models import Comment, Content  # noqa: E402
from apps.users.models import ViewHistory  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def user(name, **kw):
    return User.objects.create_user(name, f'{name}@x.fr', 'Motdepasse-solide-42', **kw)


prof, aime, garde, reussi, evalue, travaille, passe, survole, x, y = (
    user(n) for n in ('prof', 'aime', 'garde', 'reussi', 'evalue', 'travaille', 'passe', 'survole', 'x', 'y'))
admin = User.objects.create_superuser('admin', 'admin@x.fr', 'Motdepasse-solide-42')
parti = user('parti', is_active=False)
discret = user('discret')
discret.profile.comment_notifications = False
discret.profile.save()
ex = Content.objects.create(type='exercise', title='Limites usuelles', author=prof, json_content={'blocks': []})
ct = ContentType.objects.get_for_model(Content)
sid = str(ex.id)
Vote.objects.create(user=aime, value=Vote.UP, content_type=ct, object_id=sid)
Save.objects.create(user=garde, content_type=ct, object_id=sid)
Complete.objects.create(user=reussi, content_type=ct, object_id=sid, status='success')
Complete.objects.create(user=parti, content_type=ct, object_id=sid, status='success')
Complete.objects.create(user=discret, content_type=ct, object_id=sid, status='success')
QuestionProgress.objects.create(user=evalue, content_type=ct, object_id=ex.id, question_path='q1', status='review')
StudyTimeDay.objects.create(user=travaille, object_id=ex.id, date=date.today(), seconds=300)
StudyTimeDay.objects.create(user=survole, object_id=ex.id, date=date.today(), seconds=30)
ViewHistory.objects.create(user=passe, content_type=ct, object_id=ex.id)
Comment.objects.create(content_item=ex, author=admin, content='Bienvenue !')  # l'admin a déjà commenté


def client(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(u)
    return c


def notified(kind='comment'):
    return set(Notification.objects.filter(target=f'content:{ex.id}', kind=kind).values_list('recipient__username', flat=True))


Notification.objects.all().delete()  # le commentaire de l'admin ci-dessus a pu prévenir le prof
r = client(x).post(f'/api/contents/{ex.id}/comment/', {'content': 'Je bloque   à la question 2,\nune idée ?'}, format='json')
check('commentaire publié', r.status_code == 201, r.status_code)
first = r.data['id']
check('prévenus : auteur, j\'aime, favori, réussi, question évaluée, 2 min de travail, admin qui a commenté',
      notified() == {'prof', 'aime', 'garde', 'reussi', 'evalue', 'travaille', 'admin'}, notified())
check('pas prévenus : l\'auteur du commentaire, un simple passage, 30 s, un compte désactivé, notifications coupées',
      not notified() & {'x', 'passe', 'survole', 'parti', 'discret'}, notified())
n = Notification.objects.get(recipient=aime)
check('contenu de la notification', n.title == 'Limites usuelles' and n.link == f'/exercises/{ex.id}'
      and n.excerpt == 'Je bloque à la question 2, une idée ?' and n.actor == x and n.count == 1, vars(n))

# Un deuxième commentaire avant lecture : la même notification, comptée deux fois.
client(y).post(f'/api/contents/{ex.id}/comment/', {'content': 'Moi aussi'}, format='json')
n = Notification.objects.get(recipient=aime)
check('regroupé tant que ce n\'est pas lu', Notification.objects.filter(recipient=aime).count() == 1
      and n.count == 2 and n.actor == y, (n.count, n.actor))
check('y (nouveau commentateur) n\'est pas prévenu de son propre commentaire', 'y' not in notified())

# API de la cloche
r = client(aime).get('/api/notifications/')
check('liste : non lues et lien vers le commentaire', r.status_code == 200 and r.data['unread'] == 1
      and r.data['results'][0]['url'] == f'/exercises/{ex.id}?commentaire={n.comment_id}#discussion'
      and r.data['results'][0]['actor']['username'] == 'y' and r.data['results'][0]['count'] == 2, r.data)
check('compteur', client(aime).get('/api/notifications/non-lues/').data == {'unread': 1})
check('visiteur : refusé', client().get('/api/notifications/').status_code in (401, 403))
r = client(aime).post('/api/notifications/lues/', {'ids': [n.id]}, format='json')
check('marquer lu', r.data == {'unread': 0} and Notification.objects.get(pk=n.pk).read_at is not None, r.data)
client(x).post(f'/api/contents/{ex.id}/comment/', {'content': 'Encore une question'}, format='json')
check('après lecture : une nouvelle notification', Notification.objects.filter(recipient=aime).count() == 2)
check('on ne voit pas celles des autres', all(x['title'] == 'Limites usuelles' for x in client(garde).get('/api/notifications/').data['results'])
      and client(garde).get('/api/notifications/').data['unread'] == 1)

# Réponse à un commentaire : son auteur reçoit « a répondu », pas « nouveau commentaire ».
Notification.objects.update(read_at=None)
r = client(aime).post(f'/api/contents/{ex.id}/comment/', {'content': '@x regarde le théorème', 'parent': first}, format='json')
check('réponse publiée', r.status_code == 201, r.status_code)
check('l\'auteur du commentaire reçoit « réponse »', notified('reply') == {'x'}, notified('reply'))
check('… et pas en plus « nouveau commentaire » pour la même réponse',
      Notification.objects.filter(recipient=x, kind='comment').count() == 1)  # celle du commentaire de y

r = client(garde).post('/api/notifications/lues/', {}, format='json')
check('tout marquer comme lu', r.data == {'unread': 0}, r.data)

# Commentaire supprimé (seul de sa notification) : la notification part avec lui.
c = Comment.objects.create(content_item=ex, author=y, content='À supprimer')
before = Notification.objects.filter(comment_id=c.id).count()
Notification.objects.filter(comment_id=c.id).update(count=1)
c.delete()
check('commentaire supprimé : ses notifications aussi', before > 0 and not Notification.objects.filter(comment_id=c.id).exists(), before)

# Concours : ceux qui ont passé le sujet sont prévenus, lien vers les commentaires de la page.
exam = ConcoursExam.objects.create(concours_type=ConcoursExam._meta.get_field('concours_type').choices[0][0], year=2024,
                                   created_by=admin)
SimulationSession.objects.create(user=travaille, mode='exam', concours_type=exam.concours_type, exam=exam, duration_minutes=60)
r = client(x).post(f'/api/concours/exams/{exam.id}/comments/', {'content': 'Le QCM 3 est faux ?'}, format='json')
n = Notification.objects.filter(target=f'concours-exam:{exam.id}', recipient=travaille).first()
check('concours : prévenu après une simulation', r.status_code == 201 and n is not None and n.link == f'/concours/exams/{exam.id}', r.status_code)
check('concours : lien vers les commentaires', client(travaille).get('/api/notifications/').data['results'][0]['url']
      == f'/concours/exams/{exam.id}#commentaires')

ex.delete()
check('contenu supprimé : ses notifications aussi', not Notification.objects.filter(target=f'content:{ex.id}').exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
