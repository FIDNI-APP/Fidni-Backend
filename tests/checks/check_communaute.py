"""Communauté (09/11/2026), sur une base SQLite jetable : profil public (blocs masqués, ville d'un mineur), abonnements
(demandes, acceptation, refus, retrait, blocage, listes privées), badges (premier calcul silencieux, paliers gagnés après
une action, notification, badge gardé), vitrine et réglages, recherche de membres, découvrir, fil, état du défi du
jour, meilleure série, suppression de compte."""
import os
import runpy
import sys
import tempfile
from datetime import date, timedelta
from unittest import mock

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND + '/src')
sys.path.insert(0, BACKEND)
DB = os.path.join(tempfile.gettempdir(), 'fidni-communaute.sqlite3')
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
from django.core.cache import cache  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from apps.caracteristics.models import Chapter, ClassLevel, Subject  # noqa: E402
from apps.classrooms.models import Classroom, ClassroomMembership  # noqa: E402
from apps.communaute import badges as B  # noqa: E402
from apps.communaute.models import Abonnement, BadgeObtenu, Blocage, ProfilPublic  # noqa: E402
from apps.communaute.services import est_mineur  # noqa: E402
from apps.defis import views as defis  # noqa: E402
from apps.defis.models import Defi, TentativeDefi  # noqa: E402
from apps.discussions.models import Discussion, Reply  # noqa: E402
from apps.interactions.models import Complete, Vote  # noqa: E402
from apps.notifications.models import Notification  # noqa: E402
from apps.notifications.views import serialize  # noqa: E402
from apps.skilliq.models import APPROFONDISSEMENT, COURS, SkillAssessment  # noqa: E402
from apps.things.models import Content  # noqa: E402
from apps.users import maitrise  # noqa: E402
from apps.users.account_deletion import DELETED_USERNAME, delete_account, deleted_account_user  # noqa: E402

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


def notifs(u, kind):
    return list(Notification.objects.filter(recipient=u, kind=kind))


cache.clear()
pw = 'Motdepasse-solide-42'
sm = ClassLevel.objects.create(name='2ème Bac SM C', order=980)
pc = ClassLevel.objects.create(name='2ème Bac PC C', order=981)
maths = Subject.objects.create(name='Maths C')
chapitres = [Chapter.objects.create(name=f'Chapitre C{i}', subject=maths) for i in range(4)]
today = date.today()


def membre(nom, naissance=None, level=sm, teacher=False, **kw):
    u = User.objects.create_user(nom, f'{nom}@x.fr', pw, **kw)
    p = u.profile
    p.class_level = level
    p.birth_date = naissance
    if teacher:
        p.user_type = 'teacher'
    p.save()
    return u


equipe = membre('equipe', is_staff=True)
prof = membre('prof', date(1985, 3, 1), teacher=True)
prof.profile.teaching_subjects.add(maths)
prof.profile.teaching_class_levels.add(sm)
adulte = membre('adulte', date(today.year - 19, 1, 1))
mineur = membre('mineur', date(today.year - 16, 1, 1))
inconnu = membre('inconnu')
amina = membre('amina', date(today.year - 19, 6, 1))
badr = membre('badr', date(today.year - 19, 6, 1))
chaima = membre('chaima', date(today.year - 17, 6, 1), level=pc)

print('--- Mineurs')
check('Élève de 16 ans : mineur', est_mineur(mineur))
check('Âge inconnu : traité comme mineur', est_mineur(inconnu))
check('Élève de 19 ans : majeur', not est_mineur(adulte))
check('Professeur et équipe : jamais mineurs', not est_mineur(prof) and not est_mineur(equipe))

print('--- Profil public')
mineur.profile.location = 'Rabat'
mineur.profile.bio = 'Je vise médecine.'
mineur.profile.save()
r = client().get('/api/communaute/profils/mineur/')
check('Profil visible d’un visiteur', r.status_code == 200, r.status_code)
d = r.json()
check('Ville d’un mineur cachée aux autres', d['ville'] is None, d.get('ville'))
check('Pas de réglages pour un visiteur', 'reglages' not in d)
check('Relation : visiteur non connecté', d['relation'] == {'moi': False, 'abonne': None, 'me_suit': False, 'bloque': False,
                                                            'connecte': False}, d['relation'])
