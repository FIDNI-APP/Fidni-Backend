"""Consigne système de l'IA : règles du site (consignes.md) + listes fermées tirées de la base (annexes)."""
import os

ICI = os.path.dirname(os.path.abspath(__file__))


def _annexes():
    from apps.caracteristics.models import Chapter, ClassLevel, Theorem
    from apps.caracteristics.notions import NOTIONS

    lignes = ['## Annexe A — Niveaux et chapitres (noms exacts)', '']
    for lv in ClassLevel.objects.order_by('order'):
        chap = list(Chapter.objects.filter(class_levels=lv).order_by('subfield__name', 'name').values_list('name', flat=True))
        if chap:
            lignes.append(f'- **{lv.name}** : ' + ' · '.join(chap))
    lignes += ['', '## Annexe B — Notions autorisées (`identifiant` (libellé), rangées par chapitre)', '']
    for chapitre, notions in NOTIONS.items():
        lignes.append(f'- {chapitre} : ' + ' · '.join(f'`{k}` ({v})' for k, v in notions.items()))
    lignes += ['', '## Annexe C — Théorèmes (noms exacts, avec leurs chapitres)', '']
    for th in Theorem.objects.prefetch_related('chapters').order_by('name'):
        chaps = ', '.join(sorted({c.name for c in th.chapters.all()}))
        lignes.append(f'- {th.name}' + (f' — {chaps}' if chaps else ''))
    return '\n'.join(lignes)


def systeme():
    with open(os.path.join(ICI, 'consignes.md'), encoding='utf-8') as fh:
        regles = fh.read()
    return regles + '\n\n' + _annexes()


RELECTURE = """Tu es maintenant le RELECTEUR de cette fiche, avec le document original sous les yeux. Un professeur
de mathématiques exigeant la relira après toi : rien ne doit t'échapper.

Vérifie, une par une :
1. Fidélité : chaque mot, nombre, signe, exposant, indice, racine, intervalle, barème de l'énoncé est identique
   au document ; aucune question oubliée, ajoutée ou déplacée ; aucune numérotation écrite dans le HTML.
2. Mathématiques : refais chaque calcul des solutions (développements, factorisations, limites, dérivées,
   valeurs numériques, réciproques en réinjectant) ; vérifie que chaque théorème est appliqué avec ses
   hypothèses écrites (continuité, stricte monotonie, intervalle, signes avant d'élever au carré…) ; aucune
   étape sautée ; méthodes du programme du niveau.
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
                    "champ": "enonce" | "solution", "html": "<nouveau HTML complet de ce champ>"}],
 "doutes": ["…"]}
Les identifiants « bloc » et « sous_question » sont ceux de l'extrait (attribut id). « modifications » est vide
si rien n'est à changer. Le HTML suit les règles des consignes (chaque \\ doublé dans le JSON)."""
