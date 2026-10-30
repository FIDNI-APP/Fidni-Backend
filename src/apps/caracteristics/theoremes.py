"""Théorèmes des questions (13/10/2026).

Chaque question d'un contenu porte dans son json_content (`meta.theorems`, question ou sous-question) les noms exacts
des théorèmes de la base qu'elle utilise (caracteristics.Theorem : liste du programme officiel, programme.py
`theoremes` / DOMAINE_THEOREME). Ils remplacent les anciennes « notions » (liste fermée maison, supprimée) partout :
chapitre d'une question (Ma progression), théorèmes à retravailler, exercices de l'objectif, contenus
similaires, import et IA. Une question purement calculatoire n'en a aucun : elle compte pour les chapitres du contenu.
Pas affichés aux élèves.

Noms plutôt qu'identifiants : les mêmes en développement et en production, lisibles dans le JSON, ceux que l'IA et
les fiches emploient déjà ; un ancien nom (programme.ALIAS_THEOREMES) est traduit à la lecture.
"""
import time

from django.core.cache import cache

INDEX_KEY = 'theoremes:index:v1'
TIMEOUT = 600
MEMOIRE = 60  # secondes : copie gardée dans le processus (30/10/2026)

# index() est appelé un millier de fois par calcul de « Ma progression » : relu à chaque fois dans le cache fichier
# (lecture + décompression + unpickle), il coûtait 0,8 s sur 1,2 s. Copie en mémoire du processus, rafraîchie
# chaque minute (les autres processus gunicorn voient un changement de la liste au plus 60 s après).
_memoire = {'expire': 0.0, 'data': None}


def cle(nom):
    return ' '.join(str(nom or '').lower().split())


def index():
    """{nom en minuscules: {'id', 'name', 'chapters': [ids]}} des théorèmes de la base (cache 10 min)."""
    if _memoire['data'] is not None and time.monotonic() < _memoire['expire']:
        return _memoire['data']
    out = cache.get(INDEX_KEY)
    if out is None:
        from .models import Theorem
        out = {cle(th.name): {'id': th.id, 'name': th.name, 'chapters': sorted(ch.id for ch in th.chapters.all())}
               for th in Theorem.objects.prefetch_related('chapters')}
        cache.set(INDEX_KEY, out, TIMEOUT)
    _memoire.update(expire=time.monotonic() + MEMOIRE, data=out)
    return out


def oublier():
    """Après un changement de la liste (seeder, migration) : l'index est relu."""
    cache.delete(INDEX_KEY)
    _memoire.update(expire=0.0, data=None)


def _alias():
    from .programme import ALIAS_THEOREMES
    return {cle(a): tuple(v) for a, v in ALIAS_THEOREMES.items()}


def traduire(noms):
    """Noms exacts de la base pour une liste de noms (casse ignorée, anciens noms traduits) → (connus, inconnus)."""
    idx, alias = index(), _alias()
    connus, inconnus, vus = [], [], set()
    for nom in noms or []:
        if not isinstance(nom, str) or not nom.strip():
            continue
        k = cle(nom)
        if k in idx:
            cibles = [nom]
        elif k in alias:
            cibles = list(alias[k])  # ancien nom ; vide = retiré du programme
        else:
            inconnus.append(nom)
            continue
        for c in cibles:
            hit = idx.get(cle(c))
            if hit and hit['name'] not in vus:
                vus.add(hit['name'])
                connus.append(hit['name'])
    return connus, inconnus


def chapitres(noms):
    """Identifiants des chapitres des théorèmes donnés (noms, anciens noms acceptés)."""
    idx = index()
    connus, _ = traduire(noms)
    return {ch for nom in connus for ch in idx[cle(nom)]['chapters']}


def du_chapitre(nom, chapter_id):
    """Ce théorème est-il au programme de ce chapitre ?"""
    hit = index().get(cle(nom))
    return bool(hit) and chapter_id in hit['chapters']


def noms_programme():
    """Noms exacts du programme officiel (sans la base : validation d'une fiche avant import)."""
    from .programme import DOMAINE_THEOREME
    return {cle(n): n for n in DOMAINE_THEOREME}


def de_la_question(meta):
    """Théorèmes d'une question (meta d'un bloc ou d'une sous-question) : liste de noms."""
    th = (meta or {}).get('theorems') or []
    return [t for t in th if isinstance(t, str) and t.strip()]


def des_questions(structure):
    """Théorèmes de toutes les questions et sous-questions d'un json_content (noms, sans doublon, dans l'ordre)."""
    out = []
    for b in (structure or {}).get('blocks') or []:
        for q in [b] + list(b.get('subQuestions') or []):
            for nom in de_la_question(q.get('meta') if isinstance(q, dict) else None):
                if nom not in out:
                    out.append(nom)
    return out


def ajouter_au_contenu(content):
    """Les théorèmes des questions s'ajoutent à ceux du contenu (filtre « Théorème » des listes, contenus
    similaires) : à l'enregistrement depuis l'éditeur, comme à l'import. N'en retire jamais."""
    connus, _ = traduire(des_questions(content.json_content))
    if connus:
        idx = index()
        content.theorems.add(*[idx[cle(n)]['id'] for n in connus])
