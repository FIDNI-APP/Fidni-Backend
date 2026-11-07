"""Lecture d'une réponse d'élève : un nombre, écrit comme on l'écrit au lycée (12, −3, 0,5, 3/4, 2 026)."""
import re
from fractions import Fraction

_NOMBRE = re.compile(r'^[+-]?(\d+([.,]\d+)?|[.,]\d+)$')
LONGUEUR_MAX = 40


def lire(texte):
    """Fraction exacte, ou None si le texte n'est pas un nombre (la réponse n'est alors pas comptée comme un essai)."""
    if not isinstance(texte, str) or len(texte) > LONGUEUR_MAX:
        return None
    s = re.sub(r'[\s  ]', '', texte).replace('−', '-').replace('–', '-')
    morceaux = s.split('/')
    if len(morceaux) > 2 or not all(_NOMBRE.match(m) for m in morceaux):
        return None
    valeur = Fraction(morceaux[0].replace(',', '.'))
    if len(morceaux) == 2:
        bas = Fraction(morceaux[1].replace(',', '.'))
        if bas == 0:
            return None
        valeur /= bas
    return valeur


def juste(texte, attendue):
    valeur = lire(texte)
    return valeur is not None and valeur == lire(attendue)