d = client(mineur).get('/api/communaute/profils/mineur/').json()
check('Le propriétaire voit sa ville et ses réglages', d['ville'] == 'Rabat' and d['reglages']['abonnes_a_valider'] is True,
      (d.get('ville'), d.get('reglages')))
check('Bannière par défaut choisie d’après le pseudo', d['banniere'] in ('zellige-vert', 'zellige-or', 'nuit', 'sable', 'menthe', 'terre'))
adulte.profile.location = 'Fès'
adulte.profile.save()
check('Ville d’un majeur visible', client().get('/api/communaute/profils/adulte/').json()['ville'] == 'Fès')
check('API /users/ : ville d’un mineur cachée à un visiteur', 'location' not in client().get('/api/users/mineur/').json()['profile'])
check('… et à un autre membre', 'location' not in client(amina).get('/api/users/mineur/').json()['profile'])
check('… mais pas au propriétaire ni à l’équipe', client(mineur).get('/api/users/mineur/').json()['profile'].get('location') == 'Rabat'
      and client(equipe).get('/api/users/mineur/').json()['profile'].get('location') == 'Rabat')
check('API /users/ : ville d’un majeur visible', client().get('/api/users/adulte/').json()['profile'].get('location') == 'Fès')
check('Membre inconnu : 404', client().get('/api/communaute/profils/personne/').status_code == 404)
deleted_account_user()
check('Compte supprimé : pas de profil', client().get(f'/api/communaute/profils/{DELETED_USERNAME}/').status_code == 404)

r = client(mineur).patch('/api/communaute/moi/', {'blocs_masques': ['chiffres', 'activite']}, format='json')
check('Masquer des blocs', r.status_code == 200 and r.json()['blocs_masques'] == ['activite', 'chiffres'], r.content)
d = client(amina).get('/api/communaute/profils/mineur/').json()
check('Blocs masqués : absents pour les autres', d['chiffres'] is None and d['activite'] is None and d['badges'] is not None)
d = client(mineur).get('/api/communaute/profils/mineur/').json()
check('Blocs masqués : toujours là pour le propriétaire', d['chiffres'] is not None and d['activite'] is not None)
check('Bloc inconnu refusé', client(mineur).patch('/api/communaute/moi/', {'blocs_masques': ['notes']}, format='json').status_code == 400)

print('--- Abonnements')
c_amina = client(amina)
r = c_amina.post('/api/communaute/profils/prof/suivre/')
check('Suivre un professeur : accepté tout de suite', r.status_code == 200 and r.json()['abonne'] == 'accepte', r.content)
check('Le professeur est prévenu (« abonne »)', len(notifs(prof, 'abonne')) == 1)
c_amina.post('/api/communaute/profils/prof/suivre/')
check('Suivre deux fois : rien de plus', Abonnement.objects.filter(abonne=amina, suivi=prof).count() == 1
      and notifs(prof, 'abonne')[0].count == 1)
client(badr).post('/api/communaute/profils/prof/suivre/')
n = notifs(prof, 'abonne')
check('Deux abonnés avant lecture : une seule notification (×2)', len(n) == 1 and n[0].count == 2 and n[0].actor_id == badr.id,
      [(x.count, x.actor_id) for x in n])
check('Lien de la notification : la page Membres', serialize(n[0])['url'] == '/membres?onglet=abonnes', serialize(n[0])['url'])

r = c_amina.post('/api/communaute/profils/mineur/suivre/')
check('Suivre un mineur : demande en attente', r.json()['abonne'] == 'en_attente', r.content)
check('Le mineur reçoit une demande', len(notifs(mineur, 'demande')) == 1)
d = client(mineur).get('/api/communaute/demandes/').json()
check('Demandes reçues : amina', [m['username'] for m in d['results']] == ['amina'], d)
check('Une demande en attente ne compte pas comme abonné', client().get('/api/communaute/profils/mineur/').json()['abonnes'] == 0)
r = client(mineur).post('/api/communaute/demandes/amina/accepter/')
check('Accepter la demande', r.status_code == 200 and Abonnement.objects.get(abonne=amina, suivi=mineur).statut == 'accepte')
check('amina est prévenue (« accepte »)', len(notifs(amina, 'accepte')) == 1)
check('Accepter une demande qui n’existe pas : 404', client(mineur).post('/api/communaute/demandes/badr/accepter/').status_code == 404)

