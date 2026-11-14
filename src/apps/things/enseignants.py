"""Enseignants des contenus (Natsu, 14/11/2026 : « que chaque contenu soit tagué par l'enseignant », filtre des listes).

Un enseignant est un NOM (« M. Khalid Haddar »), distinct des comptes : il peut ne pas être inscrit sur Fidni ; s'il
l'est, l'équipe le relie à son compte (`Enseignant.user`) et les membres connectés vont de son nom à son profil.
Seule l'équipe pose les tags (Pilotage › Enseignants, page d'un contenu) ; l'import d'une fiche les déduit de son
`credit` (« M. Haddar, M. Hafidi et M. Naoufel, professeurs de mathématiques »).
"""
import re
import unicodedata

CIVILITES = {'m.': 'M.', 'm': 'M.', 'mr': 'M.', 'mr.': 'M.', 'monsieur': 'M.',
             'mme': 'Mme', 'mme.': 'Mme', 'madame': 'Mme', 'mlle': 'Mme', 'mlle.': 'Mme', 'mademoiselle': 'Mme'}
# « , professeur de mathématiques », « , professeurs de mathématiques », « , enseignante … » : retirés.
_SUFFIXE = re.compile(r',?\s*\b(professeure?s?|profs?|enseignante?s?)\b.*$', re.I)
_SEPARATEURS = re.compile(r'\s*,\s*|\s+et\s+|\s*&\s*|\s*/\s*', re.I)


def cle(texte: str) -> str:
    """Nom comparable : sans accents, casse, tirets ni espaces en trop (« En-Najjary » = « en najjary »)."""
    t = unicodedata.normalize('NFKD', texte or '').encode('ascii', 'ignore').decode().lower()
    return ' '.join(re.sub(r'[-\'’.]', ' ', t).split())


def _casse(mot: str) -> str:
    """« HADDAR » → « Haddar » ; un nom déjà en casse mixte est gardé tel quel."""
    return mot.title() if mot.isupper() and len(mot) > 1 else mot


def analyser(texte: str) -> list:
    """Crédit d'une fiche → [{civilite, prenom, nom}]. Un seul mot = le nom ; sinon prénom puis nom."""
    t = _SUFFIXE.sub('', (texte or '').strip())
    out = []
    for part in _SEPARATEURS.split(t):
        mots = part.strip().split()
        civ = ''
        if mots and mots[0].lower() in CIVILITES:
            civ = CIVILITES[mots.pop(0).lower()]
        elif mots and re.match(r'^M\.\S', mots[0]):  # « M.Haddar »
            civ, mots[0] = 'M.', mots[0][2:]
        mots = [_casse(m) for m in mots if m]
        if not mots:
            continue
        prenom, nom = ('', mots[0]) if len(mots) == 1 else (mots[0], ' '.join(mots[1:]))
        out.append({'civilite': civ, 'prenom': prenom[:60], 'nom': nom[:80]})
    return out


def trouver_ou_creer(civilite: str, prenom: str, nom: str):
    """Même nom (sans accents ni casse) = même enseignant : « M. Haddar » retrouve « M. Khalid Haddar », et un
    prénom manquant est complété. Deux prénoms différents = deux personnes."""
    from .models import Enseignant
    k = cle(nom)
    memes = [e for e in Enseignant.objects.all() if cle(e.nom) == k]
    if prenom:
        pareil = [e for e in memes if cle(e.prenom) == cle(prenom)]
        if pareil:
            return pareil[0]
        sans = [e for e in memes if not e.prenom]
        if len(sans) == 1:
            e = sans[0]
            e.prenom = prenom
            e.civilite = e.civilite or civilite
            e.save(update_fields=['prenom', 'civilite'])
            return e
    elif memes:
        # Sans prénom : celui qui a le plus de contenus (le plus probable).
        return max(memes, key=lambda e: (e.contenus.count(), -e.id))
    return Enseignant.objects.create(civilite=civilite, prenom=prenom, nom=nom)


def depuis_credit(texte: str) -> list:
    return [trouver_ou_creer(**p) for p in analyser(texte)]


def attacher_depuis_credit(content, texte: str):
    """Import d'une fiche : ses enseignants deviennent ceux du crédit (rien à faire sans crédit)."""
    if (texte or '').strip():
        content.enseignants.set(depuis_credit(texte))


def voit_les_comptes(viewer) -> bool:
    return bool(viewer is not None and getattr(viewer, 'is_authenticated', False))


def serialiser(enseignants, viewer=None) -> list:
    """[{id, nom, profil}] : `profil` (pseudo du compte relié) seulement pour un membre connecté — un visiteur
    ne doit pas pouvoir relier un pseudo à une vraie personne (même règle que users/noms.py)."""
    from apps.users.account_deletion import is_deleted_account
    voir = voit_les_comptes(viewer)
    out = []
    for e in enseignants:
        u = e.user if voir else None
        out.append({'id': e.id, 'nom': e.nom_affiche,
                    'profil': u.username if u is not None and not is_deleted_account(u) else None})
    return out


def texte(enseignants) -> str:
    """« M. Khalid Haddar et M. Hafidi » (pré-rendu, en-tête)."""
    noms = [e.nom_affiche for e in enseignants]
    return noms[0] if len(noms) == 1 else (', '.join(noms[:-1]) + ' et ' + noms[-1] if noms else '')
