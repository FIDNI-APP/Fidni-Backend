"""Bannir un compte (modération, 11/10/2026) : empêcher la même personne de recréer un compte.

On garde, dans `Bannissement` :
- son adresse e-mail, normalisée (Gmail : sans les points ni « +suite », qui mènent à la même boîte), à vie ;
- l'identifiant (`sub`) de son compte Google, à vie ;
- ses adresses IP, 30 jours seulement : au Maroc une IP mobile est souvent partagée par beaucoup d'abonnés
  et elle change ; en IPv6, c'est le préfixe /64 qui est banni (l'adresse change à l'intérieur).
Seule la CRÉATION d'un compte est bloquée (inscription, nouveau compte Google) : un membre déjà inscrit
qui partage l'IP navigue et se connecte normalement. Une autre adresse e-mail reste toujours possible.

Les IP d'un compte viennent du profil (`signup_ip`, `last_ip` et `recent_ips`, les IP distinctes des 30 derniers
jours, remplies par `remember_ip` à l'inscription, à la connexion et au renouvellement de session) et des
journaux (`APILog`) des 30 derniers jours.
"""
import ipaddress
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.users.models import Bannissement, GoogleAccount

IP_BAN_DAYS = 30
RECENT_IPS_MAX = 10
GMAIL_DOMAINS = {'gmail.com', 'googlemail.com'}
BANNED_MESSAGE = 'Impossible de créer un compte. Si c’est une erreur, écris à contact@fidni.fr.'


def normalize_email(email):
    """« Amine.B+fidni@GoogleMail.com » → « amineb@gmail.com » ; ailleurs, seulement minuscules et sans « +suite »."""
    email = (email or '').strip().lower()
    if '@' not in email:
        return email
    local, domain = email.rsplit('@', 1)
    local = local.split('+', 1)[0]
    if domain in GMAIL_DOMAINS:
        return f"{local.replace('.', '')}@gmail.com"
    return f'{local}@{domain}'


def ip_key(ip):
    """IP comparable : IPv4 telle quelle, IPv6 ramenée à son préfixe /64 (« 2a01:e0a:1:2::/64 »). None si invalide."""
    try:
        addr = ipaddress.ip_address((ip or '').strip())
    except ValueError:
        return None
    if addr.version == 6:
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f'{addr}/64', strict=False))
    return str(addr)


def client_ip(request):
    from apps.logging.middleware import get_client_ip
    return get_client_ip(request)


def remember_ip(user, request, *, signup=False):
    """Retient l'IP d'inscription ou de connexion du compte (pour pouvoir la bannir). Ne lève jamais."""
    try:
        ip = client_ip(request)
        if not ip or ip_key(ip) is None:
            return
        from apps.users.models import UserProfile
        profile = UserProfile.objects.filter(user=user).only('id', 'recent_ips').first()
        if profile is None:
            return
        now = timezone.now()
        since = (now - timedelta(days=IP_BAN_DAYS)).isoformat()
        recent = [e for e in (profile.recent_ips or []) if isinstance(e, dict) and e.get('ip') != ip
                  and str(e.get('at', '')) >= since]
        recent = ([{'ip': ip, 'at': now.isoformat()}] + recent)[:RECENT_IPS_MAX]
        fields = {'last_ip': ip, 'last_ip_at': now, 'recent_ips': recent}
        if signup:
            fields['signup_ip'] = ip
        UserProfile.objects.filter(pk=profile.pk).update(**fields)
    except Exception:  # noqa: BLE001 — retenir l'IP ne doit jamais empêcher une connexion
        pass


def active_bans():
    return Bannissement.objects.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))


def ban_reason(*, email=None, google_sub=None, ip=None):
    """Type du bannissement qui bloque cette création de compte (« email », « google », « ip »), sinon None."""
    tests = []
    if email:
        tests.append(Q(kind=Bannissement.KIND_EMAIL, value=normalize_email(email)))
    if google_sub:
        tests.append(Q(kind=Bannissement.KIND_GOOGLE, value=str(google_sub)))
    key = ip_key(ip) if ip else None
    if key:
        tests.append(Q(kind=Bannissement.KIND_IP, value=key))
    if not tests:
        return None
    query = tests[0]
    for t in tests[1:]:
        query |= t
    found = active_bans().filter(query).values_list('kind', flat=True).first()
    return found


def add_ban(kind, value, *, username='', motif='', by=None):
    """Ajoute (ou prolonge) un bannissement. Valeur normalisée ; IP pour IP_BAN_DAYS jours. Renvoie l'objet ou None."""
    if kind == Bannissement.KIND_EMAIL:
        value = normalize_email(value)
        if '@' not in value:
            return None
        expires = None
    elif kind == Bannissement.KIND_IP:
        value = ip_key(value)
        if value is None:
            return None
        expires = timezone.now() + timedelta(days=IP_BAN_DAYS)
    elif kind == Bannissement.KIND_GOOGLE:
        value = str(value or '').strip()
        if not value:
            return None
        expires = None
    else:
        return None
    ban, _ = Bannissement.objects.update_or_create(
        kind=kind, value=value,
        defaults={'username': username[:150], 'motif': motif[:300], 'created_by': by, 'expires_at': expires})
    return ban


def user_ips(user, days=IP_BAN_DAYS):
    """IP connues d'un compte : profil (inscription, dernière connexion) et journaux récents."""
    from apps.logging.models import APILog
    ips = set()
    profile = getattr(user, 'profile', None)
    if profile is not None:
        ips.update(ip for ip in (profile.signup_ip, profile.last_ip) if ip)
        ips.update(e.get('ip') for e in (profile.recent_ips or []) if isinstance(e, dict) and e.get('ip'))
    since = timezone.now() - timedelta(days=days)
    ips.update(ip for ip in APILog.objects.filter(user=user, timestamp__gte=since)
               .values_list('ip_address', flat=True).distinct() if ip)
    return ips


def ban_user(user, *, by=None, motif=''):
    """Bannit un compte avant sa suppression : adresse, comptes Google, IP. Renvoie {type: [valeurs]}."""
    done = {'email': [], 'google': [], 'ip': []}
    name = user.username
    if user.email:
        ban = add_ban(Bannissement.KIND_EMAIL, user.email, username=name, motif=motif, by=by)
        if ban:
            done['email'].append(ban.value)
    for sub, email in GoogleAccount.objects.filter(user=user).values_list('sub', 'email'):
        ban = add_ban(Bannissement.KIND_GOOGLE, sub, username=name, motif=motif, by=by)
        if ban:
            done['google'].append(email or ban.value)
        if email and normalize_email(email) != normalize_email(user.email or ''):
            ban = add_ban(Bannissement.KIND_EMAIL, email, username=name, motif=motif, by=by)
            if ban:
                done['email'].append(ban.value)
    for ip in sorted(user_ips(user)):
        ban = add_ban(Bannissement.KIND_IP, ip, username=name, motif=motif, by=by)
        if ban and ban.value not in done['ip']:
            done['ip'].append(ban.value)
    return done


def purge_expired():
    """Bannissements d'IP expirés : supprimés (appelé par legal.purge_old_logs). Renvoie le nombre supprimé."""
    return Bannissement.objects.filter(expires_at__lt=timezone.now()).delete()[0]
