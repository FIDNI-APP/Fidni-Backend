"""Adresses e-mail jetables (temporaires) interdites (20/11/2026, Natsu : « strictement interdit d'utiliser des
adresses temporaires »).

Refusées à l'inscription (`RegisterView`) et au changement d'adresse (`PATCH /api/users/me/`). La connexion Google
n'est pas concernée : un compte Google est une vraie adresse.

Liste : `data/adresses_jetables.txt`, copie de la liste communautaire disposable-email-domains (licence CC0,
https://github.com/disposable-email-domains/disposable-email-domains, fichier disposable_email_blocklist.conf), un
domaine par ligne. Un sous-domaine d'un domaine de la liste est refusé aussi (« x.yopmail.com »). `EN_PLUS` : domaines
vus sur Fidni et absents de la liste ; `AUTORISES` : vrais fournisseurs, jamais refusés quoi qu'il arrive.
Mettre la liste à jour : `python manage.py adresses_jetables --mettre-a-jour` (télécharge la dernière version).
Comptes existants avec une adresse jetable : `python manage.py adresses_jetables` (lecture seule).
"""
import os
from functools import lru_cache

FICHIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'adresses_jetables.txt')
SOURCE = ('https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/'
          'disposable_email_blocklist.conf')

EN_PLUS = set()
AUTORISES = {
    'gmail.com', 'googlemail.com', 'hotmail.com', 'hotmail.fr', 'outlook.com', 'outlook.fr', 'live.com', 'live.fr',
    'msn.com', 'yahoo.com', 'yahoo.fr', 'ymail.com', 'icloud.com', 'me.com', 'mac.com', 'protonmail.com',
    'proton.me', 'gmx.com', 'gmx.fr', 'orange.fr', 'free.fr', 'laposte.net', 'menara.ma', 'taalim.ma',
}

MESSAGE = ('Les adresses e-mail temporaires ne sont pas acceptées. '
           'Utilise ton adresse habituelle (Gmail, Outlook…).')


@lru_cache(maxsize=1)
def domaines():
    try:
        with open(FICHIER, encoding='utf-8') as fh:
            lus = {ligne.strip().lower() for ligne in fh if ligne.strip() and not ligne.startswith('#')}
    except OSError:
        lus = set()
    return frozenset((lus | EN_PLUS) - AUTORISES)


def domaine_jetable(domaine):
    """« yopmail.com » ou « x.yopmail.com » → True."""
    d = (domaine or '').strip().lower().rstrip('.')
    if not d or d in AUTORISES:
        return False
    liste = domaines()
    morceaux = d.split('.')
    return any('.'.join(morceaux[i:]) in liste for i in range(len(morceaux) - 1))


def adresse_jetable(email):
    """True si l'adresse est sur un domaine jetable."""
    _, arobase, domaine = str(email or '').rpartition('@')
    return bool(arobase) and domaine_jetable(domaine)
