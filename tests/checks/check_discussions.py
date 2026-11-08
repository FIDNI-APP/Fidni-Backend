"""Espace Discussions (08/11/2026) : créer, taguer des contenus, lister (salon, niveau, chapitre, contenu, recherche,
tris), répondre, « utile », suivre, notifications (aidants, réponses, mentions), droits, panneau, compteur, recherche
de contenus, suppression de compte, et reprise des commentaires (migration 0002)."""
import importlib
import os
import runpy
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-discussions.sqlite3')
os.environ.update({'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ENV': 'development', 'DB_ENGINE': 'sqlite',
                   'SQLITE_PATH': DB, 'AWS_STORAGE_ENABLED': 'false'})
if os.path.exists(DB):
    os.remove(DB)
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
call_command('migrate', verbosity=0)
runpy.run_path(os.path.join(BACKEND, 'tests', 'base_tables.py'))
from django.apps import apps as django_apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Subject  # noqa: E402
from apps.classrooms.models import Classroom, ClassroomMembership, ClassroomSubject  # noqa: E402
from apps.discussions.models import Discussion, Follow, Reply  # noqa: E402
from apps.discussions.services import MAX_AIDANTS, aidants, notify_new_discussion, notify_new_reply  # noqa: E402
from apps.interactions.models import Complete, Vote  # noqa: E402
from apps.notifications.models import Notification  # noqa: E402
from apps.things.models import Comment, Content  # noqa: E402
from apps.users.account_deletion import DELETED_USERNAME, delete_account  # noqa: E402

