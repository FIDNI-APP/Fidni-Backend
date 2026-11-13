"""Actions de la messagerie, communes aux vues (REST) et au WebSocket (consumers.py). Synchrones."""
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import regles
from .models import MEMBRES_MAX, TEXTE_MAX, TITRE_MAX, Appel, Conversation, Message, Participant, PresenceAppel
from .temps_reel import envoyer


class Refus(Exception):
    def __init__(self, message, code, status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _ids_actifs(conversation):
    return list(Participant.objects.filter(conversation=conversation, parti_le__isnull=True)
                .values_list('user_id', flat=True))


def message_dict(m):
    supprime = m.supprime_le is not None
    return {
        'id': m.id, 'conversation': m.conversation_id, 'auteur': m.auteur_id, 'type': m.type,
        'texte': '' if supprime else m.texte, 'donnees': {} if supprime else m.donnees,
        'created_at': m.created_at.isoformat(), 'supprime': supprime,
    }


# ── Conversations ─────────────────────────────────────────────────────────────────────────────────────────────────

def directe(a, b):
    """La conversation directe entre a et b (créée au besoin). Refusée s'ils ne sont pas abonnés mutuels."""
    if not regles.peut_ecrire(a, b):
        raise Refus('Vous devez vous suivre tous les deux pour vous écrire.', 'pas-mutuels', 403)
    cle = f'{min(a.id, b.id)}:{max(a.id, b.id)}'
    conv = Conversation.objects.filter(cle_directe=cle).first()
    if conv is None:
        try:
            with transaction.atomic():
                conv = Conversation.objects.create(type=Conversation.DIRECTE, cle_directe=cle, createur=a)
                Participant.objects.bulk_create([Participant(conversation=conv, user=u) for u in (a, b)])
        except IntegrityError:
            conv = Conversation.objects.get(cle_directe=cle)
    return conv


def _verifier_ajouts(par, nouveaux, deja_ids):
    for u in nouveaux:
        if not regles.peut_ecrire(par, u):
            raise Refus(f'Tu ne peux inviter que des membres que tu suis et qui te suivent ({u.username}).',
                        'pas-mutuels', 403)
        autres = [i for i in deja_ids if i != u.id]
        if autres and regles.bloque_entre(u, autres):
            raise Refus(f'{u.username} ne peut pas rejoindre ce groupe.', 'bloque', 403)


def creer_groupe(createur, membres, titre='', contenu=None):
    membres = [u for u in {u.id: u for u in membres}.values() if u.id != createur.id]
    if not membres:
        raise Refus('Choisis au moins une personne.', 'vide')
    if len(membres) + 1 > MEMBRES_MAX:
        raise Refus(f'{MEMBRES_MAX} personnes au plus dans un groupe.', 'trop')
    _verifier_ajouts(createur, membres, [createur.id] + [u.id for u in membres])
    with transaction.atomic():
        conv = Conversation.objects.create(type=Conversation.GROUPE, titre=(titre or '').strip()[:TITRE_MAX],
                                           createur=createur, contenu=contenu)
        Participant.objects.bulk_create([Participant(conversation=conv, user=u, lu_jusqu_a=timezone.now()
                                                     if u.id == createur.id else None)
                                         for u in [createur] + membres])
    envoyer([u.id for u in membres], {'type': 'conversation.maj', 'conversation': conv.id})
    return conv


def ajouter(conversation, par, membres):
    if conversation.type != Conversation.GROUPE:
        raise Refus('On ne peut ajouter quelqu’un qu’à un groupe.', 'directe')
    deja = _ids_actifs(conversation)
    nouveaux = [u for u in membres if u.id not in deja]
    if not nouveaux:
        return []
    if len(deja) + len(nouveaux) > MEMBRES_MAX:
        raise Refus(f'{MEMBRES_MAX} personnes au plus dans un groupe.', 'trop')
    _verifier_ajouts(par, nouveaux, deja + [u.id for u in nouveaux])
    now = timezone.now()
    for u in nouveaux:
        Participant.objects.update_or_create(conversation=conversation, user=u,
                                             defaults={'parti_le': None, 'rejoint_le': now, 'lu_jusqu_a': None})
    for u in nouveaux:
        systeme(conversation, par, 'ajout', {'membre': u.username})
    envoyer([u.id for u in nouveaux], {'type': 'conversation.maj', 'conversation': conversation.id})
    return nouveaux


def envoyer_maj(conversation):
    envoyer(_ids_actifs(conversation), {'type': 'conversation.maj', 'conversation': conversation.id})


def quitter(conversation, user):
    if conversation.type != Conversation.GROUPE:
        raise Refus('On ne quitte pas une conversation à deux.', 'directe')
    n = Participant.objects.filter(conversation=conversation, user=user, parti_le__isnull=True).update(
        parti_le=timezone.now())
    if n:
        systeme(conversation, user, 'depart', {'membre': user.username})
        envoyer([user.id], {'type': 'conversation.maj', 'conversation': conversation.id})
    return bool(n)


# ── Messages ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _publier(conversation, m):
    Conversation.objects.filter(pk=conversation.pk).update(dernier_message_at=m.created_at)
    envoyer(_ids_actifs(conversation), {'type': 'message.nouveau', 'message': message_dict(m)})
    return m


def ecrire(conversation, auteur, texte, type=Message.TEXTE, donnees=None):
    texte = (texte or '').strip()
    if type == Message.TEXTE and not texte:
        raise Refus('Message vide.', 'vide')
    if len(texte) > TEXTE_MAX:
        raise Refus(f'{TEXTE_MAX} caractères au plus.', 'trop-long')
    if not regles.peut_parler(auteur, conversation):
        raise Refus(regles.raison_lecture_seule(auteur, conversation) or 'Conversation fermée.', 'lecture-seule', 403)
    m = Message.objects.create(conversation=conversation, auteur=auteur, type=type, texte=texte, donnees=donnees or {})
    Participant.objects.filter(conversation=conversation, user=auteur).update(lu_jusqu_a=m.created_at)
    return _publier(conversation, m)


def systeme(conversation, acteur, code, donnees=None):
    m = Message.objects.create(conversation=conversation, auteur=acteur, type=Message.SYSTEME, texte='',
                               donnees={'code': code, **(donnees or {})})
    return _publier(conversation, m)


def supprimer(message, user):
    if message.auteur_id != user.id or message.type != Message.TEXTE:
        raise Refus('Tu ne peux supprimer que tes messages.', 'interdit', 403)
    if message.supprime_le is None:
        message.supprime_le = timezone.now()
        message.save(update_fields=['supprime_le'])
        envoyer(_ids_actifs(message.conversation), {'type': 'message.maj', 'message': message_dict(message)})
    return message


def marquer_lu(conversation, user):
    now = timezone.now()
    Participant.objects.filter(conversation=conversation, user=user).update(lu_jusqu_a=now)
    envoyer(_ids_actifs(conversation), {'type': 'lu', 'conversation': conversation.id, 'user': user.id,
                                        'quand': now.isoformat()})


def non_lus(user):
    """Nombre de conversations avec au moins un message non lu (d'un autre membre)."""
    return participations(user).filter(Exists(_recents(user))).count()


EPOQUE = datetime(2000, 1, 1, tzinfo=dt_timezone.utc)


def participations(user):
    return (Participant.objects.filter(user=user, parti_le__isnull=True)
            .annotate(lu_ref=Coalesce('lu_jusqu_a', Value(EPOQUE))))


def _recents(user):
    """Messages d'autres membres arrivés après la lecture (sous-requête sur une participation annotée de lu_ref)."""
    return (Message.objects.filter(conversation_id=OuterRef('conversation_id'), created_at__gt=OuterRef('lu_ref'))
            .exclude(auteur_id=user.id))


def compte_non_lus(user):
    """Par conversation : nombre de messages non lus (99 au plus)."""
    sous = (_recents(user).order_by().values('conversation_id').annotate(n=Count('id')).values('n')[:1])
    return {p.conversation_id: min(p.n or 0, 99)
            for p in participations(user).annotate(n=Subquery(sous))}


# ── Appels ────────────────────────────────────────────────────────────────────────────────────────────────────────
# L'audio et la vidéo vont d'un navigateur à l'autre (WebRTC, maillage) ; le serveur ne relaie que la mise en relation
# (offres, réponses, candidats ICE) entre les présences d'un même appel, et le TURN (coturn) relaie les flux chiffrés
# quand le pair-à-pair est impossible. Rien n'est enregistré.

def appel_en_cours(conversation):
    return Appel.objects.filter(conversation=conversation, fin__isnull=True).first()


def etat_appel(conversation):
    appel = appel_en_cours(conversation)
    if appel is None:
        return None
    presences = list(appel.presences.filter(parti_le__isnull=True).order_by('rejoint_le'))
    return {'id': appel.id, 'conversation': conversation.id, 'video': appel.video, 'debut': appel.debut.isoformat(),
            'lance_par': appel.lance_par_id,
            'presences': [{'id': p.id, 'user': p.user_id} for p in presences]}


def _diffuser_appel(conversation):
    envoyer(_ids_actifs(conversation), {'type': 'appel.maj', 'conversation': conversation.id,
                                        'appel': etat_appel(conversation)})


def rejoindre_appel(conversation, user, canal, video=False):
    """Entre dans l'appel de la conversation (le lance s'il n'y en a pas). → (présence, appel, présences des autres)."""
    if not regles.peut_parler(user, conversation):
        raise Refus(regles.raison_lecture_seule(user, conversation) or 'Appel impossible.', 'lecture-seule', 403)
    with transaction.atomic():
        Conversation.objects.select_for_update().filter(pk=conversation.pk).first()
        appel = appel_en_cours(conversation)
        if appel is None:
            appel = Appel.objects.create(conversation=conversation, lance_par=user, video=bool(video))
        actives = appel.presences.filter(parti_le__isnull=True)
        if actives.exclude(canal=canal).count() >= MEMBRES_MAX:
            raise Refus(f'{MEMBRES_MAX} personnes au plus dans un appel.', 'complet')
        presence = actives.filter(canal=canal).first() or PresenceAppel.objects.create(appel=appel, user=user, canal=canal)
        autres = list(appel.presences.filter(parti_le__isnull=True).exclude(pk=presence.pk))
    _diffuser_appel(conversation)
    return presence, appel, autres


def quitter_appel(canal, appel_id=None):
    """Retire les présences de ce canal (d'un appel précis, ou de tous à la déconnexion) ; termine les appels vides."""
    qs = PresenceAppel.objects.filter(canal=canal, parti_le__isnull=True).select_related('appel__conversation')
    if appel_id is not None:
        qs = qs.filter(appel_id=appel_id)
    convs = {}
    now = timezone.now()
    for p in qs:
        p.parti_le = now
        p.save(update_fields=['parti_le'])
        convs[p.appel_id] = p.appel
    for appel in convs.values():
        _terminer_si_vide(appel)
        _diffuser_appel(appel.conversation)
    return list(convs.values())


def _terminer_si_vide(appel):
    if appel.presences.filter(parti_le__isnull=True).exists():
        return
    with transaction.atomic():
        n = Appel.objects.filter(pk=appel.pk, fin__isnull=True).update(fin=timezone.now())
    if not n:
        return
    appel.refresh_from_db()
    rejoints = set(appel.presences.values_list('user_id', flat=True))
    duree = int((appel.fin - appel.debut).total_seconds())
    m = Message.objects.create(conversation=appel.conversation, auteur=appel.lance_par, type=Message.APPEL, texte='',
                               donnees={'video': appel.video, 'duree': duree, 'personnes': len(rejoints),
                                        'manque': len(rejoints) <= 1})
    _publier(appel.conversation, m)


def presence_dans_appel(presence_id, appel_id):
    return PresenceAppel.objects.filter(pk=presence_id, appel_id=appel_id, parti_le__isnull=True).first()


def membres_par_noms(noms):
    noms = [str(n).strip() for n in (noms or []) if str(n).strip()][:MEMBRES_MAX]
    users = list(User.objects.filter(username__in=noms))
    if len(users) != len(set(noms)):
        raise Refus('Membre introuvable.', 'introuvable', 404)
    return users