client(badr).post('/api/communaute/profils/mineur/suivre/')
check('Réponse inconnue à une demande : 404, la demande reste', client(mineur).post('/api/communaute/demandes/badr/nimporte/').status_code == 404
      and Abonnement.objects.filter(abonne=badr, suivi=mineur, statut='en_attente').exists())
r = client(mineur).post('/api/communaute/demandes/badr/refuser/')
check('Refuser une demande', r.status_code == 200 and not Abonnement.objects.filter(abonne=badr, suivi=mineur).exists())
client(chaima).post('/api/communaute/profils/mineur/suivre/')
client(chaima).delete('/api/communaute/profils/mineur/suivre/')
check('Demande annulée : sa notification disparaît', not Abonnement.objects.filter(abonne=chaima, suivi=mineur).exists()
      and not Notification.objects.filter(recipient=mineur, kind='demande', actor=chaima).exists())

check('Listes d’un mineur : privées pour un non-abonné', client(badr).get('/api/communaute/profils/mineur/abonnes/').status_code == 403)
r = c_amina.get('/api/communaute/profils/mineur/abonnes/')
check('… visibles d’un abonné accepté', r.status_code == 200 and [m['username'] for m in r.json()['results']] == ['amina'], r.content)
r = client().get('/api/communaute/profils/prof/abonnes/')
check('Listes d’un professeur : publiques', r.status_code == 200 and {m['username'] for m in r.json()['results']} == {'amina', 'badr'})
r = client().get('/api/communaute/profils/amina/abonnements/')
check('Abonnements d’amina (majeure) : prof et mineur', {m['username'] for m in r.json()['results']} == {'prof', 'mineur'}, r.content)

check('S’abonner à soi-même : refusé', c_amina.post('/api/communaute/profils/amina/suivre/').status_code == 400)
check('S’abonner sans être connecté : refusé', client().post('/api/communaute/profils/prof/suivre/').status_code in (401, 403))
r = client(prof).delete('/api/communaute/abonnes/badr/')
check('Retirer un abonné', r.status_code == 200 and not Abonnement.objects.filter(abonne=badr, suivi=prof).exists())

print('--- Blocage')
client(adulte).post('/api/communaute/profils/badr/suivre/')
r = client(badr).post('/api/communaute/profils/adulte/bloquer/')
check('Bloquer retire les abonnements entre eux', r.status_code == 200 and not Abonnement.objects.filter(abonne=adulte, suivi=badr).exists())
r = client(adulte).post('/api/communaute/profils/badr/suivre/')
check('Un membre bloqué ne peut plus s’abonner', r.status_code == 403, r.status_code)
check('Ni celui qui bloque', client(badr).post('/api/communaute/profils/adulte/suivre/').status_code == 403)
client(badr).delete('/api/communaute/profils/adulte/bloquer/')
check('Débloquer : de nouveau possible', client(adulte).post('/api/communaute/profils/badr/suivre/').json().get('abonne') == 'accepte')

print('--- Ne plus valider ses abonnés')
client(badr).post('/api/communaute/profils/inconnu/suivre/')
check('Âge inconnu : demande en attente', Abonnement.objects.get(abonne=badr, suivi=inconnu).statut == 'en_attente')
r = client(inconnu).patch('/api/communaute/moi/', {'abonnes_a_valider': False}, format='json')
check('Ne plus valider : les demandes en attente sont acceptées', r.status_code == 200
      and Abonnement.objects.get(abonne=badr, suivi=inconnu).statut == 'accepte' and len(notifs(badr, 'accepte')) == 1)

