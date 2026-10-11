"""Pseudos insultants refusés (11/10/2026, après un compte « l7way67 ») : inscription, changement de pseudo,
pseudo tiré d'une adresse Gmail.

Deux listes, à compléter ici :
- RACINES : cherchées n'importe où dans le pseudo (minuscules, sans « . _ - ») ; assez longues pour ne pas
  toucher de vrais prénoms. La darija écrite en lettres latines garde ses chiffres-lettres (3 = ع, 7 = ح,
  9 = ق) ; une seconde lecture « leet » (0→o, 1→i, 3→e, 4→a, 5→s, @→a, $→s) attrape « s4lope ».
- MOTS : trop courts pour être cherchés partout (« zb » est dans de vrais noms) ; refusés seulement comme mot
  entier, séparé par « . _ - » ou un chiffre (« fdp_2 », « zb.77 »).
Pas de liste parfaite : les cas qui passent se bannissent à la main (modération) et s'ajoutent ici.
"""
import re
import unicodedata

RACINES = (
    # darija (lettres latines)
    'l7wa', 'l7oua', '9a7ba', '9ahba', 'qa7ba', 'qahba', 'kahba', 'zamel', 'zbbi', 'zboub', 'tbon', 'tabon',
    'tboun', 'tabbon', 'nayek', 'n7wik', 'kh2a', 'mok7ba',
    # français
    'salop', 'connard', 'connass', 'encul', 'batard', 'putain', 'tapette', 'pedophil', 'enfoir', 'couill',
    'chatte', 'branleu', 'pouffi', 'trouduc',
    # anglais courant
    'fuck', 'bitch', 'whore', 'pussy', 'nigg', 'faggot', 'asshole',
)
# Mots entiers seulement : « nique » est dans « technique », « bite » dans « orbite », « khra » dans « Khraibi »,
# « zebi » dans « zebiba », « zaml » dans des noms de famille.
MOTS = ('pd', 'fdp', 'ntm', 'zb', 'zbi', 'zebi', 'zml', 'zaml', 'nik', 'niker', 'nique', 'niquer', 'khra',
        'pute', 'putes', 'bite', 'con', 'cons', 'merde', 'sex', 'xxx', 'porn')

_LEET = str.maketrans({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '@': 'a', '$': 's', '!': 'i'})


def _ascii(text):
    return unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()


def pseudo_interdit(username):
    """Vrai si le pseudo contient une insulte (voir RACINES et MOTS)."""
    brut = _ascii(username)
    colle = re.sub(r'[._\-\s]+', '', brut)
    lectures = {colle, colle.translate(_LEET)}
    if any(racine in lecture for racine in RACINES for lecture in lectures):
        return True
    mots = {m for m in re.split(r'[^a-z]+', brut) if m}
    mots |= {m for m in re.split(r'[^a-z]+', brut.translate(_LEET)) if m}
    return any(m in MOTS for m in mots)


PSEUDO_REFUSE = 'Ce nom d’utilisateur n’est pas accepté. Choisis-en un autre.'
