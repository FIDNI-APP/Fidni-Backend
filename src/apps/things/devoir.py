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