print('--- Badges : ce qui était déjà gagné avant leur arrivée')
ct = ContentType.objects.get_for_model(Content)
exos = [Content.objects.create(type='exercise', title=f'Exercice {i}', author=equipe, subject=maths, json_content={})
        for i in range(10)]
ancien = membre('ancien', date(2000, 1, 1))
# bulk_create : pas de signal, comme l'activité enregistrée avant la mise en ligne des badges.
Complete.objects.bulk_create([Complete(user=ancien, content_type=ct, object_id=str(c.id), status='success') for c in exos])
client().get('/api/communaute/profils/ancien/')
check('Premier calcul : les badges déjà mérités sont enregistrés', BadgeObtenu.objects.filter(user=ancien, badge='exercices').exists()
      and BadgeObtenu.objects.filter(user=ancien, badge='fondateur').exists())
check('Premier calcul : aucune notification', not notifs(ancien, 'badge'))
check('Premier calcul noté', ProfilPublic.objects.get(user=ancien).badges_init_le is not None)

print('--- Badges : palier gagné après une action')
jours = [today - timedelta(days=2), today - timedelta(days=1), today]
defis_crees = [Defi.objects.create(cle=f'd{i}', date=j, titre='Titre', theme='algebre', difficulte='easy', enonce='x',
                                   consigne='Un entier.', reponse='2', solution='s', valide=True) for i, j in enumerate(jours)]
for dfi in defis_crees:
    TentativeDefi.objects.create(user=amina, defi=dfi, statut='trouve', essais=1, le_jour_meme=True)
check('3e défi trouvé d’affilée : « Série du défi » bronze', BadgeObtenu.objects.filter(user=amina, badge='serie', palier=1).exists())
check('… annoncé par une notification', [n.title for n in notifs(amina, 'badge')] == ['Série du défi · Bronze'],
      [n.title for n in notifs(amina, 'badge')])
check('Membre fondateur (inscrit avant 2027), sans notification', BadgeObtenu.objects.filter(user=amina, badge='fondateur').exists()
      and not Notification.objects.filter(recipient=amina, target__startswith='badge:fondateur').exists())
for c in exos[:9]:
    Complete.objects.create(user=amina, content_type=ct, object_id=str(c.id), status='success')
check('9 exercices réussis : pas encore de badge', not BadgeObtenu.objects.filter(user=amina, badge='exercices').exists())
Complete.objects.create(user=amina, content_type=ct, object_id=str(exos[9].id), status='success')
check('10e exercice réussi : bronze', BadgeObtenu.objects.filter(user=amina, badge='exercices', palier=1).exists())
n = [x for x in notifs(amina, 'badge') if x.target == 'badge:exercices:1']
check('Notification « Exercices réussis · Bronze »', len(n) == 1 and n[0].title == 'Exercices réussis · Bronze'
      and n[0].excerpt == '10 exercices', [(x.title, x.excerpt) for x in notifs(amina, 'badge')])
check('Lien de la notification : les badges du profil', serialize(n[0])['url'] == '/profile/amina#badges', serialize(n[0])['url'])
maitrise.forget(adulte.id)
Complete.objects.create(user=adulte, content_type=ct, object_id=str(exos[0].id), status='success')
check('Badges après une action : le cache de « Ma progression » reste vide', maitrise.en_cache(adulte, sm) is None)
lecon = Content.objects.create(type='lesson', title='Leçon', author=equipe, subject=maths, json_content={})
Complete.objects.create(user=badr, content_type=ct, object_id=str(lecon.id), status='success')
check('Une leçon réussie ne compte pas comme exercice', B.valeurs(badr, ['exercices'])['exercices'] == 0)