settings.ALLOWED_HOSTS = ['*']
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('OK   ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))


def client(u=None):
    c = APIClient()
    if u:
        c.force_authenticate(u)
    return c


cache.clear()
pw = 'Motdepasse-solide-42'
sm = ClassLevel.objects.create(name='2ème Bac SM X', order=990)
pc = ClassLevel.objects.create(name='2ème Bac PC X', order=991)
maths = Subject.objects.create(name='Maths X')
physique = Subject.objects.create(name='Physique X')
limites = Chapter.objects.create(name='Limites X', subject=maths)
equipe = User.objects.create_user('equipe', 'e@x.fr', pw, is_staff=True)
prof = User.objects.create_user('prof', 'p@x.fr', pw)
prof.profile.user_type = 'teacher'
prof.profile.save()
prof_phy = User.objects.create_user('profphy', 'pp@x.fr', pw)
amina, badr, chaima = (User.objects.create_user(n, f'{n}@x.fr', pw) for n in ('amina', 'badr', 'chaima'))
eleves = [User.objects.create_user(f'e{i}', f'e{i}@x.fr', pw) for i in range(12)]
for u in [amina, badr, chaima, *eleves]:
    u.profile.class_level = sm
    u.profile.save()
chaima.profile.class_level = pc
chaima.profile.save()

ex = Content.objects.create(type='exercise', title='Étude d’une fonction', author=equipe, subject=maths, difficulty='medium',
                            json_content={'blocks': []})
ex.class_levels.add(sm)
ex.chapters.add(limites)
lecon = Content.objects.create(type='lesson', title='Limites et continuité', author=equipe, subject=maths, json_content={})
lecon.class_levels.add(sm)
ex_pc = Content.objects.create(type='exercise', title='Ondes mécaniques', author=equipe, subject=physique, json_content={})
ex_pc.class_levels.add(pc)

classe = Classroom.objects.create(name='TS1', owner=prof, class_level=sm)
ClassroomMembership.objects.create(classroom=classe, student=amina)
ClassroomSubject.objects.create(classroom=classe, subject=maths, teacher=prof)
ClassroomSubject.objects.create(classroom=classe, subject=physique, teacher=prof_phy)
ct = ContentType.objects.get_for_model(Content)
Complete.objects.create(user=badr, content_type=ct, object_id=str(ex.id), status='success')
for e in eleves:
    Complete.objects.create(user=e, content_type=ct, object_id=str(ex.id), status='success')

# --- Créer ---------------------------------------------------------------------------------------------------------
Notification.objects.all().delete()
r = client(amina).post('/api/discussions/', {
    'title': 'Limite en +∞ : la forme ∞ − ∞', 'body': '<p>Je bloque, @badr tu as une idée ? $\\lim f$</p>',
    'salon': 'entraide', 'content_ids': [ex.id, lecon.id]}, format='json')
check('discussion créée, contenus tagués en cartes', r.status_code == 201 and [t['id'] for t in r.data['tags']] == [ex.id, lecon.id]
      and r.data['tags'][0]['chapter'] == 'Limites X' and r.data['tags'][0]['level'] == sm.name, getattr(r, 'data', r))
d1 = Discussion.objects.get(pk=r.data['id'])
check('niveau de l\'auteur par défaut, auteur suivi d\'office', d1.class_level_id == sm.id and Follow.objects.filter(discussion=d1, user=amina).exists())
check('auteur : repère du niveau', r.data['author']['role'] == 'eleve' and r.data['author']['level'] == sm.name, r.data['author'])
for bad, why in (({'title': 'ok'}, 'titre trop court'), ({'title': 'Titre correct', 'salon': 'bidon'}, 'salon inconnu'),
                 ({'title': 'Titre correct', 'content_ids': [999999]}, 'contenu inexistant'),
                 ({'title': 'Titre correct', 'content_ids': 'abc'}, 'contenus illisibles'),
                 ({'title': 'Titre correct', 'content_ids': list(range(1, 8))}, 'trop de contenus'),
                 ({'title': 'Titre correct', 'class_level': 999999}, 'niveau inconnu')):
    r = client(amina).post('/api/discussions/', bad, format='json')
    check(f'refusé : {why}', r.status_code == 400, (r.status_code, getattr(r, 'data', None)))
check('visiteur : écrire refusé', client().post('/api/discussions/', {'title': 'Titre correct'}, format='json').status_code == 401)

# Notifications d'une nouvelle discussion (envoyées après validation : appel direct ici).
notify_new_discussion(d1)
kinds = {n.recipient.username: n.kind for n in Notification.objects.filter(target=f'discussion:{d1.id}')}
check('mention @badr : « mention »', kinds.get('badr') == 'mention', kinds)
check('équipe et professeur de maths de la classe : « discussion »', kinds.get('equipe') == 'discussion' and kinds.get('prof') == 'discussion', kinds)
check('professeur d\'une autre matière : pas prévenu', 'profphy' not in kinds, kinds)
check('au plus MAX_AIDANTS élèves sollicités', sum(1 for k in kinds if k.startswith('e') and k != 'equipe') == MAX_AIDANTS, kinds)
check('l\'auteur n\'est pas prévenu', 'amina' not in kinds)
n = Notification.objects.filter(recipient=equipe, target=f'discussion:{d1.id}').first()
r = client(equipe).get('/api/notifications/')
url = next((x['url'] for x in r.data.get('results', r.data) if x['id'] == n.id), None) if n else None
check('lien de la notification : la discussion', url == f'/discussions/{d1.id}', url)

# Limite par jour : 3 sollicitations par élève (notifications regroupées tant que non lues : marquées lues).
for i in range(4):
    Notification.objects.update(read_at=timezone.now())
    d = Discussion.objects.create(title=f'Autre {i} sur la fonction', author=amina, class_level=sm)
    d.contents.add(ex)
    notify_new_discussion(d)
par_eleve = [Notification.objects.filter(recipient=e, kind='discussion').count() for e in eleves]
check('limite par jour : jamais plus de 3 sollicitations par élève', max(par_eleve) <= 3, par_eleve)
sans_tag = Discussion.objects.create(title='Orientation après le bac', author=amina, salon='orientation', class_level=None)
check('sans contenu tagué : équipe et professeurs seulement', aidants(sans_tag) == {equipe.id, prof.id, prof_phy.id}, aidants(sans_tag))

# --- Répondre, utile, suivre ---------------------------------------------------------------------------------------
Notification.objects.all().delete()
r = client(badr).post(f'/api/discussions/{d1.id}/repondre/', {'body': '<p>Factorise par $x$.</p>'}, format='json')
check('réponse publiée', r.status_code == 201 and r.data['author']['username'] == 'badr', getattr(r, 'data', r))
rep1 = Reply.objects.get(pk=r.data['id'])
d1.refresh_from_db()
check('compteur de réponses et dernière activité à jour', d1.reply_count == 1 and d1.last_activity_at == rep1.created_at)
check('celui qui répond suit la discussion', Follow.objects.filter(discussion=d1, user=badr).exists())
notify_new_reply(rep1)
check('l\'auteur (qui suit) est prévenu : « reponse »', Notification.objects.filter(recipient=amina, kind='reponse', comment_id=rep1.id).exists())
r = client(chaima).post(f'/api/discussions/{d1.id}/repondre/', {'body': 'Merci @amina', 'reply_to': rep1.id}, format='json')
rep2 = Reply.objects.get(pk=r.data['id'])
check('en réponse à : gardé', r.status_code == 201 and r.data['reply_to'] == {'id': rep1.id, 'username': 'badr'}, getattr(r, 'data', r))
Notification.objects.all().delete()
notify_new_reply(rep2)
got = {n.recipient.username: n.kind for n in Notification.objects.all()}
check('réponse à badr : badr prévenu ; @amina : mention', got.get('badr') == 'reponse' and got.get('amina') == 'mention', got)
autre = Discussion.objects.create(title='Une autre discussion', author=badr)
r = client(amina).post(f'/api/discussions/{d1.id}/repondre/', {'body': 'x', 'reply_to': Reply.objects.create(discussion=autre, author=badr, body='y').id}, format='json')
check('en réponse à une réponse d\'une autre discussion : refusé', r.status_code == 400)
check('réponse vide : refusée', client(amina).post(f'/api/discussions/{d1.id}/repondre/', {'body': '<p> </p>'}, format='json').status_code == 400)

r = client(badr).post(f'/api/discussions/{d1.id}/utile/')
check('« utile » sur la discussion', r.status_code == 200 and r.data == {'utile': 1, 'user_utile': True}, getattr(r, 'data', r))
r = client(badr).post(f'/api/discussions/{d1.id}/utile/')
check('« utile » une seconde fois : retiré', r.data == {'utile': 0, 'user_utile': False}, r.data)
check('« utile » sur son propre message : refusé', client(amina).post(f'/api/discussions/{d1.id}/utile/').status_code == 400)
client(amina).post(f'/api/discussions/reponses/{rep1.id}/utile/')
client(chaima).post(f'/api/discussions/reponses/{rep1.id}/utile/')
client(chaima).post(f'/api/discussions/{d1.id}/utile/')
r = client(chaima).post(f'/api/discussions/{d1.id}/suivre/')
check('suivre (bascule)', r.status_code == 200 and r.data['followed'] is False, getattr(r, 'data', r))  # suivait déjà (a répondu)
r = client(chaima).post(f'/api/discussions/{d1.id}/suivre/')
check('suivre à nouveau', r.data['followed'] is True, r.data)

# --- Détail ------------------------------------------------------------------------------------------------------------
r = client(badr).get(f'/api/discussions/{d1.id}/')
check('détail : corps, réponses dans l\'ordre, utiles', r.status_code == 200 and '<p>' in r.data['body']
      and [x['id'] for x in r.data['replies']][:2] == [rep1.id, rep2.id] and r.data['replies'][0]['utile'] == 2
      and r.data['utile'] == 1, getattr(r, 'data', r))
check('détail : statut de l\'élève sur le contenu tagué', r.data['tags'][0]['status'] == 'success', r.data['tags'][0])
check('détail : derniers à répondre', {x['username'] for x in r.data['repliers']} >= {'badr', 'chaima'}, r.data['repliers'])
check('visiteur : lecture du détail', client().get(f'/api/discussions/{d1.id}/').status_code == 200)
seul = Discussion.objects.create(title='Je me réponds à moi-même', author=badr, class_level=sm)
Reply.objects.create(discussion=seul, author=badr, body='précision')
cards = {x['id']: x for x in client().get('/api/discussions/?niveau=tous').data['results']}
check('« répondue » : réponse d\'un autre membre seulement', cards[d1.id]['answered'] is True and cards[seul.id]['answered'] is False,
      (cards[d1.id]['answered'], cards[seul.id]['answered']))
seul.delete()

# --- Liste ---------------------------------------------------------------------------------------------------------
pc_disc = Discussion.objects.create(title='Ondes : la célérité', author=chaima, class_level=pc, salon='methodes')
pc_disc.contents.add(ex_pc)
r = client(badr).get('/api/discussions/')
ids = [x['id'] for x in r.data['results']]
check('liste : niveau de l\'élève par défaut (et les discussions sans niveau)', d1.id in ids and sans_tag.id in ids and pc_disc.id not in ids, ids)
check('liste : la plus active d\'abord', ids[0] in (d1.id, rep1.discussion_id, autre.id), ids[:3])
r = client(badr).get('/api/discussions/?niveau=tous&salon=methodes')
check('salon', [x['id'] for x in r.data['results']] == [pc_disc.id], r.data)
r = client(badr).get(f'/api/discussions/?niveau=tous&chapitre={limites.id}')
check('chapitre (via les contenus tagués)', d1.id in [x['id'] for x in r.data['results']] and pc_disc.id not in [x['id'] for x in r.data['results']])
r = client(badr).get(f'/api/discussions/?niveau=tous&contenu={lecon.id}')
check('contenu tagué (onglet « Discussions » d\'un contenu)', [x['id'] for x in r.data['results']] == [d1.id], r.data)
r = client(badr).get('/api/discussions/?niveau=tous&q=celerite')
check('recherche sans accents', [x['id'] for x in r.data['results']] == [pc_disc.id], r.data)
r = client(badr).get('/api/discussions/?niveau=tous&tri=sans_reponse')
check('sans réponse : d1 n\'y est pas', d1.id not in [x['id'] for x in r.data['results']] and pc_disc.id in [x['id'] for x in r.data['results']])
r = client(badr).get('/api/discussions/?niveau=tous&tri=populaires')
check('populaires : la plus « utile » d\'abord', r.data['results'][0]['id'] == d1.id, [x['id'] for x in r.data['results']])
r = client(chaima).get('/api/discussions/?niveau=tous&tri=suivies')
check('suivies : celles qu\'il suit (réponse = suivie d\'office)', {x['id'] for x in r.data['results']} == {d1.id}, [x['id'] for x in r.data['results']])
check('suivies sans compte : refusé', client().get('/api/discussions/?tri=suivies').status_code == 401)
check('tri inconnu : refusé', client().get('/api/discussions/?tri=bidon').status_code == 400)
r = client().get('/api/discussions/?niveau=abc')
check('niveau illisible : seulement les discussions sans niveau', all(x['class_level'] is None for x in r.data['results']), r.data)

# --- Modifier, supprimer -------------------------------------------------------------------------------------------
check('modifier : réservé à l\'auteur', client(badr).patch(f'/api/discussions/{d1.id}/', {'title': 'Piraté !!'}, format='json').status_code == 403)
r = client(amina).patch(f'/api/discussions/{d1.id}/', {'title': 'Limite en +∞ : forme ∞ − ∞', 'content_ids': [ex.id]}, format='json')
check('modifier par l\'auteur : titre, tags, date de modification', r.status_code == 200 and r.data['edited_at']
      and [t['id'] for t in r.data['tags']] == [ex.id], getattr(r, 'data', r))
check('modifier une réponse : réservé à l\'auteur', client(amina).patch(f'/api/discussions/reponses/{rep1.id}/', {'body': 'x'}, format='json').status_code == 403)
r = client(equipe).delete(f'/api/discussions/reponses/{rep2.id}/')
d1.refresh_from_db()
check('l\'équipe supprime une réponse : compteur recalculé', r.status_code == 204 and d1.reply_count == 1, (r.status_code, d1.reply_count))
tmp = Discussion.objects.create(title='À supprimer bientôt', author=badr)
Notification.objects.create(recipient=amina, kind='discussion', target=f'discussion:{tmp.id}', title='x', link='/x')
check('supprimer : réservé à l\'auteur', client(amina).delete(f'/api/discussions/{tmp.id}/').status_code == 403)
check('supprimer par l\'auteur, notifications effacées', client(badr).delete(f'/api/discussions/{tmp.id}/').status_code == 204
      and not Notification.objects.filter(target=f'discussion:{tmp.id}').exists())

# --- Panneau, compteur, contenus à taguer --------------------------------------------------------------------------
r = client(badr).get('/api/discussions/panneau/?niveau=tous')
check('panneau : salons et nombres', r.status_code == 200 and {s['key'] for s in r.data['salons']} == {'entraide', 'methodes', 'bac', 'orientation'}
      and r.data['total'] == Discussion.objects.count(), getattr(r, 'data', r))
check('panneau : contenu le plus discuté', r.data['tendances'] and r.data['tendances'][0]['content']['id'] == ex.id, r.data['tendances'])
check('panneau : membre le plus utile (votes reçus)', r.data['utiles'] and r.data['utiles'][0]['author']['username'] == 'badr', r.data['utiles'])
r = client(badr).get('/api/discussions/compteur/')
attendu = sum(1 for d in Discussion.objects.exclude(author=badr)
              if d.class_level_id in (sm.id, None) and not d.replies.exclude(author=d.author).exists())
check('compteur : sans réponse à son niveau, hors les siennes', r.status_code == 200 and r.data['sans_reponse'] == attendu, (r.data, attendu))
check('compteur réservé aux connectés', client().get('/api/discussions/compteur/').status_code in (401, 403))
r = client(amina).get('/api/discussions/contenus/?q=fonction')
check('contenus à taguer : recherche', r.status_code == 200 and r.data['results'] and r.data['results'][0]['id'] == ex.id, getattr(r, 'data', r))
r = client(amina).get(f'/api/discussions/contenus/?q={ex.id}')
check('contenus à taguer : par numéro', ex.id in [x['id'] for x in r.data['results']], r.data)
check('contenus à taguer : réservé aux connectés', client().get('/api/discussions/contenus/?q=fonction').status_code in (401, 403))

# --- Suppression de compte : les discussions restent, au nom de « Compte supprimé » -------------------------------------
partant = User.objects.create_user('partant', 'pa@x.fr', pw)
dp = Discussion.objects.create(title='Discussion d’un partant', author=partant)
Reply.objects.create(discussion=d1, author=partant, body='réponse')
delete_account(partant, keep_contributions=True)
dp.refresh_from_db()
check('compte supprimé : discussions et réponses gardées', dp.author.username == DELETED_USERNAME
      and Reply.objects.filter(author__username=DELETED_USERNAME, discussion=d1).exists())

# --- Reprise des commentaires (migration 0002) ---------------------------------------------------------------------
Discussion.objects.all().delete()
t0 = timezone.now() - timedelta(days=10)
c1 = Comment.objects.create(content_item=ex, author=amina, content='<p>Pourquoi la dérivée change de signe ? Je ne vois pas.</p>')
c2 = Comment.objects.create(content_item=ex, author=badr, content='<p>Factorise.</p>', parent=c1)
c3 = Comment.objects.create(content_item=ex, author=amina, content='<p>Merci !</p>', parent=c2)
c4 = Comment.objects.create(content_item=lecon, author=chaima, content='merci')
for i, c in enumerate((c1, c2, c3, c4)):
    Comment.objects.filter(pk=c.pk).update(created_at=t0 + timedelta(hours=i))
ct_comment = ContentType.objects.get_for_model(Comment)
Vote.objects.create(user=chaima, value=1, content_type=ct_comment, object_id=str(c2.id))
from django.core.files.base import ContentFile  # noqa: E402
from apps.uploads.models import FileAttachment  # noqa: E402
photo = FileAttachment(content_type=ct_comment, object_id=c1.id, file_name='copie.png', file_size=3, file_type='image',
                       mime_type='image/png', uploaded_by=amina)
photo.file.save('copie.png', ContentFile(b'png'), save=True)
migration = importlib.import_module('apps.discussions.migrations.0002_reprise_commentaires')
migration.reprendre(django_apps, None)
migration.reprendre(django_apps, None)  # rejouée : rien en double
dr = Discussion.objects.get(legacy_comment_id=c1.id)
check('commentaire repris : une discussion, titre = première phrase, contenu tagué', Discussion.objects.count() == 2
      and dr.title == 'Pourquoi la dérivée change de signe ?' and list(dr.contents.values_list('id', flat=True)) == [ex.id]
      and dr.salon == 'entraide' and dr.class_level_id == sm.id, (Discussion.objects.count(), dr.title))
replies = list(dr.replies.order_by('created_at'))
check('réponses reprises dans l\'ordre, « en réponse à » gardé', [r.legacy_comment_id for r in replies] == [c2.id, c3.id]
      and replies[1].reply_to_id == replies[0].id and replies[0].reply_to_id is None and dr.reply_count == 2)
check('dates gardées', abs((dr.created_at - t0).total_seconds()) < 1 and abs((dr.last_activity_at - (t0 + timedelta(hours=2))).total_seconds()) < 1)
ct_reply = ContentType.objects.get_for_model(Reply)
check('« j\'aime » devenu « utile »', Vote.objects.filter(content_type=ct_reply, object_id=str(replies[0].id), user=chaima, value=1).exists())
check('commentaire trop court : titre « À propos de … »', Discussion.objects.get(legacy_comment_id=c4.id).title == 'À propos de « Limites et continuité »')
check('recherche sur une discussion reprise', Discussion.objects.get(legacy_comment_id=c1.id).search_text.startswith('pourquoi la derivee'))
check('les commentaires restent en base', Comment.objects.filter(pk__in=[c1.id, c2.id, c3.id, c4.id]).count() == 4)
ct_disc = ContentType.objects.get_for_model(Discussion)
copie = FileAttachment.objects.filter(content_type=ct_disc, object_id=dr.id).first()
check('pièce jointe copiée (même fichier), le commentaire garde la sienne', copie is not None
      and copie.file.name == photo.file.name and FileAttachment.objects.filter(pk=photo.pk, object_id=c1.id).exists())
r = client(amina).get(f'/api/discussions/{dr.id}/')
check('détail de la discussion reprise : la photo', r.status_code == 200 and len(r.data['files']) == 1, getattr(r, 'data', r))
stockage, nom = photo.file.storage, photo.file.name
client(equipe).delete(f'/api/comments/{c4.id}/')  # un autre commentaire : sans effet sur la photo
copie.delete_file()
check('fichier partagé : pas effacé tant que le commentaire y renvoie', stockage.exists(nom))
photo.delete()
copie.refresh_from_db()
copie.delete_file()
check('dernière pièce jointe : fichier effacé', not stockage.exists(nom))

# Commentaires écrits sur l'ancien site après la reprise : la commande les ajoute, sans doublon.
c5 = Comment.objects.create(content_item=ex, author=chaima, content='<p>Et avec un tableau de signes ?</p>', parent=c3)
Comment.objects.create(content_item=lecon, author=badr, content='<p>Le cours est très clair, merci pour les exemples.</p>')
from io import StringIO  # noqa: E402
out = StringIO()
call_command('reprendre_commentaires', stdout=out)
dr.refresh_from_db()
r5 = Reply.objects.filter(legacy_comment_id=c5.id).first()
check('commande rejouée : nouvelle réponse et nouveau fil ajoutés', Discussion.objects.count() == 3 and r5 is not None
      and r5.reply_to.legacy_comment_id == c3.id and dr.reply_count == 3 and '1 discussion(s) et 1 réponse(s)' in out.getvalue(),
      (Discussion.objects.count(), dr.reply_count, out.getvalue()))
call_command('reprendre_commentaires', stdout=StringIO())
check('commande rejouée une seconde fois : rien en double', Discussion.objects.count() == 3 and Reply.objects.filter(discussion=dr).count() == 3)
# Migration 0003 (jouée au déploiement du site) : même reprise, un commentaire écrit entre-temps la rejoint.
Comment.objects.create(content_item=ex, author=chaima, content='<p>Écrit sur l’ancien site après la reprise.</p>', parent=c1)
importlib.import_module('apps.discussions.migrations.0003_reprise_complement').rattraper(django_apps, None)
dr.refresh_from_db()
check('migration 0003 : le commentaire écrit entre-temps est repris', dr.reply_count == 4 and Discussion.objects.count() == 3,
      (dr.reply_count, Discussion.objects.count()))

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
