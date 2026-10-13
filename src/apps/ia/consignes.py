"""Consigne système de l'IA : règles du site (consignes.md) + listes fermées tirées de la base (annexes A à C) +
programme officiel des niveaux du travail (annexe D, apps/caracteristics/programme.py).

Niveaux du travail (11/10/2026) : le niveau imposé par l'administrateur et son niveau précédent dans la filière
(niveaux_du_travail), « Lu dans le document » → les 4 ; fixés à la création du travail (job.options['niveaux'])
pour que tous ses appels reçoivent le même texte système (cache de l'API). Ils filtrent les annexes C et D.
"""
import os

ICI = os.path.dirname(os.path.abspath(__file__))


def niveaux_du_travail(niveaux=()):
    """Noms des niveaux dont l'IA reçoit le programme : ceux donnés (noms ou ClassLevel) et leur niveau précédent
    dans la filière, dans l'ordre de programme.NIVEAUX ; aucun niveau connu → les 4."""
    from apps.caracteristics.programme import NIVEAU_PRECEDENT, NIVEAUX, nom_niveau_actuel

    tous = [n for n, _o in NIVEAUX]
    par_cle = {n.lower(): n for n in tous}
    voulus = set()
    for n in niveaux or ():
        nom = par_cle.get(nom_niveau_actuel(str(getattr(n, 'name', n) or '')).strip().lower())
        if nom:
            voulus.add(nom)
            if nom in NIVEAU_PRECEDENT:
                voulus.add(NIVEAU_PRECEDENT[nom])
    return [n for n in tous if n in voulus] or tous


def _annexes(niveaux):
    from django.db.models import Prefetch

    from apps.caracteristics.models import Chapter, ClassLevel, Theorem
    from apps.caracteristics.notions import NOTIONS
    from apps.caracteristics.programme import MATIERE, ORDRE_NATURE, annexe_d, chapitres_du_niveau

    lignes = ['## Annexe A — Niveaux et chapitres (noms exacts, dans l\'ordre du programme de chaque niveau)', '']
    for lv in ClassLevel.objects.order_by('order', 'id'):
        chap = chapitres_du_niveau(lv, Chapter.objects.select_related('subfield'))
        if chap:
            nature = ORDRE_NATURE.get(lv.name)
            lignes.append(f'- **{lv.name}**' + (f' (ordre : {nature})' if nature else '') + ' : ' + ' · '.join(
                f'{i}. {ch.name}' + (f' ({ch.subfield.name})' if ch.subfield else '') for i, ch in enumerate(chap, 1)))
    lignes += ['', '## Annexe B — Notions autorisées (`identifiant` (libellé), rangées par chapitre)', '']
    for chapitre, notions in NOTIONS.items():
        lignes.append(f'- {chapitre} : ' + ' · '.join(f'`{k}` ({v})' for k, v in notions.items()))
    lignes += ['', f'## Annexe C — Théorèmes de {", ".join(niveaux)} (noms exacts, avec leurs chapitres)', '']
    theoremes = (Theorem.objects.filter(subject__name=MATIERE, class_levels__name__in=niveaux).distinct()
                 .prefetch_related(Prefetch('chapters', queryset=Chapter.objects.filter(subject__name=MATIERE)))
                 .order_by('name'))
    for th in theoremes:
        chaps = ', '.join(sorted({c.name for c in th.chapters.all()}))
        lignes.append(f'- {th.name}' + (f' — {chaps}' if chaps else ''))
    lignes += ['', annexe_d(niveaux)]
    return '\n'.join(lignes)


def systeme(niveaux=None):
    """Consigne système : règles + annexes. `niveaux` : noms des niveaux du travail (niveaux_du_travail), déjà
    complétés ; None ou vide = les 4."""
    with open(os.path.join(ICI, 'consignes.md'), encoding='utf-8') as fh:
        regles = fh.read()
    return regles + '\n\n' + _annexes(list(niveaux) if niveaux else niveaux_du_travail())


RELECTURE = """Tu es maintenant le RELECTEUR de cette fiche, avec le document original sous les yeux. Un professeur
de mathématiques exigeant la relira après toi : rien ne doit t'échapper.

Vérifie, une par une :
1. Fidélité : chaque mot, nombre, signe, exposant, indice, racine, intervalle, barème de l'énoncé est identique
   au document ; aucune question oubliée, ajoutée ou déplacée ; aucune numérotation écrite dans le HTML.
2. Mathématiques : refais chaque calcul des solutions (développements, factorisations, limites, dérivées,
   valeurs numériques, réciproques en réinjectant) ; vérifie que chaque théorème est appliqué avec ses
   hypothèses écrites (continuité, stricte monotonie, intervalle, signes avant d'élever au carré…) ; aucune
   étape sautée ; méthodes du programme du niveau, et vérifie qu'aucun résultat de la rubrique « Hors programme »
   du niveau (annexe D) n'est utilisé (le « périmètre habituel » n'est pas une interdiction).
3. Forme : premier paragraphe « Méthode : », puis rédaction continue sans intertitre d'étape, dernière phrase
   « Donc … » ; formules KaTeX valides ; lignes centrées pas trop longues ; métadonnées dans les annexes.

Réponds par exactement un bloc ```json :
{"problemes": [{"gravite": "corrige" | "a_verifier", "ou": "Exercice 2, question 1.3", "description": "…"}],
 "fiches": [ …les fiches entières, corrigées… ] ou null si tu n'as rien changé}
- « corrige » : erreur que tu as corrigée dans « fiches » (dis laquelle) ;
- « a_verifier » : point que le professeur doit regarder (doute de lecture, choix discutable, donnée incohérente
  du document…), sans correction certaine possible.
Si tu modifies, renvoie les fiches COMPLÈTES (même structure, mêmes clés)."""


SIGNALEMENT = """Tu corriges une erreur signalée par un élève sur un contenu publié de Fidni. Les règles de rédaction et de
format des consignes s'appliquent aux passages que tu réécris (HTML autorisé, KaTeX, rédaction façon copie avec
« Méthode : », conditions des théorèmes, aucune étape sautée).

Étapes :
1. Lis le signalement et l'extrait concerné ; vérifie par toi-même, en refaisant les calculs, si l'erreur existe.
2. Si elle existe : propose la correction MINIMALE (ne réécris que ce qui est faux ; garde le reste mot pour mot).
   Si l'énoncé lui-même semble faux, ne le change pas sans certitude : signale-le dans « doutes ».
3. Si le signalement n'est pas fondé : ne modifie rien et explique pourquoi, simplement.

Réponds par exactement un bloc ```json :
{"fonde": "oui" | "non" | "incertain",
 "explication": "ce qui est faux (ou pourquoi ce n'est pas une erreur), en 1 à 4 phrases claires",
 "modifications": [{"bloc": "<id du bloc>", "sous_question": "<id de la sous-question ou null>",
                    "champ": "enonce" | "indication" | "solution", "html": "<nouveau HTML complet de ce champ>"}],
 "doutes": ["…"]}
Les identifiants « bloc » et « sous_question » sont ceux de l'extrait (attribut id). « modifications » est vide
si rien n'est à changer. Le HTML suit les règles des consignes (chaque \\ doublé dans le JSON)."""