disc = Discussion.objects.create(title='Méthode', author=amina, salon='methodes', body='<p>x</p>')
rep = Reply.objects.create(discussion=disc, author=badr, body='<p>merci</p>')
ct_d, ct_r = ContentType.objects.get_for_model(Discussion), ContentType.objects.get_for_model(Reply)
Vote.objects.create(user=amina, value=1, content_type=ct_d, object_id=str(disc.id))
check('Voter « utile » pour soi-même ne compte pas', not BadgeObtenu.objects.filter(user=amina, badge='entraide').exists())
Vote.objects.create(user=badr, value=1, content_type=ct_d, object_id=str(disc.id))
check('« Utile » reçu d’un autre : Entraide bronze', BadgeObtenu.objects.filter(user=amina, badge='entraide', palier=1).exists())
Vote.objects.create(user=amina, value=1, content_type=ct_r, object_id=str(rep.id))
check('… aussi sur une réponse (badr)', BadgeObtenu.objects.filter(user=badr, badge='entraide', palier=1).exists())

for ch in chapitres[:3]:
    SkillAssessment.objects.create(user=amina, chapter=ch, score=9, max_score=10, type=COURS)
check('3 quiz du cours réussis : bronze', BadgeObtenu.objects.filter(user=amina, badge='quiz', palier=1).exists())
SkillAssessment.objects.create(user=amina, chapter=chapitres[3], score=7, max_score=10, type=COURS)
check('Un quiz à 70 % ne compte pas', B.valeurs(amina, ['quiz'])['quiz'] == 3)
SkillAssessment.objects.create(user=amina, chapter=chapitres[0], score=8, max_score=10, type=APPROFONDISSEMENT)
check('Approfondissement à 80 % : Chapitres approfondis bronze', BadgeObtenu.objects.filter(user=amina, badge='approfondi').exists())
Content.objects.create(type='exercise', title='Par le prof', author=prof, subject=maths, json_content={})
check('Première publication : Auteur bronze', BadgeObtenu.objects.filter(user=prof, badge='auteur', palier=1).exists())

Complete.objects.filter(user=amina).delete()
client().get('/api/communaute/profils/amina/')
check('Badge gardé quand le chiffre redescend', BadgeObtenu.objects.filter(user=amina, badge='exercices', palier=1).exists())

maitrise.forget(badr.id)
with mock.patch('apps.users.maitrise.evaluer', side_effect=RuntimeError('panne')):
    r = client(badr).get('/api/communaute/profils/badr/')
    check('« Ma progression » en panne : le profil s’affiche quand même', r.status_code == 200, r.status_code)
    d = r.json()
    check('… sans chapitres ni chiffre de maîtrise : inconnus, pas zéro', d['chapitres'] is None
          and all(c['id'] != 'maitrise' for c in d['chiffres'])
          and 'valeur' not in next(b for b in d['badges'] if b['id'] == 'maitrise'), (d['chapitres'], d['chiffres']))
check('Unité au singulier pour 1 : « 1 publication », « 10 publications »',
      B.texte_seuil('auteur', 1) == '1 publication' and B.texte_seuil('auteur', 10) == '10 publications'
      and B.texte_seuil('entraide', 1) == '1 « utile » reçu' and B.texte_seuil('fondateur', 1) == '')

print('--- Catalogue, vitrine, réglages')
d = client(badr).get('/api/communaute/profils/amina/').json()
ids = {b['id'] for b in d['badges']}
check('Visiteur : seulement les badges obtenus', all(b['palier'] >= 1 for b in d['badges']) and 'maitrise' not in ids, ids)
check('Visiteur : pas de chiffre de progression', all('valeur' not in b for b in d['badges']))
d = client(amina).get('/api/communaute/profils/amina/').json()
par = {b['id']: b for b in d['badges']}
check('Propriétaire : aussi les badges à gagner, avec son chiffre', par['maitrise']['palier'] == 0 and 'valeur' in par['maitrise']
      and par['serie']['valeur'] == 3, par.get('serie'))
