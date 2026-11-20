"""Adresses e-mail jetables (temporaires) interdites (20/11/2026, Natsu : « strictement interdit d'utiliser des
adresses temporaires »).

Liste locale actualisée par le serveur. Pour les domaines inconnus à l'inscription ou au changement d'adresse,
Check-Mail peut compléter la liste. Le rapport sur les comptes existants utilise uniquement la liste locale.
"""
import json
import logging
import os
import re
from contextlib import closing
from functools import lru_cache
from hashlib import sha256
from http.client import HTTPException, HTTPSConnection
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

FICHIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'adresses_jetables.txt')
SOURCE = ('https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/'
          'disposable_email_blocklist.conf')
# Liste standard : les variantes « strict » incluent des fournisseurs légitimes.
SOURCE_QUOTIDIENNE = 'https://disposable.github.io/disposable-email-domains/domains.txt'
NOM_DOMAINE = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$')

EN_PLUS = {'bonuscable.com'}
AUTORISES = {
    'gmail.com', 'googlemail.com', 'hotmail.com', 'hotmail.fr', 'outlook.com', 'outlook.fr', 'live.com', 'live.fr',
    'msn.com', 'yahoo.com', 'yahoo.fr', 'ymail.com', 'icloud.com', 'me.com', 'mac.com', 'protonmail.com',
    'proton.me', 'gmx.com', 'gmx.fr', 'orange.fr', 'free.fr', 'laposte.net', 'menara.ma', 'taalim.ma',
}

MESSAGE = ('Les adresses e-mail temporaires ne sont pas acceptées. '
           'Utilise ton adresse habituelle (Gmail, Outlook…).')


def fichier_liste():
    return Path(os.environ.get('FIDNI_JETABLES_FICHIER') or FICHIER)


@lru_cache(maxsize=1)
def _lire_domaines(chemin, inode, mtime_ns):
    # L'identité du fichier invalide aussi le cache des autres processus après le remplacement atomique.
    with chemin.open(encoding='utf-8') as fh:
        return frozenset(ligne.strip() for ligne in fh if ligne.strip() and not ligne.startswith('#'))


def domaines():
    chemin = fichier_liste()
    try:
        stat = chemin.stat()
        return _lire_domaines(chemin, stat.st_ino, stat.st_mtime_ns)
    except OSError:
        # Premier téléchargement en cours ou volume temporairement inaccessible.
        chemin = Path(FICHIER)
        stat = chemin.stat()
        return _lire_domaines(chemin, stat.st_ino, stat.st_mtime_ns)


def _check_mail(domaine):
    cle = 'check-mail:v2:' + sha256(domaine.encode('ascii')).hexdigest()
    verdict = cache.get(cle)
    if verdict is not None:
        return verdict
    pause = 'check-mail:indisponible'
    if cache.get(pause):
        return False
    try:
        with closing(HTTPSConnection('api.check-mail.org', timeout=2)) as connexion:
            connexion.request('POST', '/v2/', body=urlencode({'domain': domaine}), headers={
                'Authorization': 'Bearer ' + settings.CHECK_MAIL_API_KEY,
                'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json',
            })
            reponse = connexion.getresponse()
            if reponse.status != 200:
                cache.set(pause, True, 900 if reponse.status in (401, 403, 429) else 60)
                logger.warning('Check-Mail HTTP %s, utilisation de la liste locale.', reponse.status)
                return False
            donnees = json.loads(reponse.read(65536))
    except (OSError, HTTPException, ValueError, RecursionError):
        cache.set(pause, True, 60)
        logger.warning('Check-Mail indisponible, utilisation de la liste locale.')
        return False
    if not isinstance(donnees, dict) or donnees.get('domain') != domaine:
        return False
    verdict = donnees.get('is_disposable')
    if type(verdict) is not bool:
        return False
    cache.set(cle, verdict, 86400 if verdict else 21600)
    return verdict


def domaine_jetable(domaine, *, consulter_api=False):
    """« yopmail.com » ou « x.yopmail.com » → True."""
    d = (domaine or '').strip().lower().rstrip('.')
    try:
        d = d.encode('idna').decode('ascii')
    except UnicodeError:
        return False
    if not NOM_DOMAINE.fullmatch(d):
        return False
    morceaux = d.split('.')
    suffixes = {'.'.join(morceaux[i:]) for i in range(len(morceaux) - 1)}
    if not AUTORISES.isdisjoint(suffixes):
        return False
    if not EN_PLUS.isdisjoint(suffixes) or not domaines().isdisjoint(suffixes):
        return True
    return bool(consulter_api and settings.CHECK_MAIL_API_KEY and _check_mail(d))


def adresse_jetable(email, *, consulter_api=False):
    """True si l'adresse est sur un domaine jetable."""
    _, arobase, domaine = str(email or '').rpartition('@')
    return bool(arobase) and domaine_jetable(domaine, consulter_api=consulter_api)
