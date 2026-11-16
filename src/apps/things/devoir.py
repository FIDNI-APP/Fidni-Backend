"""Type d'un devoir lu dans son titre (cartes des listes, Natsu 14/11/2026 : « DS n° 2, devoir maison, année scolaire »).

Les titres suivent la règle des imports (« Devoir surveillé n° 1 (rattrapage) — 2ème Bac SM (octobre 2024) »,
« Contrôle continu n° 2 — … (2023-2024) ») : on en tire le genre, le numéro, le rattrapage et l'année scolaire.
Un titre qui ne dit rien de tout ça → None (la carte n'affiche rien de plus).
"""
import re

GENRES = [
    ('synthese', r'devoir\s+de\s+synth[eè]se'),
    ('controle', r'devoir\s+de\s+contr[oô]le|contr[oô]le(\s+continu)?'),
    ('ds', r'devoir\s+surveill[eé]|\bds\b'),
    ('dm', r'devoir\s+(maison|libre)|\bdm\b'),
    ('table', r'devoir\s+sur\s+table'),
    ('blanc', r'(examen|bac)\s+blanc'),
]
MOIS = {'janvier': 1, 'fevrier': 2, 'février': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6, 'juillet': 7,
        'aout': 8, 'août': 8, 'septembre': 9, 'octobre': 10, 'novembre': 11, 'decembre': 12, 'décembre': 12}


def annee_scolaire(titre: str):
    """« 2023-2024 » écrit tel quel, ou déduit d'un mois (« octobre 2024 » → 2024-2025, « mai 2025 » → 2024-2025)."""
    m = re.search(r'\b(20\d\d)\s*[-–/]\s*(20\d\d)\b', titre)
    if m and int(m.group(2)) == int(m.group(1)) + 1:
        return f'{m.group(1)}-{m.group(2)}'
    m = re.search(r'\b(' + '|'.join(MOIS) + r')\s+(20\d\d)\b', titre, re.I)
    if m:
        mois, an = MOIS[m.group(1).lower()], int(m.group(2))
        debut = an if mois >= 9 else an - 1
        return f'{debut}-{debut + 1}'
    return None


def type_devoir(titre: str, national: bool = False):
    """{genre, numero, rattrapage, annee_scolaire} ou None. Un sujet du Bac national a déjà son étiquette."""
    if national or not titre:
        return None
    t = titre.lower()
    genre = next((g for g, motif in GENRES if re.search(motif, t)), None)
    an = annee_scolaire(titre)
    if genre is None and an is None:
        return None
    m = re.search(r'n\s*[°ºo]\s*(\d{1,2})\b', t)
    return {
        'genre': genre,
        'numero': int(m.group(1)) if m and genre else None,
        'rattrapage': 'rattrapage' in t,
        'annee_scolaire': an,
    }


# ───────────── Rangement par semestre et par numéro (Natsu, 16/11/2026) ─────────────
# Les élèves cherchent « le DS n° 2 du semestre 1 », pas un chapitre : sur la page d'un niveau, les devoirs sont
# rangés par semestre puis par numéro (hubs.py `devoirs`), les chapitres restant un second choix. Au Maroc, la
# numérotation repart à 1 à chaque semestre (« devoir n° 1 du semestre 2 »).

# Genres numérotés comme un devoir surveillé : un devoir maison (ou libre) n° 1 va avec le DS n° 1 (Natsu, 17/11/2026) ;
# un bac blanc va dans « Autres devoirs ».
GENRES_NUMEROTES = {'ds', 'controle', 'synthese', 'table', 'dm'}
_SEMESTRE = [
    (1, re.compile(r'semestre\s*(?:n\s*[°ºo]\s*)?1\b|\b(?:1\s*(?:er|ère|e)?|premier)\s+semestre|\bs\s?1\b', re.I)),
    (2, re.compile(r'semestre\s*(?:n\s*[°ºo]\s*)?2\b|\b(?:2\s*(?:e|ème|nd)?|second|deuxi[eè]me)\s+semestre|\bs\s?2\b', re.I)),
]
_NUMERO_COURT = re.compile(r'\b(?:cc|ds)\s?(\d{1,2})\b|\bdevoir\s+n\s*[°ºo]\s*(\d{1,2})\b', re.I)
_MOIS = re.compile(r'\b(' + '|'.join(MOIS) + r')\s+(20\d\d)\b', re.I)


def semestre_du_titre(titre: str):
    """1 ou 2 si le titre le dit (« semestre 1 », « S2 »), sinon d'après le mois (septembre à janvier : 1 ; février
    à août : 2), sinon None."""
    for sem, motif in _SEMESTRE:
        if motif.search(titre or ''):
            return sem
    m = _MOIS.search(titre or '')
    if m:
        mois = MOIS[m.group(1).lower()]
        return 1 if mois >= 9 or mois == 1 else 2
    return None


def semestre_de_periode(periode: str):
    """« Semestre 1 (semaines 3–4) » (programme.py) → 1 ; le premier semestre cité pour un chapitre à cheval."""
    m = re.search(r'semestre\s*(\d)', periode or '', re.I)
    return int(m.group(1)) if m and m.group(1) in '12' else None


def rang(titre: str, periodes=()):
    """(semestre, numéro) d'un devoir de classe. Semestre : titre, puis mois, puis période du programme de son chapitre
    (`periodes`, dernier chapitre d'abord), sinon 1. Numéro : None pour un devoir non numéroté (« Autres devoirs »)."""
    td = type_devoir(titre) or {}
    numero = td.get('numero') if td.get('genre') in GENRES_NUMEROTES else None
    # « CC2 », « DS 3 », « Devoir n° 1 » (sans « surveillé ») : numérotés aussi, sauf un bac blanc.
    if numero is None and td.get('genre') != 'blanc':
        m = _NUMERO_COURT.search(titre or '')
        numero = int(m.group(1) or m.group(2)) if m else None
    sem = semestre_du_titre(titre)
    if sem is None:
        sem = next((s for s in map(semestre_de_periode, periodes) if s), None) or 1
    return sem, numero


_SLUG = re.compile(r'devoir-(\d{1,2})-semestre-([12])|autres-devoirs-semestre-([12])')


def slug_devoir(semestre: int, numero):
    return f'devoir-{numero}-semestre-{semestre}' if numero else f'autres-devoirs-semestre-{semestre}'


def lire_slug_devoir(slug: str):
    """« devoir-2-semestre-1 » → (1, 2) ; « autres-devoirs-semestre-2 » → (2, None) ; autre chose → None."""
    m = _SLUG.fullmatch(slug or '')
    if not m:
        return None
    if m.group(3):
        return int(m.group(3)), None
    numero = int(m.group(1))
    return (int(m.group(2)), numero) if numero > 0 else None


def nom_devoir(numero) -> str:
    return f'Devoir surveillé n° {numero}' if numero else 'Autres devoirs'