check('Propriétaire élève : pas le badge « Auteur » à gagner', 'auteur' not in par)
check('Obtenus d’abord', [b['palier'] > 0 for b in d['badges']] == sorted([b['palier'] > 0 for b in d['badges']], reverse=True))
c_am = client(amina)
r = c_am.patch('/api/communaute/moi/', {'vitrine': ['entraide', 'serie']}, format='json')
check('Vitrine de badges obtenus', r.status_code == 200 and r.json()['vitrine'] == ['entraide', 'serie'], r.content)
d = client().get('/api/communaute/profils/amina/').json()
check('Vitrine dans l’ordre choisi', [b['id'] for b in d['vitrine']] == ['entraide', 'serie'], d['vitrine'])
check('Vitrine : un badge pas obtenu refusé', c_am.patch('/api/communaute/moi/', {'vitrine': ['maitrise']}, format='json').status_code == 400)
check('Vitrine : 3 au plus', c_am.patch('/api/communaute/moi/', {'vitrine': ['entraide', 'serie', 'quiz', 'exercices']},
                                        format='json').status_code == 400)
check('Objectif enregistré', c_am.patch('/api/communaute/moi/', {'objectif': '  Médecine   à Rabat '}, format='json').json()['objectif']
      == 'Médecine à Rabat')
for texte in ['Appelle-moi 06 12 34 56 78', 'insta.com/amina', 'www.exemple.ma', 'x' * 61]:
    check(f'Objectif refusé : {texte[:20]!r}', c_am.patch('/api/communaute/moi/', {'objectif': texte}, format='json').status_code == 400)
check('Bannière inconnue refusée', c_am.patch('/api/communaute/moi/', {'banniere': 'rose'}, format='json').status_code == 400)
check('Bannière choisie', c_am.patch('/api/communaute/moi/', {'banniere': 'nuit'}, format='json').json()['banniere'] == 'nuit')
check('Réglage booléen mal formé refusé', c_am.patch('/api/communaute/moi/', {'visible_recherche': 'non'}, format='json').status_code == 400)

print('--- Recherche de membres')
check('Recherche réservée aux membres connectés', client().get('/api/communaute/membres/').status_code in (401, 403))
r = client(badr).get('/api/communaute/membres/?q=ami').json()
check('Recherche par pseudo', [m['username'] for m in r['results']] == ['amina'], r)
carte = r['results'][0]
check('Carte : objectif, bannière, vitrine d’abord puis les plus hauts paliers', carte['objectif'] == 'Médecine à Rabat'
      and carte['banniere'] == 'nuit' and [b['id'] for b in carte['badges']][:2] == ['entraide', 'serie']
      and len(carte['badges']) == 3, carte)
c_am.patch('/api/communaute/moi/', {'visible_recherche': False}, format='json')
check('Cachée de la recherche : introuvable', client(badr).get('/api/communaute/membres/?q=ami').json()['results'] == [])
c_am.patch('/api/communaute/moi/', {'visible_recherche': True}, format='json')
r = client(badr).get('/api/communaute/membres/?role=prof').json()
check('Filtre Professeurs', [m['username'] for m in r['results']] == ['prof'], r)
r = client(badr).get(f'/api/communaute/membres/?role=eleve&niveau={pc.id}').json()
check('Filtre niveau', [m['username'] for m in r['results']] == ['chaima'], r)
chaima.profile.last_activity_date = timezone.now() + timedelta(hours=1)
chaima.profile.save()
r = client(badr).get('/api/communaute/membres/?role=eleve').json()
check('Sans recherche : le plus récemment actif d’abord, ceux sans activité connue à la fin (PostgreSQL aussi)',
      r['results'][0]['username'] == 'chaima', [m['username'] for m in r['results']])
check('L’équipe n’est ni élève ni professeur', 'equipe' not in [m['username'] for m in client(badr).get(
    '/api/communaute/membres/?role=eleve').json()['results']])
Blocage.objects.create(auteur=chaima, bloque=badr)
check('Un membre qui m’a bloqué n’apparaît pas', client(badr).get('/api/communaute/membres/?q=chaima').json()['results'] == [])
Blocage.objects.filter(auteur=chaima).delete()

print('--- Découvrir')
classe = Classroom.objects.create(name='TS1', owner=prof, class_level=sm)
ClassroomMembership.objects.create(classroom=classe, student=badr)
ClassroomMembership.objects.create(classroom=classe, student=adulte)
ProfilPublic.objects.filter(user=prof).update(verifie=True)
membre('prof2', date(1980, 1, 1), teacher=True)  # sans réglages enregistrés (NULL) ni activité : après le professeur vérifié
d = client(badr).get('/api/communaute/decouvrir/').json()
check('Ta classe : camarades et professeur', {m['username'] for m in d['classe']} == {'prof', 'adulte'}, d['classe'])
check('Professeurs : le professeur vérifié', d['profs'] and d['profs'][0]['username'] == 'prof' and d['profs'][0]['verifie'])
check('Élèves de ton niveau, sans ceux de ta classe', 'adulte' not in {m['username'] for m in d['niveau']}
      and 'amina' in {m['username'] for m in d['niveau']}, d['niveau'])
check('Les plus utiles (30 jours)', [(x['membre']['username'], x['n']) for x in d['utiles']][:2] == [('amina', 1), ('badr', 1)],
      d['utiles'])
check('Meilleures séries en cours', [(x['membre']['username'], x['n']) for x in d['series']] == [('amina', 3)], d['series'])

print('--- Fil des abonnements')
r = client(adulte).get('/api/communaute/fil/').json()
check('Fil : ce que fait badr (suivi)', any(x['type'] == 'badge' and x['membre']['username'] == 'badr' for x in r['results']),
      r['results'])
check('Fil : rien de ceux qu’on ne suit pas', all(x['membre']['username'] == 'badr' for x in r['results']))
r = client(amina).get('/api/communaute/fil/').json()
types = {(x['type'], x['membre']['username']) for x in r['results']}
check('Fil : publication et badges du professeur suivi', ('publication', 'prof') in types and ('badge', 'prof') in types, types)
client(chaima).post('/api/communaute/profils/mineur/suivre/')
check('Demande en attente : rien dans le fil', client(chaima).get('/api/communaute/fil/').json()['results'] == [])
for curseur in ('2026-13-45T00:00:00', 'nimporte', '2026-11-09T10:00:00'):
    check(f'Fil : curseur {curseur!r} sans erreur', client(amina).get('/api/communaute/fil/', {'avant': curseur}).status_code == 200)

print('--- État du défi du jour')
r = client().get('/api/defis/etat/').json()
check('Visiteur : le jour du défi, sans état', r == {'date': today.isoformat(), 'statut': None, 'serie': None}, r)
check('Membre qui ne l’a pas ouvert : en cours', client(badr).get('/api/defis/etat/').json()['statut'] == 'en_cours')
r = client(amina).get('/api/defis/etat/').json()
check('Membre qui l’a trouvé : trouvé, série 3', r['statut'] == 'trouve' and r['serie'] == 3, r)
Defi.objects.filter(date=today).update(valide=False)
check('Pas de défi aujourd’hui : rien', client(amina).get('/api/defis/etat/').json()['date'] is None)
Defi.objects.filter(date=today).update(valide=True)

print('--- Meilleure série')
u = membre('serieux', date(2000, 1, 1))
plus_tot = [today - timedelta(days=i) for i in range(10, 3, -1)]
for i, j in enumerate(plus_tot):
    Defi.objects.create(cle=f'old{i}', date=j, titre='T', theme='algebre', difficulte='easy', enonce='x', consigne='c',
                        reponse='2', solution='s', valide=True)
for j in plus_tot[:4] + plus_tot[5:]:
    TentativeDefi.objects.create(user=u, defi=Defi.objects.get(date=j), statut='trouve', le_jour_meme=True)
check('Meilleure série : 4 (un défi manqué casse la série)', defis.meilleure_serie(u) == 4, defis.meilleure_serie(u))
Defi.objects.filter(date=plus_tot[4]).update(valide=False)
check('Un jour sans défi publié ne casse rien : 6', defis.meilleure_serie(u) == 6, defis.meilleure_serie(u))

print('--- Suppression de compte')
delete_account(badr, keep_contributions=True)
check('Compte supprimé : ses abonnements et badges partent avec lui', not Abonnement.objects.filter(abonne_id=badr.id).exists()
      and not BadgeObtenu.objects.filter(user_id=badr.id).exists())

print(f'\n{sum(results)}/{len(results)} vérifications réussies')
sys.exit(0 if all(results) else 1)
