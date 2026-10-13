"""Programme officiel de mathématiques, niveau par niveau : SOURCE UNIQUE de la taxonomie (11/10/2026).

D'ici dérivent le seeder (tests/base_tables.py), l'ordre d'affichage d'un niveau, l'annexe D de la consigne de
l'IA, la traduction des anciens noms et la vérification « base = programme ». La migration
caracteristics/0003_programme_officiel en garde une copie FIGÉE : elle ne lit jamais ce module.

API publique
------------
Données (à lire, jamais à modifier en place) :
- NIVEAUX : [(nom du niveau, ClassLevel.order)], du plus jeune au plus avancé ; MATIERE = 'Mathématiques'.
- PROGRAMME : {nom du niveau: [chapitre, …]} dans l'ordre d'enseignement du niveau. Un chapitre est un dict :
  nom, domaine, ordre (1, 2, … dans le niveau), listes capacites, hors_programme, perimetre, reperes,
  vu_plus_tard, aussi, theoremes, contenus, sources ; textes titre_officiel, periode, heures, statut, remarque.
- ORDRE_NATURE : {niveau: nature de l'ordre} (seul celui du Tronc commun est officiel).
- DOMAINE_THEOREME : {théorème: domaine « maison »} (un seul domaine par théorème, même s'il est rattaché à des
  chapitres de plusieurs domaines) ; DOMAINE_CHAPITRE : {chapitre: domaine}.
- ALIAS_CHAPITRES : {ancien nom: {niveau ou None: (nouveaux noms,)}} — None : toujours traduit ; un niveau : seulement
  pour une fiche de ce niveau (voir traduire_noms). ALIAS_THEOREMES : {ancien nom: (nouveaux noms,)}, () = retiré
  sans remplaçant. ALIAS_SLUGS : {slug du niveau: {ancien slug de chapitre: nouveau slug}} (redirections 301).
- DECISIONS : réponses du propriétaire aux questions ouvertes (copie dans migrations/0003_programme_officiel.py).

Fonctions :
- rang(niveau) -> dict {nom de chapitre: ordre} ; un nom absent du programme du niveau vaut RANG_ABSENT (10**6)
  par l'indexation rang(niveau)[nom] (pas par .get()). `niveau` : nom ou ClassLevel.
- chapitre(niveau, nom) -> dict | None : copie de l'entrée du programme (pour `aussi`, `ordre`, `capacites`…).
- chapitres_du_niveau(level, queryset=None) -> list[Chapter] : chapitres de la matière Mathématiques rattachés au
  niveau (ClassLevel, id ou nom), triés par (rang, id) ; `queryset` permet un select_related / prefetch.
- annexe_d(niveaux=None) -> str : annexe D de la consigne de l'IA (Markdown) pour ces niveaux (noms ou
  ClassLevel ; None ou vide = les 4), dans l'ordre de NIVEAUX.
- traduire_noms(chapitres, theoremes=(), niveaux=()) -> (chapitres, theoremes, avertissements) : anciens noms
  d'une fiche traduits (import, fiches IA en attente), avant toute recherche par nom exact.
- ecarts_base() -> {'chapitres': [...], 'theoremes': [...]} : écarts entre la base et ce programme (lecture
  seule ; vide = conforme).

Champs d'un chapitre :
- envoyés à l'IA (annexe D) : nom, domaine, ordre, capacites, hors_programme, perimetre ; pour la 1ère Bac SM, dont
  le document officiel ne donne que les titres, aussi titre_officiel, reperes et vu_plus_tard, présentés comme
  des repères indicatifs (« Repères habituels du programme (indicatifs, non exhaustifs) » et « Habituellement vu
  plus tard (indicatif, pas une interdiction) »), jamais comme des règles ;
- affichage : aussi (mots d'un ancien dossier absorbé, gardés sur la page qui l'accueille) ;
- internes, jamais envoyés à l'IA : periode, heures, contenus, theoremes (l'IA les reçoit par l'annexe C, depuis
  la base), statut, sources, remarque, et titre_officiel hors TITRES_SEULS.
« Hors programme » = exclusion nette ; « périmètre » = lecture de la formulation, jamais une interdiction.

Modifier le programme : éditer les listes ci-dessous (ordre de la liste = ordre d'enseignement du niveau). Le seeder
n'AJOUTE que (get_or_create) : un chapitre ou un théorème retiré d'ici reste en base tant qu'une migration ne le
traite pas, et un renommage ici créerait un doublon (le nom fait office d'identifiant).
"""
from __future__ import annotations

import copy
import re

MATIERE = 'Mathématiques'
# 12/10/2026 : « 2ème Bac PC » renommé « 2ème Bac PC/SVT » (migration caracteristics/0004_pc_svt ; ancienne adresse
# du niveau : ALIAS_NIVEAUX, ancien nom accepté à l'import : NOMS_NIVEAUX_ANCIENS).
TC, SM1, SM2, PC = 'Tronc commun Sciences', '1ère Bac SM', '2ème Bac SM', '2ème Bac PC/SVT'

# (nom affiché, ordre des menus = ClassLevel.order), du plus jeune au plus avancé.
NIVEAUX = [(TC, 1), (SM1, 2), (SM2, 3), (PC, 4)]

# Nature de l'ordre des chapitres de chaque niveau : seul celui du Tronc commun est officiel, les autres sont des
# repères (jamais une contrainte sur les solutions).
ORDRE_NATURE = {
    TC: 'répartition TC (document officiel)',
    SM1: "répartition d'établissement (repère, non officielle)",
    SM2: "progression d'enseignant (repère, non officielle)",
    PC: "progression usuelle (repère, non officielle ; le cadre n'en donne pas)",
}

# Niveaux dont le document officiel ne donne que les titres et les heures : l'IA reçoit leurs titres officiels et
# nos repères, comme indications.
TITRES_SEULS = {SM1}

# Niveau précédent dans la même filière (prérequis permis). Le 2ème Bac PC/SVT suit la 1ère Bac Sciences
# expérimentales, absente du site.
NIVEAU_PRECEDENT = {SM1: TC, SM2: SM1}

# Réponses du propriétaire aux questions ouvertes (11/10/2026). Copie dans DECISIONS de
# migrations/0003_programme_officiel.py (tests/checks/check_programme.py vérifie que les deux disent la même chose).
DECISIONS = {
    # 1 : « Espaces vectoriels » (2ème Bac SM) GARDÉ comme chapitre à part, juste après « Structures algébriques »
    #     (le programme en fait un seul chapitre « Les structures » ; capacités 2.4.6-2.4.8 réparties entre les deux).
    'fusion_espaces_vectoriels': False,
    # 2 : « Dénombrement » détaché du 2ème Bac SM (il reste en 1ère Bac SM et en 2ème Bac PC) ; ses contenus de
    #     2ème Bac SM passent dans « Probabilités ».
    'detacher_denombrement_2sm': True,
    # 3 : trois leçons de 1ère Bac SM séparées de leur homonyme du Tronc commun (SCISSIONS_1ERE).
    'scinder_homonymes_1ere': True,
}

# Question 3 : chapitre partagé avec le Tronc commun → chapitre propre à la 1ère Bac SM.
SCISSIONS_1ERE = {
    'Calcul trigonométrique': 'Trigonométrie (formules de transformation)',
    'Produit scalaire dans le plan': 'Étude analytique du produit scalaire dans le plan',
    "Géométrie dans l'espace": "Géométrie analytique de l'espace",
}

RANG_ABSENT = 10 ** 6

CHAMPS_IA = ('nom', 'domaine', 'ordre', 'capacites', 'hors_programme', 'perimetre', 'reperes', 'vu_plus_tard')
CHAMPS_AFFICHAGE = ('aussi',)
CHAMPS_INTERNES = ('titre_officiel', 'periode', 'heures', 'contenus', 'theoremes', 'statut', 'sources', 'remarque')
_LISTES = ('capacites', 'hors_programme', 'perimetre', 'reperes', 'vu_plus_tard', 'aussi', 'theoremes', 'contenus',
           'sources')


def _chapitre(nom, domaine, **champs):
    inconnus = set(champs) - set(CHAMPS_IA + CHAMPS_AFFICHAGE + CHAMPS_INTERNES)
    assert not inconnus, f'{nom} : champ(s) inconnu(s) {sorted(inconnus)}'
    entree = {'nom': nom, 'domaine': domaine}
    for champ in _LISTES:
        entree[champ] = list(champs.pop(champ, []))
    entree.update({k: champs.get(k) for k in ('titre_officiel', 'periode', 'heures', 'statut', 'remarque')})
    return entree


# ── Tronc commun Sciences — ordre : répartition TC (document officiel)
_TC = [
    _chapitre('Ensembles de nombres ℕ, ℤ, 𝔻, ℚ et ℝ', 'Algèbre',
              titre_officiel='مجموعات الأعداد (tableau des capacités : المجموعات ℕ و ℤ و ℚ و ℝ)',
              periode='Semestre 1 (semaines 1–2)',
              heures=7,
              capacites=[
                  'Appréhender les relations entre les nombres et distinguer les différents ensembles de nombres ;',
                  "Déterminer une écriture adaptée d'une expression algébrique selon la situation étudiée.",
              ],
              theoremes=[
                  'Identités remarquables',
                  'Propriétés des puissances',
                  'Propriétés des racines carrées',
                  'Irrationalité de √2',
              ],
              contenus=[
                  'Les ensembles de nombres ℕ, ℤ, ℚ et ℝ ; distinction entre les différents ensembles de nombres',
                  'Relations entre les nombres',
                  "Écriture adaptée d'une expression algébrique selon la situation étudiée",
              ],
              statut='inchangé',
              remarque="Nom gardé (titre BIOF usuel) ; le document ne cite pas 𝔻 mais ne l'exclut pas."),
    _chapitre('Arithmétique dans ℕ', 'Algèbre',
              titre_officiel='الحسابيات (tableau des capacités : الحسابيات في ℕ)',
              periode='Semestre 1 (semaines 2–3)',
              heures=7,
              capacites=[
                  "Utiliser la parité et la décomposition d'un nombre en produit de facteurs premiers pour résoudre quelques problèmes simples sur les entiers naturels.",
              ],
              theoremes=[
                  'Critères de divisibilité',
                  'Parité de la somme et du produit',
                  'Décomposition en facteurs premiers',
                  'PGCD et PPCM par la décomposition en facteurs premiers',
              ],
              contenus=[
                  'Parité',
                  "Décomposition d'un entier naturel en produit de facteurs premiers",
                  'Résolution de problèmes simples sur les entiers naturels',
              ],
              statut='inchangé'),
    _chapitre('Calcul vectoriel dans le plan', 'Géométrie',
              titre_officiel='الحساب المتجهي',
              periode='Semestre 1 (semaines 3–4)',
              heures=5,
              capacites=[
                  'Construire un vecteur de la forme a·u⃗ + b·v⃗ ;',
                  "Exprimer des notions et des propriétés de la géométrie affine à l'aide de l'outil vectoriel, et réciproquement ;",
                  "Résoudre des problèmes géométriques à l'aide de l'outil vectoriel.",
              ],
              theoremes=[
                  'Relation de Chasles',
                  'Condition de colinéarité de deux vecteurs',
              ],
              contenus=[
                  "Construction d'un vecteur de la forme a·u⃗ + b·v⃗",
                  'Expression vectorielle des notions et propriétés de la géométrie affine, et réciproquement',
                  'Outil vectoriel dans la résolution de problèmes géométriques',
              ],
              statut='inchangé'),
    _chapitre('Projection dans le plan', 'Géométrie',
              titre_officiel='الاسقاط',
              periode='Semestre 1 (semaines 4–6)',
              heures=4,
              capacites=[
                  'Traduction vectorielle du théorème de Thalès.',
              ],
              theoremes=[
                  'Théorème de Thalès',
                  'Conservation du coefficient de colinéarité par projection',
              ],
              contenus=[
                  'Projection (titre de la leçon ; le document ne détaille pas les notions)',
                  'Traduction vectorielle du théorème de Thalès',
              ],
              statut='inchangé'),
    _chapitre('Ordre dans ℝ', 'Algèbre',
              titre_officiel='الترتيب (tableau des capacités : الترتيب و العمليات في ℝ)',
              periode='Semestre 1 (semaines 6–7)',
              heures=7,
              capacites=[
                  'Maîtriser les différentes techniques de comparaison de deux nombres (ou de deux expressions) et utiliser celle qui convient selon la situation étudiée (valeur absolue et ses propriétés ; intervalles ; encadrement et approximation, approximations décimales) ;',
                  "Représenter sur la droite numérique les différentes relations liées à l'ordre ;",
                  "Appréhender et déterminer une approximation d'un nombre (ou d'une expression) à une précision donnée ; effectuer des majorations ou des minorations d'expressions algébriques ;",
                  "Utiliser la calculatrice pour déterminer des valeurs approchées d'un nombre réel.",
              ],
              theoremes=[
                  'Ordre et opérations',
                  'Propriétés de la valeur absolue',
                  'Inégalité triangulaire',
              ],
              contenus=[
                  'Ordre et opérations dans ℝ : techniques de comparaison de deux nombres (ou de deux expressions)',
                  'Valeur absolue et ses propriétés',
                  'Intervalles',
                  'Encadrement et approximation ; approximations décimales',
                  "Représentation des relations d'ordre sur la droite numérique",
                  "Approximation d'un nombre (ou d'une expression) à une précision donnée",
                  "Majorations et minorations d'expressions algébriques",
                  "Valeurs approchées d'un nombre réel à la calculatrice",
              ],
              statut='inchangé'),
    _chapitre('Droite dans le plan', 'Géométrie',
              titre_officiel='المستقيم في المستوى',
              periode='Semestre 1 (semaine 8)',
              heures=5,
              capacites=[
                  "Traduire les notions et propriétés de la géométrie affine et de la géométrie vectorielle à l'aide des coordonnées ;",
                  "Utiliser l'outil analytique pour résoudre des problèmes géométriques.",
              ],
              theoremes=[
                  'Condition de colinéarité par le déterminant',
                  "Équation cartésienne et équation réduite d'une droite",
                  'Parallélisme de deux droites',
              ],
              contenus=[
                  "Traduction, à l'aide des coordonnées, des notions et propriétés de la géométrie affine et de la géométrie vectorielle",
                  'Outil analytique dans la résolution de problèmes géométriques',
              ],
              statut='inchangé'),
    _chapitre('Polynômes', 'Algèbre',
              titre_officiel='الحدوديات',
              periode='Semestre 1 (semaines 9–10)',
              heures=4,
              capacites=[
                  'Maîtriser la technique de la division euclidienne par x − α et appréhender la divisibilité par x − α.',
              ],
              theoremes=[
                  'Égalité de deux polynômes',
                  "Racine d'un polynôme et factorisation par (x − a)",
              ],
              contenus=[
                  'Division euclidienne par x − α',
                  'Divisibilité par x − α',
              ],
              statut='inchangé'),
    _chapitre('Équations, inéquations et systèmes', 'Algèbre',
              titre_officiel='المعادلات و المتراجحات و النظمات',
              periode='Semestre 1 (semaines 10–12)',
              heures=8,
              capacites=[
                  'Résoudre des équations et des inéquations dont la résolution se ramène à des équations et des inéquations du premier ou du second degré à une inconnue ;',
                  'Résoudre des systèmes du premier degré à deux inconnues en utilisant différentes méthodes (combinaison linéaire, substitution, déterminant) ;',
                  "Mathématiser des situations comportant des grandeurs variables à l'aide d'expressions, d'équations, d'inéquations, d'inégalités ou de systèmes ;",
                  "Représenter graphiquement les solutions d'inéquations ou de systèmes d'inéquations du premier degré à deux inconnues, et utiliser cette représentation pour le régionnement du plan.",
              ],
              theoremes=[
                  "Discriminant et racines d'un trinôme",
                  'Signe du trinôme',
                  'Somme et produit des racines',
                  'Méthode du déterminant (Cramer) pour un système 2×2',
              ],
              contenus=[
                  'Équations et inéquations se ramenant au premier ou au second degré à une inconnue',
                  'Systèmes du premier degré à deux inconnues : méthodes de combinaison linéaire, de substitution et du déterminant',
                  'Mathématisation de situations comportant des grandeurs variables (expressions, équations, inéquations, inégalités, systèmes)',
                  "Inéquations et systèmes d'inéquations du premier degré à deux inconnues : représentation graphique des solutions",
                  'Régionnement du plan',
              ],
              statut='inchangé'),
    _chapitre('Calcul trigonométrique', 'Analyse',
              titre_officiel='الحساب المثلثي (Calcul trigonométrique), une seule leçon en deux parties (S1 puis S2)',
              periode='Semestre 1 (semaines 12–15) puis semestre 2 (semaines 1–2)',
              heures=20,
              capacites=[
                  "Utiliser la calculatrice scientifique pour déterminer une valeur approchée d'un angle défini par l'un de ses rapports trigonométriques, et inversement ;",
                  'Maîtriser les rapports trigonométriques des angles usuels et appliquer les différentes relations.',
                  "Maîtriser le tracé de la courbe de chacune des fonctions sin et cos et l'exploiter pour appréhender et consolider les notions de périodicité, de parité et de monotonie… ;",
                  "Maîtriser la représentation et la lecture, sur le cercle trigonométrique, des solutions d'une équation ou d'une inéquation trigonométrique.",
              ],
              theoremes=[
                  'Relation cos²x + sin²x = 1',
                  'Angles associés',
                  'Équations trigonométriques de base',
              ],
              contenus=[
                  'Rapports trigonométriques des angles usuels',
                  'Relations trigonométriques',
                  "Valeur approchée, à la calculatrice scientifique, d'un angle défini par l'un de ses rapports trigonométriques, et inversement",
                  'Courbes des fonctions sin et cos',
                  'Périodicité, parité, monotonie (liste ouverte dans le document : « … »)',
                  'Équations et inéquations trigonométriques : représentation et lecture des solutions sur le cercle trigonométrique',
              ],
              statut='inchangé',
              remarque="Garde la ligne, le nom et l'URL actuels. N'est plus partagé avec la 1ère Bac SM (scission) : les formules de transformation de 1ère partent dans « Trigonométrie (formules de transformation) »."),
    _chapitre('Statistiques', 'Statistiques',
              titre_officiel='الاحصاء (tableau des capacités : الإحصاء)',
              periode='Semestre 1 (semaine 15)',
              heures=3,
              capacites=[
                  'Organiser des données statistiques ; lire et interpréter des diagrammes statistiques ;',
                  'Interpréter les paramètres de position et de dispersion ; distinguer les différents paramètres de position ; distinguer les différents paramètres de dispersion.',
              ],
              theoremes=[
                  'Moyenne, variance et écart type',
              ],
              contenus=[
                  'Organisation de données statistiques',
                  'Lecture et interprétation de diagrammes statistiques',
                  'Paramètres de position',
                  'Paramètres de dispersion',
              ],
              statut='inchangé'),
    _chapitre('Généralités sur les fonctions', 'Analyse',
              titre_officiel='الدوال العددية',
              periode='Semestre 2 (semaines 3–7)',
              heures=20,
              capacites=[
                  "Reconnaître la variable et l'ensemble de définition d'une fonction définie par un tableau de données, par une courbe ou par une formule ;",
                  "Lire l'image d'un nombre et déterminer un nombre dont l'image est connue à partir de la représentation graphique d'une fonction ;",
                  "Déduire les variations d'une fonction ou ses valeurs maximales et minimales à partir de sa représentation graphique ;",
                  'Utiliser la représentation graphique pour étudier certaines équations et inéquations ;',
                  "Maîtriser le tracé de la courbe d'une fonction polynôme du second degré ou d'une fonction homographique sans recourir au changement de repère ;",
                  "Exprimer, à l'aide de la notion de fonction, des situations issues de la réalité ou d'autres disciplines.",
              ],
              hors_programme=[
                  "Changement de repère pour tracer la courbe d'une fonction polynôme du second degré ou d'une fonction homographique : le tracé se fait sans changement de repère.",
              ],
              theoremes=[
                  'Fonctions paires et impaires',
                  'Sens de variation et taux de variation',
                  'Fonctions de référence (x², 1/x, √x, ax² + bx + c, (ax + b)/(cx + d))',
              ],
              contenus=[
                  "Variable et ensemble de définition d'une fonction définie par un tableau de données, par une courbe ou par une formule",
                  "Image d'un nombre ; nombre dont l'image est connue (lecture graphique)",
                  "Variations d'une fonction ; valeurs maximales et minimales lues sur la représentation graphique",
                  'Étude graphique de certaines équations et inéquations',
                  "Courbe d'une fonction polynôme du second degré",
                  "Courbe d'une fonction homographique",
                  "Modélisation de situations issues de la réalité ou d'autres disciplines par la notion de fonction",
              ],
              statut='inchangé',
              sources=[
                  'Exclusion explicite : le document demande ce tracé « sans recourir au changement de repère ».',
              ],
              remarque="Reste partagé avec la 1ère Bac SM : même leçon (la 1ère reprend le Tronc commun et l'approfondit), même nom usuel aux deux niveaux."),
    _chapitre('Produit scalaire dans le plan', 'Géométrie',
              titre_officiel='الجداء السلمي',
              periode='Semestre 2 (semaines 8–9)',
              heures=7,
              capacites=[
                  "Exprimer la distance et l'orthogonalité à l'aide du produit scalaire ;",
                  'Utiliser le produit scalaire pour résoudre des problèmes géométriques ;',
                  "Utiliser le théorème d'Al-Kashi et le théorème de la médiane pour résoudre des exercices de géométrie.",
              ],
              theoremes=[
                  "Théorème d'Al-Kashi",
                  'Théorème de la médiane',
                  "Caractérisation de l'orthogonalité par le produit scalaire",
              ],
              contenus=[
                  "Expression de la distance et de l'orthogonalité par le produit scalaire",
                  'Produit scalaire dans la résolution de problèmes géométriques',
                  "Théorème d'Al-Kashi",
                  'Théorème de la médiane',
              ],
              statut='inchangé',
              remarque="Garde la ligne et l'URL. N'est plus partagé avec la 1ère Bac SM (scission vers « Étude analytique du produit scalaire dans le plan »)."),
    _chapitre('Transformations du plan', 'Géométrie',
              titre_officiel='التحويلات (tableau des capacités : التحويلات في المستوى)',
              periode='Semestre 2 (semaines 9–10)',
              heures=5,
              capacites=[
                  "Reconnaître des figures isométriques et des figures semblables à l'aide de la translation, de l'homothétie et de la symétrie ;",
                  "Utiliser la translation, l'homothétie et la symétrie pour résoudre des problèmes géométriques.",
              ],
              theoremes=[
                  'Propriétés de conservation des transformations',
                  "Image d'une droite et d'un cercle par une transformation",
              ],
              contenus=[
                  'Translation, homothétie, symétrie',
                  'Figures isométriques et figures semblables obtenues par translation, homothétie et symétrie',
                  'Transformations dans la résolution de problèmes géométriques',
              ],
              statut='inchangé'),
    _chapitre("Géométrie dans l'espace", 'Géométrie',
              titre_officiel='الهندسة الفضائية',
              periode='Semestre 2 (semaines 11–14)',
              heures=13,
              capacites=[
                  "Reconnaître et représenter dans le plan des parties de l'espace ;",
                  "Appréhender les cas d'analogie et de non-analogie entre des notions et propriétés du plan et leurs homologues dans l'espace ;",
                  "Utiliser les propriétés de la géométrie dans l'espace pour résoudre des problèmes issus de la réalité.",
              ],
              theoremes=[
                  'Théorème du toit',
                  "Parallélisme d'une droite et d'un plan, de deux plans",
                  "Orthogonalité d'une droite et d'un plan",
              ],
              contenus=[
                  "Représentation dans le plan de parties de l'espace",
                  "Analogies et différences entre les notions et propriétés du plan et leurs homologues dans l'espace",
                  "Propriétés de la géométrie dans l'espace appliquées à des problèmes issus de la réalité",
              ],
              statut='inchangé',
              remarque="Garde la ligne et l'URL. N'est plus partagé avec la 1ère Bac SM (scission vers « Géométrie analytique de l'espace »)."),
]

# ── 1ère Bac SM — ordre : répartition d'établissement (repère, non officielle)
_SM1 = [
    _chapitre('Logique mathématique', 'Algèbre',
              titre_officiel='La logique',
              periode='Trimestre 1',
              heures=8,
              theoremes=[
                  'Lois de De Morgan',
                  'Raisonnement par contraposée',
                  "Raisonnement par l'absurde",
                  'Raisonnement par récurrence',
              ],
              statut='inchangé',
              reperes=[
                  "Propositions, valeur de vérité ; fonctions propositionnelles (propositions dépendant d'une ou de plusieurs variables).",
                  'Connecteurs logiques : négation, conjonction, disjonction, implication, équivalence ; tables de vérité.',
                  "Lois logiques usuelles : lois de De Morgan, loi de contraposition, transitivité de l'implication.",
                  "Quantificateurs universel (∀) et existentiel (∃, ∃!) ; négation d'une proposition quantifiée ; importance de l'ordre des quantificateurs.",
                  "Types de raisonnement : par équivalences successives, par disjonction des cas, par contraposée, par l'absurde, par contre-exemple, par récurrence.",
                  "Capacités habituellement visées : employer correctement connecteurs et quantificateurs, écrire la négation d'une proposition, choisir le type de raisonnement adapté à la situation.",
                  "Orientation habituelle : éviter tout formalisme excessif ; introduire les notions à partir d'exemples tirés des acquis des élèves, puis les réinvestir tout au long de l'année (la logique est un outil).",
              ],
              remarque='Titre du document « La logique » ; nom actuel gardé (équivalent usuel de « Notions de logique »).'),
    _chapitre('Ensembles et applications', 'Algèbre',
              titre_officiel='Les ensembles et les applications',
              periode='Trimestre 1',
              heures=12,
              theoremes=[
                  'Opérations sur les ensembles et lois de De Morgan',
                  'Composée de deux bijections',
                  "Application réciproque d'une bijection",
              ],
              contenus=[
                  "Les ensembles (d'après le titre)",
                  "Les applications (d'après le titre)",
              ],
              statut='inchangé',
              reperes=[
                  'Ensemble, élément, appartenance ; ensemble défini en extension ou en compréhension ; ensemble vide, singleton.',
                  'Inclusion, égalité de deux ensembles ; ensemble des parties P(E).',
                  'Opérations sur les ensembles : complémentaire, intersection, réunion, différence A∖B ; propriétés (distributivité, lois de De Morgan) ; produit cartésien de deux ensembles.',
                  'Différence symétrique A Δ B. (à vérifier)',
                  "Application d'un ensemble E dans un ensemble F : image, antécédent, égalité de deux applications ; restriction et prolongement d'une application.",
                  "Image directe f(A) et image réciproque f⁻¹(B) d'une partie.",
                  'Applications injectives, surjectives, bijectives ; bijection réciproque ; composée de deux applications ; composée de deux bijections et sa réciproque ((g∘f)⁻¹ = f⁻¹∘g⁻¹).',
                  "Relations binaires (relation d'équivalence, relation d'ordre) : présentes dans d'anciens programmes de 1ère SM, leur place dans le programme de 2007 est incertaine. (à vérifier)",
              ]),
    _chapitre('Généralités sur les fonctions', 'Analyse',
              titre_officiel='Généralités sur les fonctions',
              periode='Trimestre 1',
              heures=12,
              theoremes=[
                  'Fonction majorée, minorée, bornée',
                  "Monotonie d'une fonction composée",
                  'Fonction périodique',
              ],
              statut='inchangé',
              reperes=[
                  'Rappels du Tronc commun : ensemble de définition, égalité de deux fonctions, parité et interprétation graphique, sens de variation, taux de variation.',
                  'Fonction majorée, minorée, bornée.',
                  "Extremums (maximum, minimum) d'une fonction sur un intervalle, absolus et relatifs.",
                  'Comparaison de deux fonctions (f ≤ g) et interprétation graphique : position relative de deux courbes.',
                  'Fonction périodique.',
                  "Composée de deux fonctions ; sens de variation d'une fonction composée.",
                  'Représentation graphique de x ↦ ax³ et de x ↦ √(x + a) ; rappels sur x ↦ ax² + bx + c et x ↦ (ax + b)/(cx + d).',
                  "Éléments de symétrie d'une courbe (axe, centre) et courbes déduites (x ↦ f(x) + b, x ↦ f(x + a), x ↦ |f(x)|) : peuvent aussi relever du chapitre « Étude des fonctions ». (à vérifier)",
                  "Résolution graphique d'équations et d'inéquations.",
              ],
              remarque='Partagé avec le Tronc commun (même leçon, approfondie).'),
    _chapitre('Suites numériques', 'Analyse',
              titre_officiel='Les suite numériques',
              periode='Trimestre 1',
              heures=12,
              theoremes=[
                  'Suites arithmétiques et géométriques',
                  'Somme de termes consécutifs',
                  'Suite majorée, minorée, monotone',
                  'Raisonnement par récurrence',
              ],
              statut='inchangé',
              reperes=[
                  'Généralités : suite numérique, notation (uₙ), terme général ; suite définie par une formule explicite ou par une relation de récurrence.',
                  'Suite majorée, minorée, bornée ; suite croissante, décroissante, monotone (strictement ou non).',
                  'Suite périodique. (à vérifier)',
                  'Utilisation du raisonnement par récurrence sur les suites.',
                  'Suites arithmétiques : définition, raison, terme général, somme de termes consécutifs.',
                  'Suites géométriques : définition, raison, terme général, somme de termes consécutifs.',
                  'Utilisation des suites arithmétiques et géométriques pour modéliser des situations.',
              ],
              vu_plus_tard=[
                  'Limites de suites, critères de convergence, suites adjacentes, convergence des suites uₙ₊₁ = f(uₙ) (à vérifier) ; les suites définies par récurrence restent au programme de 1ère.',
              ],
              remarque='Partagé avec le 2ème Bac SM et le 2ème Bac PC : les programmes de 1ère et de 2ème année nomment tous deux la leçon « Les suites numériques ».'),
    _chapitre("Limites d'une fonction", 'Analyse',
              titre_officiel='Les limites d’une fonction numériques',
              periode='Trimestre 1',
              heures=14,
              theoremes=[
                  'Opérations sur les limites',
                  'Limites trigonométriques usuelles',
                  'Limites et ordre',
                  'Théorème des gendarmes',
              ],
              statut='inchangé',
              reperes=[
                  'Limite finie en un point (en filière SM, définition formelle avec ε et α, niveau de formalisation variable selon la classe) ; limite infinie en un point. (à vérifier)',
                  'Limite à droite, limite à gauche.',
                  'Limite finie ou infinie en +∞ et en −∞.',
                  'Limites des fonctions usuelles (x ↦ xⁿ, x ↦ 1/xⁿ, x ↦ √x) ; limites des fonctions polynômes et rationnelles en ±∞.',
                  'Opérations sur les limites (somme, produit, quotient) ; formes indéterminées.',
                  'Limites trigonométriques usuelles en 0 : sin x / x → 1, tan x / x → 1, (1 − cos x)/x² → 1/2.',
                  "Limites et ordre : théorèmes de comparaison, théorème d'encadrement (« des gendarmes »).",
                  'Limite de x ↦ √(u(x)). (à vérifier)',
              ],
              vu_plus_tard=[
                  "Continuité sur un intervalle, image d'un intervalle par une fonction continue, théorème des valeurs intermédiaires, dichotomie, fonction réciproque (à vérifier).",
              ]),
    _chapitre('Barycentre dans le plan', 'Géométrie',
              titre_officiel='Le barycentre',
              periode='Trimestre 1',
              heures=10,
              theoremes=[
                  'Associativité du barycentre',
                  'Coordonnées du barycentre',
              ],
              statut='inchangé',
              reperes=[
                  'Barycentre de deux points pondérés : définition (somme des coefficients non nulle), construction, propriété caractéristique, homogénéité ; cas du milieu (isobarycentre).',
                  'La droite (AB) et le segment [AB] comme ensembles de barycentres de A et B.',
                  "Barycentre de trois et de quatre points pondérés ; centre de gravité d'un triangle ; associativité (barycentres partiels).",
                  'Généralisation au barycentre de n points pondérés. (à vérifier)',
                  'Coordonnées du barycentre dans un repère.',
                  "Applications : alignement de points, droites concourantes, réduction d'une somme vectorielle pondérée et détermination d'ensembles de points (lieux géométriques).",
                  'Lignes de niveau (ensembles de points M définis par une relation métrique pondérée). (à vérifier)',
                  "Extension du barycentre à l'espace (le titre officiel dit seulement « Le barycentre »). (à vérifier)",
              ]),
    _chapitre('Étude analytique du produit scalaire dans le plan', 'Géométrie',
              titre_officiel='Analytique du produit scalaire dans le plan',
              periode='Trimestre 1',
              heures=16,
              theoremes=[
                  'Expression analytique du produit scalaire',
                  "Distance d'un point à une droite",
                  "Équation d'un cercle",
              ],
              contenus=[
                  "Étude analytique du produit scalaire dans le plan (d'après le titre)",
              ],
              statut='scindé',
              reperes=[
                  "Rappels du Tronc commun : définition et propriétés du produit scalaire, théorème d'Al-Kashi, théorème de la médiane.",
                  "Base et repère orthonormés ; expression analytique du produit scalaire ; norme d'un vecteur ; distance entre deux points.",
                  "Expressions de cos et de sin d'un angle orienté de deux vecteurs en fonction des coordonnées dans un repère orthonormé direct (sin par le déterminant).",
                  "Vecteur normal à une droite ; équation cartésienne d'une droite définie par un point et un vecteur normal ; orthogonalité de deux droites.",
                  "Distance d'un point à une droite : |ax₀ + by₀ + c| / √(a² + b²).",
                  "Cercle : équation cartésienne (centre et rayon) ; cercle de diamètre [AB] (MA→·MB→ = 0) ; étude de l'ensemble des points M(x, y) tels que x² + y² + ax + by + c = 0.",
                  "Représentation paramétrique d'un cercle.",
                  "Position relative d'une droite et d'un cercle ; tangente à un cercle en un de ses points.",
                  "Inéquations : intérieur et extérieur d'un disque. (à vérifier)",
              ],
              remarque="Nouveau chapitre issu de « Produit scalaire dans le plan » (partagé avec le Tronc commun) : le programme de 1ère est l'étude ANALYTIQUE (titre officiel), celui du Tronc commun l'outil vectoriel."),
    _chapitre('Trigonométrie (formules de transformation)', 'Analyse',
              titre_officiel='La trigonométrie (les formules de transformation)',
              periode='Trimestre 1',
              heures=12,
              aussi=[
                  'calcul trigonométrique',
              ],
              theoremes=[
                  "Formules d'addition",
                  'Formules de duplication',
                  'Transformation de a cos x + b sin x',
                  'Formules de transformation somme-produit',
              ],
              contenus=[
                  'Les formules de transformation (précisées entre parenthèses dans le titre)',
              ],
              statut='scindé',
              reperes=[
                  "Formules d'addition : cos(a ± b), sin(a ± b), tan(a ± b).",
                  'Formules de duplication : cos 2a, sin 2a, tan 2a ; expression de cos²a et sin²a en fonction de cos 2a (linéarisation).',
                  'Expression de cos x, sin x et tan x en fonction de t = tan(x/2).',
                  'Transformation de produits en sommes et de sommes en produits (cos p + cos q, cos p − cos q, sin p + sin q, sin p − sin q).',
                  'Transformation de a cos x + b sin x en r cos(x − φ).',
                  "Résolution d'équations et d'inéquations trigonométriques qui se ramènent à ces formules.",
              ],
              remarque='Nouveau chapitre issu de « Calcul trigonométrique » (partagé avec le Tronc commun) : la leçon de 1ère porte sur les formules de transformation (titre officiel), celle du Tronc commun sur le cercle trigonométrique et les rapports usuels.'),
    _chapitre('Rotation dans le plan', 'Géométrie',
              titre_officiel='La rotation dans le plan',
              periode='Trimestre 1',
              heures=16,
              theoremes=[
                  'Propriétés de la rotation',
                  'Composée de deux symétries axiales',
              ],
              statut='inchangé',
              reperes=[
                  "Rappels et compléments sur les angles orientés (mesures, relation de Chasles) : prérequis. (à vérifier)",
                  "Définition de la rotation de centre Ω et d'angle α ; cas particuliers : identité (α ≡ 0 [2π]), symétrie centrale (α ≡ π [2π]) ; rotation réciproque.",
                  'Propriété caractéristique : si R(M) = M′ et R(N) = N′, alors M′N′ = MN et (MN→, M′N′→) ≡ α [2π].',
                  'Propriétés de conservation : distances, milieu et barycentre, alignement, parallélisme, orthogonalité, angles orientés, produit scalaire.',
                  "Image d'une droite, d'un segment, d'une demi-droite, d'un cercle ; angle entre une droite et son image.",
                  "Composée de deux symétries axiales d'axes sécants et décomposition d'une rotation en deux symétries axiales ; composée de deux rotations de même centre (le cas de centres différents est encore plus incertain). (à vérifier)",
                  'Utilisation des rotations pour résoudre des problèmes géométriques : constructions, lieux géométriques, démonstrations.',
              ]),
    _chapitre('Dénombrement', 'Probabilités',
              titre_officiel='Dénombrement',
              periode='Trimestre 2',
              heures=14,
              theoremes=[
                  'Principe multiplicatif',
                  'Arrangements et combinaisons',
                  'Formule du binôme de Newton',
                  'Triangle de Pascal',
              ],
              statut='inchangé',
              reperes=[
                  'Ensemble fini, cardinal ; card(A ∪ B) = card A + card B − card(A ∩ B) ; cardinal du complémentaire ; card(E × F).',
                  'Principe fondamental (multiplicatif) du dénombrement ; arbres de choix, tableaux.',
                  "p-listes (arrangements avec répétition) : nᵖ ; nombre d'applications d'un ensemble à p éléments dans un ensemble à n éléments.",
                  'Arrangements sans répétition Aₙᵖ ; permutations, factorielle n!.',
                  'Combinaisons Cₙᵖ ; propriétés Cₙᵖ = Cₙⁿ⁻ᵖ et formule de Pascal ; triangle de Pascal.',
                  "Nombre de parties d'un ensemble à n éléments : card P(E) = 2ⁿ.",
                  'Formule du binôme de Newton. (à vérifier)',
                  'Modélisation des tirages : simultanés, successifs avec remise, successifs sans remise.',
              ],
              vu_plus_tard=[
                  'Probabilités (à vérifier).',
              ],
              remarque='Partagé avec le 2ème Bac PC (même contenu) ; détaché du 2ème Bac SM.'),
    _chapitre('Dérivation', 'Analyse',
              titre_officiel='La dérivation et ses applications',
              periode='Trimestre 2',
              theoremes=[
                  "Dérivée d'une somme, d'un produit, d'un quotient",
                  'Équation de la tangente',
                  "Dérivée d'une fonction composée",
                  'Signe de la dérivée et sens de variation',
              ],
              contenus=[
                  "La dérivation (d'après le titre)",
                  "Applications de la dérivation (d'après le titre)",
              ],
              statut='inchangé',
              reperes=[
                  "Dérivabilité en un point, nombre dérivé ; interprétation géométrique : tangente et son équation ; approximation affine au voisinage d'un point.",
                  'Dérivabilité à droite et à gauche ; demi-tangentes.',
                  'Dérivabilité sur un intervalle, fonction dérivée ; dérivées des fonctions usuelles (polynômes, x ↦ 1/x, x ↦ √x, sin, cos, tan).',
                  'Opérations sur les fonctions dérivables : somme, produit, inverse, quotient, puissance uⁿ, x ↦ f(ax + b).',
                  "Dérivée de x ↦ √(u(x)) et dérivée d'une composée générale (capacité explicite du 2ème Bac SM). (à vérifier)",
                  'Dérivées successives (dérivée seconde).',
                  "Applications : signe de la dérivée et sens de variation ; extremums ; démonstration d'inégalités ; problèmes d'optimisation ; interprétation cinématique (vitesse instantanée).",
              ],
              vu_plus_tard=[
                  'Théorème de Rolle, théorème et inégalité des accroissements finis, dérivée de la fonction réciproque (à vérifier).',
              ],
              remarque='Titre du document « La dérivation et ses applications ».'),
    _chapitre('Étude des fonctions', 'Analyse',
              titre_officiel='Etude et représentation d’une fonction',
              periode='Trimestre 2',
              theoremes=[
                  'Branches infinies et asymptotes',
                  "Concavité et point d'inflexion",
                  "Centre et axe de symétrie d'une courbe",
              ],
              contenus=[
                  "Étude d'une fonction (d'après le titre)",
                  "Représentation graphique d'une fonction (d'après le titre)",
              ],
              statut='inchangé',
              reperes=[
                  "Branches infinies : asymptotes verticale, horizontale, oblique ; directions asymptotiques et branches paraboliques ; position relative d'une courbe et d'une asymptote.",
                  "Concavité d'une courbe et point d'inflexion (signe de la dérivée seconde).",
                  "Éléments de symétrie : axe x = a (f(2a − x) = f(x)) et centre Ω(a, b) (f(2a − x) + f(x) = 2b) ; réduction du domaine d'étude (parité, périodicité).",
                  'Étude et représentation graphique de fonctions polynômes, rationnelles, irrationnelles (avec racine carrée) et trigonométriques.',
                  "Résolution graphique d'équations et d'inéquations.",
                  "Discussion selon un paramètre (nombre de solutions de l'équation f(x) = m). (à vérifier)",
              ],
              remarque="Titre du document « Étude et représentation d'une fonction »."),
    _chapitre('Arithmétique dans ℤ', 'Algèbre',
              titre_officiel='L’arithmétique',
              periode='Trimestre 2',
              theoremes=[
                  'Division euclidienne dans ℤ',
                  'Congruences modulo n',
                  "PGCD, PPCM et algorithme d'Euclide",
                  'Décomposition en facteurs premiers',
                  'Infinité des nombres premiers',
              ],
              statut='inchangé',
              reperes=[
                  'Divisibilité dans ℤ : définition et propriétés (transitivité, combinaisons linéaires).',
                  'Division euclidienne dans ℤ (existence et unicité du quotient et du reste).',
                  "Congruence modulo n : définition, compatibilité avec l'addition et la multiplication.",
                  'Nombres premiers : définition ; tout entier n ≥ 2 admet un diviseur premier ; test de primalité par les diviseurs premiers inférieurs ou égaux à √n ; infinité des nombres premiers.',
                  "Décomposition d'un entier en produit de facteurs premiers (déjà vue en Tronc commun dans ℕ). (à vérifier)",
                  'PGCD et PPCM de deux entiers : définitions et propriétés.',
                  "Algorithme d'Euclide. (à vérifier)",
              ],
              vu_plus_tard=[
                  'Théorèmes de Bézout, de Gauss et de Fermat, équation ax + by = c, numération en base b, ℤ/nℤ (à vérifier).',
              ]),
    _chapitre("Vecteurs de l'espace", 'Géométrie',
              titre_officiel='Vecteurs de l’espace',
              periode='Trimestre 2',
              theoremes=[
                  'Vecteurs coplanaires',
                  "Base de l'espace et coordonnées",
              ],
              statut='inchangé',
              reperes=[
                  "Extension de la notion de vecteur à l'espace : égalité, somme, relation de Chasles, multiplication par un réel.",
                  "Vecteurs colinéaires ; caractérisation vectorielle d'une droite (un point et un vecteur directeur).",
                  "Vecteurs coplanaires et critère de coplanarité ; caractérisation vectorielle d'un plan (un point et deux vecteurs non colinéaires).",
                  "Base et repère de l'espace ; décomposition d'un vecteur dans une base ; coordonnées d'un vecteur et d'un point.",
                  "Applications : alignement et coplanarité de points ; caractérisation vectorielle du parallélisme (d'une droite et d'un plan, de deux plans).",
              ]),
    _chapitre("Géométrie analytique de l'espace", 'Géométrie',
              titre_officiel='Analytique de l’espace',
              periode='Trimestre 2',
              aussi=[
                  "géométrie dans l'espace",
              ],
              theoremes=[
                  "Représentation paramétrique d'une droite",
                  "Équation cartésienne d'un plan",
              ],
              statut='scindé',
              reperes=[
                  "Repère de l'espace ; coordonnées d'un point, d'un vecteur, du milieu d'un segment ; coordonnées de u + v et de k·u.",
                  "Condition analytique de colinéarité de deux vecteurs (déterminants extraits d'ordre 2).",
                  'Déterminant de trois vecteurs ; condition de coplanarité (déterminant nul).',
                  "Représentation paramétrique d'une droite ; système d'équations cartésiennes d'une droite.",
                  "Représentation paramétrique d'un plan ; équation cartésienne d'un plan ax + by + cz + d = 0.",
                  'Étude analytique des positions relatives et des intersections : deux droites, une droite et un plan, deux plans.',
              ],
              remarque="Nouveau chapitre issu de « Géométrie dans l'espace » (partagé avec le Tronc commun) : titre officiel « Analytique de l'espace » (repère, représentations paramétriques, équations cartésiennes), alors que le Tronc commun fait la géométrie de l'espace sans repère."),
    _chapitre("Produit scalaire dans l'espace", 'Géométrie',
              titre_officiel='Analytique du produit scalaire dans l’espace et ses applications – la sphère',
              periode='Trimestre 2',
              theoremes=[
                  "Vecteur normal et équation d'un plan",
                  "Équation d'une sphère",
                  "Distance d'un point à un plan",
                  "Positions relatives d'une sphère et d'un plan ou d'une droite",
              ],
              contenus=[
                  "Étude analytique du produit scalaire dans l'espace (d'après le titre)",
                  "Applications du produit scalaire dans l'espace (d'après le titre)",
                  'La sphère (citée explicitement dans le titre)',
              ],
              statut='inchangé',
              reperes=[
                  "Produit scalaire de deux vecteurs de l'espace (défini dans un plan qui les contient) ; propriétés (symétrie, bilinéarité) ; orthogonalité de deux vecteurs.",
                  "Base et repère orthonormés ; expression analytique du produit scalaire ; norme d'un vecteur ; distance entre deux points.",
                  "Vecteur normal à un plan ; équation cartésienne d'un plan défini par un point et un vecteur normal.",
                  'Droite orthogonale à un plan ; plans perpendiculaires.',
                  "Distance d'un point à un plan : |ax₀ + by₀ + cz₀ + d| / √(a² + b² + c²).",
                  "Sphère : définition, équation cartésienne (centre et rayon) ; sphère de diamètre [AB] (MA→·MB→ = 0) ; étude de l'ensemble des points M(x, y, z) tels que x² + y² + z² + ax + by + cz + d = 0.",
                  "Représentation paramétrique d'une sphère. (à vérifier)",
                  "Position relative d'une sphère et d'un plan (cercle d'intersection, plan tangent, intersection vide) ; position relative d'une sphère et d'une droite.",
              ],
              remarque='Partagé avec le 2ème Bac PC (même contenu, sphère comprise).'),
    _chapitre('Produit vectoriel', 'Géométrie',
              titre_officiel='Le produit vectoriel dans l’espace',
              periode='Trimestre 2',
              theoremes=[
                  'Expression analytique du produit vectoriel',
                  "Distance d'un point à une droite dans l'espace",
              ],
              statut='nouveau',
              reperes=[
                  "Orientation de l'espace : base et repère orthonormés directs (règle du bonhomme d'Ampère, de la main droite).",
                  'Définition du produit vectoriel u ∧ v (direction, sens, norme ‖u‖·‖v‖·|sin θ|).',
                  'Propriétés : antisymétrie, bilinéarité ; u ∧ v = 0⃗ si et seulement si u et v sont colinéaires.',
                  'Expression analytique du produit vectoriel dans une base orthonormée directe.',
                  "Applications : vecteur normal au plan (ABC) et équation de ce plan ; aire d'un triangle (½‖AB→ ∧ AC→‖) et d'un parallélogramme ; distance d'un point à une droite de l'espace (‖AM→ ∧ u‖ / ‖u‖) ; direction de la droite d'intersection de deux plans.",
              ],
              remarque="Chapitre existant du 2ème Bac PC, rattaché à la 1ère Bac SM (absent jusqu'ici) ; même contenu."),
]

# ── 2ème Bac SM — ordre : progression d'enseignant (repère, non officielle)
_SM2 = [
    _chapitre('Limites et continuité', 'Analyse',
              titre_officiel='« Limites et continuité (16h) » (partition p.1) ; « ch1 : limites et continuité » (p.3) ; Cadres 2015 : « Deuxième sous-domaine : limite et continuité » (§1.2)',
              periode='Trimestre 1 (semaines 1 à 3)',
              heures=16,
              capacites=[
                  "Étudier la continuité d'une fonction numérique en un point en utilisant le calcul des limites (1.2.1).",
                  "Étudier la continuité d'une fonction sur un intervalle en utilisant la continuité des fonctions usuelles, les propriétés des opérations sur les fonctions continues et la composée de deux fonctions continues (1.2.2).",
                  "Déterminer l'image d'un intervalle ou d'un segment par une fonction continue (1.2.3).",
                  "Appliquer le théorème des valeurs intermédiaires pour prouver l'existence de solutions de certaines équations ou pour étudier le signe de certaines expressions (1.2.4).",
                  'Utiliser la méthode de dichotomie (1.2.5).',
                  "Déterminer la fonction réciproque d'une fonction continue et strictement monotone sur un intervalle (1.2.6).",
                  'Appliquer le théorème de la fonction réciproque : existence, continuité, variations et représentation graphique de la fonction réciproque (1.2.7).',
              ],
              hors_programme=[
                  'Théorème de Bolzano-Weierstrass : hors programme.',
              ],
              theoremes=[
                  'Théorème des gendarmes',
                  'Théorème des valeurs intermédiaires (TVI)',
                  'Théorème de la bijection',
                  "Image d'un intervalle par une fonction continue",
                  'Continuité de la fonction réciproque',
                  'Prolongement par continuité',
                  "Limite et continuité d'une fonction composée",
                  'Fonction arc tangente',
                  'Fonction racine n-ième et puissance rationnelle',
                  'Méthode de dichotomie',
              ],
              contenus=[
                  "Continuité d'une fonction numérique en un point, étudiée par le calcul des limites",
                  'Continuité sur un intervalle : continuité des fonctions usuelles, opérations sur les fonctions continues, continuité de la composée de deux fonctions continues',
                  "Image d'un intervalle ou d'un segment par une fonction continue",
                  'Théorème des valeurs intermédiaires : existence de solutions de certaines équations, signe de certaines expressions',
                  'Méthode de dichotomie',
                  "Fonction réciproque (bijection réciproque) d'une fonction continue et strictement monotone sur un intervalle",
                  'Théorème de la fonction réciproque : existence, continuité, sens de variation et représentation graphique de la fonction réciproque',
              ],
              statut='inchangé',
              sources=[
                  "Bolzano-Weierstrass absent des Cadres 2015 (SM et PC) ; théorème supprimé, ses étiquettes vont à « Image d'un intervalle par une fonction continue ».",
                  "Déterminer l'image d'un intervalle ou d'un segment par une f… : la partition dit seulement « d'un intervalle »",
                  "Déterminer la fonction réciproque d'une fonction continue et… : « bijection réciproque » dans la partition",
                  'Appliquer le théorème de la fonction réciproque : existence,… : « th de la bijection réciproque (existence - continuité - variation - courbe) » dans la partition',
              ]),
    _chapitre('Suites numériques', 'Analyse',
              titre_officiel='« Les suites numériques (14h) » (partition p.1) ; « ch2 : les suies [sic] numériques » (p.3) ; Cadres 2015 : « Premier sous-domaine : Suites numériques » (§1.1)',
              periode='Trimestre 1 (semaines 3 à 5)',
              heures=14,
              capacites=[
                  "Utiliser les suites géométriques et les suites arithmétiques dans l'étude de suites récurrentes (1.1.1).",
                  'Utiliser les limites des suites de référence, les critères de convergence et la notion de suites adjacentes pour déterminer les limites de suites numériques (1.1.2).',
                  "Étudier la limite de la composée d'une suite et d'une fonction continue, c'est-à-dire d'une suite de la forme (f(uₙ))ₙ (1.1.3).",
                  'Étudier la limite des suites de la forme uₙ₊₁ = f(uₙ), où f est une fonction continue sur un intervalle I vérifiant f(I) ⊂ I (1.1.4).',
                  'Utiliser les suites pour résoudre des problèmes variés issus de différents domaines (1.1.5).',
              ],
              perimetre=[
                  "Suites récurrentes : uₙ₊₁ = f(uₙ) avec f continue sur un intervalle I et f(I) ⊂ I (1.1.4). Le théorème et l'inégalité des accroissements finis s'y appliquent (1.3.17).",
              ],
              theoremes=[
                  'Convergence et divergence',
                  'Suites arithmétiques et géométriques',
                  'Suite monotone et bornée : convergence',
                  'Suites adjacentes',
                  'Suites récurrentes u(n+1) = f(u(n))',
                  'Théorème des gendarmes',
                  'Raisonnement par récurrence',
              ],
              contenus=[
                  'Suites arithmétiques et suites géométriques, utilisées pour étudier des suites récurrentes',
                  'Limites des suites de référence (suites usuelles)',
                  'Critères de convergence',
                  'Suites adjacentes',
                  "Limite de la composée d'une suite et d'une fonction continue : suites de la forme (f(uₙ))ₙ",
                  'Suites récurrentes uₙ₊₁ = f(uₙ), où f est continue sur un intervalle I avec f(I) ⊂ I',
                  'Utilisation des suites pour résoudre des problèmes variés issus de différents domaines',
              ],
              statut='inchangé',
              sources=[
                  'Périmètre lu dans la formulation de 1.1.4 ; renvoi à 1.3.17 (Cadres 2015).',
              ]),
    _chapitre('Dérivation et étude des fonctions', 'Analyse',
              titre_officiel='« La dérivation et th des A. F (16h) » (partition p.1) ; « ch3 : la dérivation et le th des A.F » (p.3) ; Cadres 2015 : « Troisième sous-domaine : Dérivation et étude de fonctions » (§1.3.1-1.3.7 pour ce chapitre) ; + §1.3.16 (étude de fonctions) et §1.3.17 (Rolle, accroissements finis)',
              periode='Trimestre 1 (semaines 5 à 8)',
              heures=16,
              capacites=[
                  "Étudier la dérivabilité d'une fonction numérique en un point (1.3.1).",
                  "Étudier la dérivabilité d'une fonction numérique sur un intervalle en utilisant la dérivabilité des fonctions usuelles, les propriétés des opérations sur les fonctions dérivables et la composée de deux fonctions dérivables (1.3.2).",
                  "Déterminer la monotonie d'une fonction (1.3.3).",
                  "Déterminer le signe d'une fonction à partir de son tableau de variations (1.3.4).",
                  "Déterminer le signe d'une fonction à partir de sa représentation graphique (1.3.5).",
                  'Utiliser la dérivée première et la dérivée seconde pour étudier une fonction numérique et pour prouver certaines inégalités (1.3.6).',
                  "Étudier la dérivabilité et déterminer la dérivée de la fonction réciproque d'une fonction continue et strictement monotone sur un intervalle (1.3.7).",
                  "Étudier des fonctions ou des fonctions composées parmi les fonctions figurant au programme et les représenter graphiquement : ensemble de définition, continuité, éléments de symétrie, périodicité, monotonie, branches infinies, tangentes, concavité, points d'inflexion… (1.3.16).",
                  "Appliquer le théorème de Rolle, le théorème des accroissements finis et l'inégalité des accroissements finis dans l'étude de suites numériques du type uₙ₊₁ = f(uₙ) ou dans l'encadrement d'expressions, de formules algébriques, de nombres réels et d'intégrales… (1.3.17).",
              ],
              aussi=[
                  'théorème des accroissements finis (TAF)',
              ],
              theoremes=[
                  'Théorème de Rolle',
                  'Théorème des accroissements finis (TAF)',
                  'Inégalité des accroissements finis',
                  "Dérivée d'une fonction composée",
                  'Dérivée de la fonction réciproque',
                  "Concavité et point d'inflexion",
                  'Branches infinies et asymptotes',
              ],
              contenus=[
                  "Dérivabilité d'une fonction numérique en un point",
                  'Dérivabilité sur un intervalle : dérivabilité des fonctions usuelles, opérations sur les fonctions dérivables, dérivabilité de la composée de deux fonctions dérivables',
                  "Sens de variation (monotonie) d'une fonction",
                  "Signe d'une fonction à partir de son tableau de variations ou de sa représentation graphique",
                  "Dérivée première et dérivée seconde : étude d'une fonction numérique, preuve d'inégalités",
                  "Dérivabilité et dérivée de la fonction réciproque d'une fonction continue et strictement monotone sur un intervalle",
                  "Théorème des accroissements finis, nommé dans le titre du chapitre (ses applications, avec le théorème de Rolle et l'inégalité des accroissements finis, sont listées au ch5, capacité 9 = Cadres 1.3.17)",
                  "Étude et représentation graphique de fonctions et de fonctions composées du programme : ensemble de définition, continuité, éléments de symétrie, périodicité, monotonie, branches infinies, tangentes, concavité, points d'inflexion…",
                  "Applications du théorème de Rolle, du théorème des accroissements finis et de l'inégalité des accroissements finis : suites uₙ₊₁ = f(uₙ), inégalités, encadrements",
              ],
              statut='fusionné',
              sources=[
                  "Étudier la dérivabilité d'une fonction numérique sur un inte… : (« fonctions dérivées » dans les Cadres)",
                  'Utiliser la dérivée première et la dérivée seconde pour étud… : la partition dit seulement « utiliser la dérivation pour prouver des inégalités »',
                  'Appliquer le théorème de Rolle, le théorème des accroissemen… : la partition dit « pour prouver des inégalités et établir des encadrements »',
              ],
              remarque='Nom actuel gardé (= sous-domaine « Dérivation et étude de fonctions » des Cadres ; partagé avec le PC). Absorbe le chapitre « Théorème des Accroissements Finis (TAF) », qui est un théorème du chapitre (titre officiel « La dérivation et th des A.F »). Les capacités 1.3.16-1.3.17, rangées au ch5 par la partition, sont générales au sous-domaine : elles sont rattachées ici, où vivent Rolle et le TAF.'),
    _chapitre('Fonctions primitives', 'Analyse',
              titre_officiel='« Les primitives (5h) » (partition p.1) ; « ch4 : les primitives » (p.3) ; Cadres 2015 : §1.3.8, dans le sous-domaine « Dérivation et étude de fonctions »',
              periode='Trimestre 1 (semaine 8)',
              heures=5,
              capacites=[
                  "Utiliser les formules de dérivation pour déterminer les fonctions primitives d'une fonction continue sur un intervalle (1.3.8).",
              ],
              theoremes=[
                  'Primitives des fonctions usuelles',
                  "Primitive d'une fonction continue sur un intervalle",
              ],
              contenus=[
                  "Primitives d'une fonction continue sur un intervalle, déterminées à l'aide des formules de dérivation",
              ],
              statut='nouveau',
              remarque='Chapitre existant du 2ème Bac PC rattaché au 2ème Bac SM : la partition en fait un chapitre (ch4, 5 h).'),
    _chapitre('Fonctions logarithmiques', 'Analyse',
              titre_officiel='« Les fonctions logarithmes et les fonctions exponentielles (20h) » (ch5, partie logarithmes) ; Cadres §1.3.9-1.3.11',
              periode='Trimestre 1 (semaines 9 à 12)',
              capacites=[
                  'Maîtriser le calcul sur les logarithmes (1.3.9).',
                  'Résoudre des équations, des inéquations et des systèmes logarithmiques (1.3.10).',
                  'Utiliser les limites logarithmiques de base (1.3.11).',
                  '(1.3.16) Étudier et représenter des fonctions faisant intervenir ln.',
              ],
              theoremes=[
                  'Dérivée et propriétés du logarithme',
                  'Limites usuelles du logarithme',
                  'Fonction logarithme de base a',
                  'Logarithme décimal',
              ],
              contenus=[
                  'Calcul sur les logarithmes',
                  'Équations, inéquations et systèmes logarithmiques',
                  'Limites logarithmiques de base (« remarquables »)',
              ],
              statut='inchangé',
              sources=[
                  'Utiliser les limites logarithmiques de base (1.3.11).… : « limites logarithmiques remarquables » dans la partition',
              ],
              remarque='Le document fait un seul chapitre de 20 h « logarithmes et exponentielles » ; gardé en deux chapitres (voir principes) : 20 h pour les deux, sans répartition donnée. Logarithme décimal : cas particulier du logarithme de base a, théorème rattaché ici aussi.'),
    _chapitre('Fonctions exponentielles', 'Analyse',
              titre_officiel='« Les fonctions logarithmes et les fonctions exponentielles (20h) » (ch5, partie exponentielles) ; Cadres §1.3.12-1.3.15',
              periode='Trimestre 1 (semaines 9 à 12)',
              capacites=[
                  'Maîtriser le calcul exponentiel à base donnée (1.3.12).',
                  'Résoudre des équations, des inéquations et des systèmes exponentiels (1.3.13).',
                  'Utiliser les limites de base de la fonction exponentielle népérienne (1.3.14).',
                  'Maîtriser le calcul sur les puissances réelles (1.3.15).',
                  '(1.3.16) Étudier et représenter des fonctions faisant intervenir exp.',
              ],
              theoremes=[
                  "Dérivée et propriétés de l'exponentielle",
                  "Limites usuelles de l'exponentielle",
                  'Fonction exponentielle de base a',
              ],
              contenus=[
                  'Calcul exponentiel à base donnée',
                  'Équations, inéquations et systèmes exponentiels',
                  'Limites de base de la fonction exponentielle népérienne',
                  'Puissances à exposant réel',
              ],
              statut='inchangé',
              sources=[
                  'Maîtriser le calcul sur les puissances réelles (1.3.15).… : « puissances à exposant réel » dans la partition',
              ],
              remarque='Voir « Fonctions logarithmiques » : 20 h pour les deux chapitres.'),
    _chapitre('Équations différentielles', 'Analyse',
              titre_officiel='« Les équations différentielles (6h) » (partition p.1) ; « ch6 : les équations différentielles » (p.4) ; Cadres 2015 : §1.3.18-1.3.20',
              periode='Trimestre 1 (semaines 12 à 13)',
              heures=6,
              capacites=[
                  "Résoudre l'équation différentielle y' = ay + b (1.3.18).",
                  "Résoudre l'équation différentielle y'' + ay' + by = 0 (1.3.19).",
                  "Résoudre des équations différentielles dont la résolution se ramène à l'une des équations différentielles y' = ay + b ou y'' + ay' + by = 0 (1.3.20).",
              ],
              hors_programme=[
                  "Méthode de variation de la constante : hors programme ; une équation avec second membre se ramène à y' = ay + b ou à y'' + ay' + by = 0 (1.3.20).",
              ],
              perimetre=[
                  "Équations y' = ay + b, y'' + ay' + by = 0 et celles qui s'y ramènent (1.3.18 à 1.3.20).",
              ],
              theoremes=[
                  "Équation y' = ay + b",
                  "Équation y'' + ay' + by = 0",
              ],
              contenus=[
                  "Équation différentielle y' = ay + b",
                  "Équation différentielle y'' + ay' + by = 0",
                  "Équations différentielles dont la résolution se ramène à y' = ay + b ou à y'' + ay' + by = 0",
              ],
              statut='inchangé',
              sources=[
                  "Variation de la constante absente des Cadres 2015 ; théorème fusionné dans « Équation y' = ay + b ».",
              ]),
    _chapitre('Nombres complexes', 'Algèbre',
              titre_officiel='« Les nombres complexes (24h) » (partition p.1) ; « ch7 : les complexes » (p.4) ; Cadres 2015 : « Deuxième sous-domaine : Les nombres complexes » (§2.2, domaine Algèbre et géométrie)',
              periode='Trimestre 1 (semaines 13 à 17)',
              heures=24,
              capacites=[
                  'Maîtriser le calcul algébrique sur les nombres complexes dans chacune de leurs écritures : algébrique, trigonométrique et exponentielle (2.2.1).',
                  "Traduire, à l'aide de l'outil complexe, les concepts géométriques suivants : distance de deux points, mesure d'angles, barycentre, alignement de points, colinéarité et orthogonalité de vecteurs, cocyclicité de quatre points… (2.2.2).",
                  'Interpréter géométriquement des expressions complexes (2.2.3).',
                  'Utiliser les nombres complexes dans le calcul trigonométrique : formules de transformation, linéarisation et développement (2.2.4).',
                  'Résoudre une équation du deuxième degré à une inconnue (2.2.5).',
                  "Résoudre des équations dont la résolution se ramène à celle d'une équation du deuxième degré à une inconnue (2.2.6).",
                  "Résoudre des équations du type zⁿ = a et reconnaître l'interprétation géométrique de l'ensemble de leurs solutions (2.2.7).",
                  "Déterminer les expressions complexes des transformations usuelles et de leurs composées : composée de deux rotations, d'une rotation et d'une translation, d'une homothétie et d'une translation, d'une rotation et d'une homothétie (2.2.8).",
                  'Utiliser les expressions complexes des transformations usuelles pour étudier des situations géométriques (2.2.9).',
                  'Utiliser les nombres complexes dans la résolution de problèmes géométriques (2.2.10).',
              ],
              theoremes=[
                  'Forme trigonométrique et exponentielle',
                  'Formule de Moivre',
                  "Formules d'Euler",
                  "Racines n-ièmes d'un nombre complexe",
                  'Équations du second degré dans ℂ',
                  'Transformations du plan : translation, homothétie, rotation',
                  'Formule du binôme de Newton',
              ],
              contenus=[
                  'Calcul algébrique sur les nombres complexes dans chacune de leurs écritures : algébrique, trigonométrique et exponentielle',
                  "Traduction complexe de notions géométriques : distance de deux points, mesure d'angles, barycentre, alignement de points, colinéarité et orthogonalité de vecteurs, cocyclicité de quatre points…",
                  "Interprétation géométrique d'expressions complexes",
                  'Nombres complexes et calcul trigonométrique : formules de transformation, linéarisation, développement (« factorisation » dans la partition)',
                  "Équation du second degré à une inconnue et équations qui s'y ramènent",
                  "Équations du type zⁿ = a et interprétation géométrique de l'ensemble des solutions",
                  'Écriture complexe des transformations usuelles et de leurs composées : deux rotations, une rotation et une translation, une homothétie et une translation, une rotation et une homothétie',
                  'Utilisation des nombres complexes pour étudier des situations géométriques et résoudre des problèmes géométriques',
              ],
              statut='inchangé',
              sources=[
                  'Utiliser les nombres complexes dans le calcul trigonométriqu… : la partition écrit « linéarisation, factorisation »',
                  'Déterminer les expressions complexes des transformations usu… : la partition, item 7, ne cite pas les composées',
              ],
              remarque='Formule du binôme de Newton rattachée ici aussi (développement, 2.2.4).'),
    _chapitre('Calcul intégral', 'Analyse',
              titre_officiel='« calcul intégral (24h) » (partition p.2) ; « ch8 : les intégrales » (p.4) ; Cadres 2015 : « Quatrième sous-domaine : Calcul intégral » (§1.4)',
              periode='Trimestre 2 (semaines 1 à 4)',
              heures=24,
              capacites=[
                  "Utiliser les techniques du calcul intégral pour calculer l'intégrale d'une fonction continue sur un segment (1.4.1).",
                  "Maîtriser le calcul de l'aire d'un domaine du plan limité par deux courbes (1.4.2).",
                  "Maîtriser le calcul du volume d'un solide de révolution engendré par la rotation de la courbe d'une fonction continue autour de l'un des deux axes du repère (1.4.3).",
                  'Appliquer le calcul intégral pour prouver certaines inégalités, calculer certaines limites et donner des approximations… (1.4.4).',
                  'Étudier des fonctions composées de la forme x ↦ ∫ₐ^u(x) f(t) dt (1.4.5).',
                  'Déterminer la limite de chacune des deux suites uₙ = ((b − a)/n) Σ_{k=1}^{n} f(a + k(b − a)/n) et vₙ = ((b − a)/n) Σ_{k=0}^{n−1} f(a + k(b − a)/n), où f est une fonction continue sur le segment [a, b] (1.4.6).',
                  'Étudier des fonctions et des suites définies par une intégrale (1.4.7).',
              ],
              perimetre=[
                  'Sommes de Riemann : à travers les deux suites uₙ et vₙ de pas (b − a)/n, f continue sur [a, b] (1.4.6).',
              ],
              theoremes=[
                  "Théorème fondamental de l'analyse",
                  "Primitives et techniques d'intégration",
                  'Intégration par parties',
                  "Valeur moyenne d'une fonction",
                  "Calcul d'aires et de volumes",
                  'Sommes de Riemann',
              ],
              contenus=[
                  "Intégrale d'une fonction continue sur un segment et techniques du calcul intégral",
                  "Aire d'un domaine du plan limité par deux courbes",
                  "Volume d'un solide de révolution engendré par la rotation de la courbe d'une fonction continue autour de l'un des deux axes du repère",
                  'Applications : prouver des inégalités, calculer des limites, donner des approximations',
                  'Fonctions composées de la forme x ↦ ∫ₐ^u(x) f(t) dt',
                  'Limites des suites uₙ = ((b − a)/n) Σ_{k=1}^{n} f(a + k(b − a)/n) et vₙ = ((b − a)/n) Σ_{k=0}^{n−1} f(a + k(b − a)/n), f continue sur [a, b] (sommes de Riemann)',
                  'Fonctions et suites définies par une intégrale',
              ],
              statut='inchangé'),
    _chapitre('Arithmétique', 'Algèbre',
              titre_officiel="« l'arithmétique (20h) » (partition p.2) ; « ch9 : l'arithmétique » (p.4-5) ; Cadres 2015 : « Premier sous-domaine : Arithmétique » (§2.1, domaine Algèbre et géométrie)",
              periode='Trimestre 2 (semaines 4 à 7)',
              heures=20,
              capacites=[
                  'Utiliser la décomposition en produit de facteurs premiers pour déterminer le plus petit multiple commun et le plus grand diviseur commun de deux ou plusieurs entiers (2.1.1).',
                  "Utiliser la décomposition en produit de facteurs premiers pour déterminer les diviseurs d'un entier (2.1.2).",
                  "Utiliser l'algorithme d'Euclide pour déterminer le plus grand diviseur commun de deux entiers et les coefficients de Bézout dans l'écriture a ∧ b = au + bv (2.1.3).",
                  'Écrire un entier naturel dans un système de numération de base donnée (2.1.4).',
                  'Additionner, multiplier et comparer deux entiers dans un système de numération de base donnée (2.1.5).',
                  "Utiliser les écritures dans des systèmes de numération dans des situations d'arithmétique (2.1.6).",
                  "Utiliser la congruence modulo n, les propriétés des opérations dans ℤ/nℤ et la structure de (ℤ/nℤ, +, ×) dans des situations d'arithmétique (2.1.7).",
                  "Utiliser la divisibilité, la division euclidienne, les théorèmes de Gauss, de Bézout et de Fermat, le théorème fondamental et les propriétés des nombres premiers et des nombres premiers entre eux dans des situations d'arithmétique (2.1.8).",
                  "Résoudre l'équation ax + by = c dans ℤ × ℤ (2.1.9).",
              ],
              theoremes=[
                  'Théorème de Bézout',
                  'Théorème de Gauss',
                  'Petit théorème de Fermat',
                  'Division euclidienne et congruences',
                  "PGCD, PPCM et algorithme d'Euclide",
                  'Décomposition en facteurs premiers',
                  'Numération dans une base donnée',
                  'Structure de (ℤ/nℤ, +, ×)',
              ],
              contenus=[
                  'Décomposition en produit de facteurs premiers : PGCD et PPCM de deux ou plusieurs entiers',
                  "Diviseurs d'un entier et nombre de ses diviseurs positifs",
                  "Algorithme d'Euclide ; coefficients de Bézout dans l'écriture a ∧ b = au + bv",
                  "Systèmes de numération de base donnée : écriture d'un entier naturel ; addition, multiplication et comparaison de deux entiers ; utilisation en arithmétique",
                  'Congruence modulo n, opérations dans ℤ/nℤ, structure de (ℤ/nℤ, +, ×)',
                  "Divisibilité et division euclidienne ; théorèmes de Gauss, de Bézout et de Fermat ; théorème fondamental de l'arithmétique ; propriétés des nombres premiers et des nombres premiers entre eux",
                  'Équation ax + by = c dans ℤ × ℤ',
              ],
              statut='inchangé',
              sources=[
                  "Utiliser la décomposition en produit de facteurs premiers po… : la partition précise : le nombre de diviseurs positifs d'un entier",
              ],
              remarque="Nom actuel gardé (titre officiel « l'arithmétique ») ; distinct de « Arithmétique dans ℤ » (1ère)."),
    _chapitre('Structures algébriques', 'Algèbre',
              titre_officiel='« Les structures (30h) » (partition p.2) ; « ch10 : les structures » (p.5) ; Cadres 2015 : « Quatrième sous-domaine : Structures algébriques » (§2.4)',
              periode='Trimestre 2 (semaines 8 à 13)',
              heures=30,
              capacites=[
                  'Reconnaître une loi de composition interne et ses propriétés (2.4.1).',
                  'Reconnaître les structures algébriques figurant au programme : groupe, anneau, corps et espace vectoriel (2.4.2).',
                  'Maîtriser les techniques de calcul dans les ensembles usuels et dans les diverses structures algébriques figurant au programme (2.4.3).',
                  "Utiliser les structures algébriques des ensembles usuels dans l'étude des structures d'autres ensembles (2.4.4).",
                  "Transférer la structure algébrique d'un ensemble muni d'une loi de composition interne vers un autre ensemble muni d'une loi de composition interne, à l'aide des notions d'homomorphisme et d'isomorphisme (2.4.5).",
                  "Utiliser la propriété caractéristique d'un sous-groupe (2.4.6).",
              ],
              perimetre=[
                  "Matrices carrées d'ordre 2 et 3 comme ensembles de référence.",
              ],
              theoremes=[
                  'Lois de composition interne',
                  'Groupes, anneaux et corps',
                  'Sous-groupes et morphismes de groupes',
                  'Transfert de structure par un morphisme',
                  "Matrices carrées d'ordre 2 et 3",
              ],
              contenus=[
                  'Loi de composition interne et ses propriétés',
                  'Structures algébriques au programme : groupe, anneau, corps et espace vectoriel réel',
                  'Calcul dans les ensembles usuels et dans les structures algébriques du programme',
                  "Étude de la structure d'autres ensembles à l'aide des structures des ensembles usuels",
                  "Homomorphisme et isomorphisme : transfert de la structure d'un ensemble muni d'une loi de composition interne vers un autre",
                  "Propriété caractéristique d'un sous-groupe",
              ],
              statut='inchangé',
              sources=[
                  "Théorèmes « Applications linéaires et matrices » et « Définition et propriétés des groupes, anneaux et corps » renommés.",
                  'Reconnaître une loi de composition interne et ses propriétés… : absente de la partition',
                  'Reconnaître les structures algébriques figurant au programme… : absente de la partition',
              ],
              remarque="Première partie du chapitre officiel « Les structures » (30 h, toutes comptées ici) ; la partie espace vectoriel (2.4.6 pour les sous-espaces, 2.4.7, 2.4.8) est le chapitre « Espaces vectoriels », gardé à part (décision du propriétaire du 11/10/2026)."),
    _chapitre('Espaces vectoriels', 'Algèbre',
              titre_officiel='« Les structures (30h) », items 5-6 (partition p.2 ; « ch10 : les structures » p.5) ; Cadres 2015 §2.4.6-2.4.8',
              periode='Trimestre 2 (semaines 8 à 13)',
              capacites=[
                  "Utiliser la propriété caractéristique d'un sous-espace vectoriel (2.4.6).",
                  'Reconnaître une famille libre, une famille génératrice et une base dans un espace vectoriel réel donné (2.4.7).',
                  "Déterminer les composantes (coordonnées) d'un vecteur dans une base donnée d'un espace vectoriel (2.4.8).",
              ],
              hors_programme=[
                  'Applications linéaires étudiées pour elles-mêmes, produit scalaire abstrait : hors programme.',
              ],
              perimetre=[
                  "Espaces vectoriels réels (2.4.7) ; matrices carrées d'ordre 2 et 3 comme ensembles de référence.",
              ],
              theoremes=[
                  'Sous-espaces vectoriels',
                  'Familles libres et génératrices',
                  "Base et dimension d'un espace vectoriel",
              ],
              contenus=[
                  "Propriété caractéristique d'un sous-espace vectoriel",
                  "Famille libre, famille génératrice, base d'un espace vectoriel réel",
                  "Composantes (coordonnées) d'un vecteur dans une base",
              ],
              statut='inchangé',
              sources=[
                  'Applications linéaires et produit scalaire abstrait absents des Cadres 2015 §2.4 ; théorème « Produit scalaire et propriétés » supprimé.',
              ],
              remarque="Gardé comme chapitre à part (décision du propriétaire du 11/10/2026) ; le programme en fait la seconde partie du chapitre « Les structures » (30 h, comptées sur « Structures algébriques »)."),
    _chapitre('Probabilités', 'Probabilités',
              titre_officiel='« Les probabilités (20h) » (partition p.2) ; « ch11 : les probabilités » (p.5) ; Cadres 2015 : « Troisième sous-domaine : Calcul des probabilités » (§2.3)',
              periode='Trimestre 2 (semaines 13 à 16)',
              heures=20,
              capacites=[
                  'Utiliser le modèle combinatoire adéquat suivant la situation étudiée (2.3.1).',
                  "Calculer la probabilité de la réunion de deux événements, la probabilité de l'événement contraire d'un événement et la probabilité de l'intersection de deux événements (2.3.2).",
                  "Calculer la probabilité conditionnelle et l'utiliser pour déterminer la probabilité de l'intersection de deux événements (2.3.3).",
                  "Reconnaître l'indépendance de deux événements (2.3.4).",
                  "Déterminer la loi de probabilité d'une variable aléatoire et calculer ses divers paramètres (2.3.5).",
                  'Déterminer et représenter la fonction de répartition (2.3.6).',
                  "Reconnaître la loi binomiale et l'appliquer dans des situations probabilistes (2.3.7).",
              ],
              hors_programme=[
                  'Loi des grands nombres, théorème central limite : hors programme.',
              ],
              aussi=[
                  'dénombrement',
              ],
              theoremes=[
                  'Arrangements et combinaisons',
                  'Formule du binôme de Newton',
                  'Probabilité conditionnelle',
                  'Formule des probabilités totales',
                  "Indépendance d'événements",
                  'Variable aléatoire : espérance et variance',
                  'Loi binomiale',
                  'Fonction de répartition',
              ],
              contenus=[
                  'Modèle combinatoire (dénombrement) adapté à la situation étudiée',
                  "Probabilité de la réunion de deux événements, de l'événement contraire et de l'intersection de deux événements",
                  "Probabilité conditionnelle ; probabilité de l'intersection de deux événements",
                  'Indépendance de deux événements',
                  'Variable aléatoire : loi de probabilité et paramètres',
                  'Fonction de répartition : détermination et représentation',
                  'Loi binomiale',
              ],
              statut='fusionné',
              sources=[
                  'Absents des Cadres 2015 SM et PC ; théorèmes supprimés sans remplaçant.',
                  'Utiliser le modèle combinatoire adéquat suivant la situation… : « modèle de dénombrement convenable » dans la partition',
              ],
              remarque="Nom actuel gardé (partagé avec le PC). Le dénombrement n'est pas un chapitre de 2ème Bac SM (c'est un chapitre de 1ère) : il y sert d'outil (capacité 2.3.1, « utiliser le modèle combinatoire adéquat »). Ce chapitre reçoit donc les contenus de 2ème Bac SM rangés dans « Dénombrement », détaché de ce niveau (voir question ouverte)."),
]

# ── 2ème Bac PC/SVT — ordre : progression usuelle (repère, non officielle ; le cadre n'en donne pas)
_PC = [
    _chapitre('Limites et continuité', 'Analyse',
              titre_officiel='Deuxième sous-domaine : Continuité, dérivation et étude de fonctions (items 1.2.1 à 1.2.4, et la partie « monotonie et représentation graphique » de 1.2.11)',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 1, première leçon',
              capacites=[
                  "1.2.1. Étudier la continuité d'une fonction numérique en un point en utilisant le calcul des limites.",
                  "1.2.2. Déterminer l'image d'un segment ou d'un intervalle par une fonction continue ou par une fonction continue et strictement monotone.",
                  '1.2.3. Appliquer le théorème des valeurs intermédiaires pour étudier certaines équations et inéquations ou pour étudier le signe de certaines expressions...',
                  "1.2.4. Appliquer le théorème des valeurs intermédiaires dans le cas d'une fonction continue et strictement monotone sur un intervalle pour prouver l'unicité de la solution de l'équation f(x) = λ.",
                  "(1.2.11, partie) Déterminer la monotonie de la fonction réciproque d'une fonction continue et strictement monotone sur un intervalle et la représenter graphiquement.",
              ],
              hors_programme=[
                  'Fonction arc tangente : hors programme en 2ème Bac PC/SVT.',
              ],
              theoremes=[
                  'Théorème des gendarmes',
                  'Théorème des valeurs intermédiaires (TVI)',
                  'Théorème de la bijection',
                  "Image d'un intervalle par une fonction continue",
                  'Continuité de la fonction réciproque',
                  'Prolongement par continuité',
                  "Limite et continuité d'une fonction composée",
                  'Fonction racine n-ième et puissance rationnelle',
                  'Méthode de dichotomie',
              ],
              contenus=[
                  "Continuité d'une fonction numérique en un point, étudiée à l'aide du calcul des limites",
                  "Image d'un segment ou d'un intervalle par une fonction continue, ou par une fonction continue et strictement monotone",
                  'Théorème des valeurs intermédiaires : étude de certaines équations et inéquations, et du signe de certaines expressions',
                  "Fonction continue et strictement monotone sur un intervalle : unicité de la solution de l'équation f(x) = λ",
                  "Fonction réciproque d'une fonction continue et strictement monotone sur un intervalle : monotonie et représentation graphique (item 1.2.11 ; la dérivée de la réciproque est traitée en Dérivation)",
              ],
              statut='inchangé',
              sources=[
                  'Connaissance générale : fonction usuelle du seul 2ème Bac SM (non nommée par les Cadres SM) ; absente du cadre PC.',
              ],
              remarque="Ordre : progression BIOF usuelle, le cadre de référence n'en donne pas. Méthode de dichotomie rattachée à ce niveau (programme Sciences expérimentales, à vérifier : absente du cadre PC)."),
    _chapitre('Dérivation et étude des fonctions', 'Analyse',
              titre_officiel='Deuxième sous-domaine : Continuité, dérivation et étude de fonctions (items 1.2.5 à 1.2.13 et 1.2.22)',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 1',
              capacites=[
                  "1.2.5. Étudier la dérivabilité d'une fonction numérique en un point et sur un intervalle.",
                  "1.2.6. Déterminer la fonction dérivée d'une fonction numérique.",
                  "1.2.7. Déterminer la monotonie d'une fonction.",
                  "1.2.8. Déterminer le signe d'une fonction à partir de son tableau de variations.",
                  "1.2.9. Déterminer le signe d'une fonction à partir de sa représentation graphique.",
                  '1.2.10. Résoudre graphiquement des équations de la forme f(x) = g(x) et des inéquations de la forme f(x) ≤ g(x).',
                  "1.2.11. Déterminer la dérivée et la monotonie de la fonction réciproque d'une fonction continue et strictement monotone sur un intervalle et la représenter graphiquement.",
                  "1.2.12. Résoudre des problèmes d'application concernant les valeurs minimales et les valeurs maximales.",
                  "1.2.13. Utiliser la dérivée première et la dérivée seconde pour l'étude d'une fonction numérique et pour prouver certaines inégalités...",
                  "1.2.22. Étudier des fonctions ou des composées de fonctions figurant au programme et les représenter graphiquement (ensemble de définition, éléments de symétrie, périodicité, monotonie, branches infinies, tangentes, concavité, points d'inflexion...).",
              ],
              hors_programme=[
                  'Théorème de Rolle, théorème et inégalité des accroissements finis : hors programme en 2ème Bac PC/SVT.',
              ],
              theoremes=[
                  "Dérivée d'une fonction composée",
                  'Dérivée de la fonction réciproque',
                  "Concavité et point d'inflexion",
                  'Branches infinies et asymptotes',
              ],
              contenus=[
                  "Dérivabilité d'une fonction numérique en un point et sur un intervalle",
                  "Fonction dérivée d'une fonction numérique",
                  "Monotonie d'une fonction",
                  "Signe d'une fonction à partir de son tableau de variations ou de sa représentation graphique",
                  'Résolution graphique des équations f(x) = g(x) et des inéquations f(x) ≤ g(x)',
                  "Dérivée et monotonie de la fonction réciproque d'une fonction continue et strictement monotone sur un intervalle ; représentation graphique de la réciproque",
                  "Problèmes d'application sur les valeurs minimales et maximales (optimisation)",
                  "Dérivée première et dérivée seconde : étude d'une fonction numérique et démonstration de certaines inégalités",
                  "Étude et représentation graphique des fonctions du programme et de leurs composées : ensemble de définition, éléments de symétrie, périodicité, monotonie, branches infinies, tangentes, concavité, points d'inflexion",
              ],
              statut='inchangé',
              sources=[
                  'Cadres SM §1.3.17 ; absents du cadre PC.',
              ]),
    _chapitre('Suites numériques', 'Analyse',
              titre_officiel='Premier sous-domaine : Suites numériques',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 1',
              capacites=[
                  '1.1.1. Utiliser les suites géométriques et les suites arithmétiques pour étudier des exemples de suites de la forme : u_{n+1} = a·u_n + b ou u_{n+1} = (a·u_n + b)/(c·u_n + d).',
                  "1.1.2. Utiliser les limites des suites de référence et les critères de convergence pour déterminer la limite d'une suite numérique.",
                  "1.1.3. Déterminer la limite de la composée d'une suite et d'une fonction continue (suites du type v_n = f(u_n)).",
                  "1.1.4. Étudier la convergence d'une suite (u_n) de la forme u_{n+1} = f(u_n) où f est une fonction continue sur un intervalle I et qui vérifie f(I) ⊂ I, et déterminer sa limite.",
                  '1.1.5. Utiliser les suites pour résoudre des problèmes variés issus de domaines différents.',
              ],
              hors_programme=[
                  'Suites adjacentes : hors programme en 2ème Bac PC/SVT.',
              ],
              perimetre=[
                  'Suites uₙ₊₁ = a·uₙ + b et uₙ₊₁ = (a·uₙ + b)/(c·uₙ + d) étudiées sur des exemples, au moyen de suites arithmétiques ou géométriques auxiliaires (1.1.1).',
                  "Suites uₙ₊₁ = f(uₙ) avec f continue sur un intervalle I et f(I) ⊂ I (1.1.4) ; le raisonnement par récurrence y est l'outil usuel.",
              ],
              theoremes=[
                  'Convergence et divergence',
                  'Suites arithmétiques et géométriques',
                  'Suite monotone et bornée : convergence',
                  'Suites récurrentes u(n+1) = f(u(n))',
                  'Théorème des gendarmes',
                  'Raisonnement par récurrence',
              ],
              contenus=[
                  'Suites arithmétiques et suites géométriques, utilisées pour étudier des exemples de suites de la forme u_{n+1} = a·u_n + b ou u_{n+1} = (a·u_n + b)/(c·u_n + d)',
                  'Limites des suites de référence et critères de convergence',
                  "Limite de la composée d'une suite et d'une fonction continue (suites du type v_n = f(u_n))",
                  "Convergence et limite d'une suite u_{n+1} = f(u_n), où f est continue sur un intervalle I avec f(I) ⊂ I",
                  'Utilisation des suites pour résoudre des problèmes variés issus de domaines différents',
              ],
              statut='inchangé',
              sources=[
                  'Cadres SM §1.1.2 ; absentes du cadre PC.',
              ]),
    _chapitre('Fonctions primitives', 'Analyse',
              titre_officiel='Deuxième sous-domaine : Continuité, dérivation et étude de fonctions (items 1.2.14 et 1.2.15)',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 1, avant les fonctions logarithmiques',
              capacites=[
                  '1.2.14. Déterminer les fonctions primitives des fonctions usuelles.',
                  "1.2.15. Utiliser les formules de dérivation pour déterminer les fonctions primitives d'une fonction sur un intervalle.",
              ],
              theoremes=[
                  'Primitives des fonctions usuelles',
                  "Primitive d'une fonction continue sur un intervalle",
              ],
              contenus=[
                  'Fonctions primitives des fonctions usuelles',
                  "Utilisation des formules de dérivation pour déterminer les fonctions primitives d'une fonction sur un intervalle",
              ],
              statut='inchangé'),
    _chapitre('Fonctions logarithmiques', 'Analyse',
              titre_officiel='Deuxième sous-domaine : Continuité, dérivation et étude de fonctions (items 1.2.16 à 1.2.19, et 1.2.22 appliqué aux logarithmes)',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 1',
              capacites=[
                  '1.2.16. Maîtriser le calcul algébrique sur les logarithmes.',
                  '1.2.17. Maîtriser la résolution des équations, des inéquations et des systèmes logarithmiques.',
                  '1.2.18. Reconnaître et appliquer le logarithme décimal (en particulier pour résoudre des équations du type 10^x = a et des inéquations du type 10^x ≤ a ou 10^x ≥ a).',
                  '1.2.19. Maîtriser les limites logarithmiques de base et les appliquer.',
                  '(1.2.22, appliqué aux logarithmes) Étudier des fonctions ou des composées de fonctions figurant au programme et les représenter graphiquement.',
              ],
              theoremes=[
                  'Dérivée et propriétés du logarithme',
                  'Limites usuelles du logarithme',
                  'Fonction logarithme de base a',
                  'Logarithme décimal',
              ],
              contenus=[
                  'Calcul algébrique sur les logarithmes',
                  'Équations, inéquations et systèmes logarithmiques',
                  'Logarithme décimal, en particulier pour résoudre les équations 10^x = a et les inéquations 10^x ≤ a ou 10^x ≥ a',
                  'Limites logarithmiques de base et leurs applications',
                  'Étude et représentation graphique de fonctions (et de composées) faisant intervenir le logarithme (item 1.2.22)',
              ],
              statut='inchangé',
              remarque='Logarithme décimal nommé par le cadre PC (1.2.18).'),
    _chapitre('Nombres complexes', 'Algèbre',
              titre_officiel='4- Quatrième sous-domaine : Nombres complexes',
              periode='Non donnée par le document (cadre d’examen) ; habituellement partie 1 au Semestre 1 et partie 2 au Semestre 2',
              capacites=[
                  '2.4.1. Maîtriser le calcul algébrique sur les nombres complexes (dans ses différentes écritures : algébrique, trigonométrique et exponentielle).',
                  "2.4.2. Passer de l'écriture algébrique à l'écriture trigonométrique d'un nombre complexe et réciproquement.",
                  "2.4.3. Linéariser des monômes trigonométriques en utilisant l'écriture exponentielle d'un nombre complexe.",
                  "2.4.4. Traduire les notions géométriques suivantes : distance de deux points, mesure des angles, alignement de points, colinéarité et orthogonalité de vecteurs, en utilisant l'outil complexe.",
                  "2.4.5. Exprimer la translation, l'homothétie et la rotation en utilisant l'outil complexe.",
                  '2.4.6. Reconnaître une translation, une homothétie ou une rotation à partir de leurs expressions complexes.',
                  '2.4.7. Utiliser les nombres complexes pour résoudre des problèmes de géométrie (alignement, orthogonalité...).',
                  "2.4.8. Résoudre l'équation az² + bz + c = 0 dans l'ensemble des nombres complexes, où a, b et c sont des nombres réels.",
                  "2.4.9. Résoudre des équations dont la résolution se ramène à la résolution d'une équation du second degré à une seule inconnue à coefficients réels.",
              ],
              hors_programme=[
                  "Racines n-ièmes d'un nombre complexe (zⁿ = a) et composées de transformations en écriture complexe : hors programme en 2ème Bac PC/SVT.",
              ],
              perimetre=[
                  'Équations du second degré à coefficients réels (2.4.8, 2.4.9).',
                  'Transformations : translation, homothétie, rotation (2.4.5, 2.4.6).',
              ],
              theoremes=[
                  'Forme trigonométrique et exponentielle',
                  'Formule de Moivre',
                  "Formules d'Euler",
                  'Équations du second degré dans ℂ',
                  'Transformations du plan : translation, homothétie, rotation',
              ],
              contenus=[
                  'Calcul algébrique sur les nombres complexes dans leurs différentes écritures : algébrique, trigonométrique et exponentielle',
                  "Passage de l'écriture algébrique à l'écriture trigonométrique, et réciproquement",
                  "Linéarisation de monômes trigonométriques à l'aide de l'écriture exponentielle",
                  'Traduction complexe de notions géométriques : distance de deux points, mesure des angles, alignement de points, colinéarité et orthogonalité de vecteurs',
                  "Écriture complexe de la translation, de l'homothétie et de la rotation ; reconnaissance de ces transformations à partir de leur expression complexe",
                  "Résolution de problèmes de géométrie à l'aide des nombres complexes (alignement, orthogonalité…)",
                  "Résolution dans ℂ de l'équation az² + bz + c = 0, où a, b et c sont réels",
                  'Équations qui se ramènent à une équation du second degré à une inconnue et à coefficients réels',
              ],
              statut='inchangé',
              sources=[
                  'Cadres SM §2.2.7-2.2.8 ; absents du cadre PC.',
              ]),
    _chapitre("Produit scalaire dans l'espace", 'Géométrie',
              titre_officiel="Premier sous-domaine : Produit scalaire dans V₃ ; Deuxième sous-domaine : Applications du produit scalaire dans l'espace",
              periode='Non donnée par le document (cadre d’examen) ; habituellement fin du Semestre 1, parfois Semestre 2',
              capacites=[
                  "2.1.1. Exprimer et démontrer l'orthogonalité de deux vecteurs en utilisant le produit scalaire.",
                  "2.1.2. Exprimer vectoriellement l'orthogonalité et ses propriétés.",
                  "2.1.3. Exprimer analytiquement l'orthogonalité et ses propriétés.",
                  "2.2.1. Déterminer une équation d'un plan défini par un point et un vecteur normal.",
                  "2.2.2. Déterminer une représentation paramétrique d'une droite passant par un point et orthogonale à un plan.",
                  "2.2.3. Étudier l'ensemble des points M(x, y, z) tels que : x² + y² + z² + ax + by + cz + d = 0.",
                  "2.2.4. Déterminer une équation cartésienne d'une sphère définie par son centre et son rayon.",
                  "2.2.5. Reconnaître l'ensemble des points M de l'espace vérifiant la relation MA→ · MB→ = 0.",
                  "2.2.6. Utiliser la distance d'un point à un plan pour résoudre des problèmes géométriques (positions relatives d'un plan et d'une sphère et d'une droite et d'une sphère...).",
              ],
              theoremes=[
                  "Vecteur normal et équation d'un plan",
                  "Équation d'une sphère",
                  "Distance d'un point à un plan",
                  "Positions relatives d'une sphère et d'un plan ou d'une droite",
                  "Représentation paramétrique d'une droite",
              ],
              contenus=[
                  "Produit scalaire dans V₃ (vecteurs de l'espace) : orthogonalité de deux vecteurs, expressions vectorielle et analytique, propriétés",
                  "Équation d'un plan défini par un point et un vecteur normal",
                  "Représentation paramétrique d'une droite passant par un point et orthogonale à un plan",
                  'Ensemble des points M(x, y, z) tels que x² + y² + z² + ax + by + cz + d = 0',
                  "Équation cartésienne d'une sphère définie par son centre et son rayon",
                  "Ensemble des points M de l'espace tels que MA→ · MB→ = 0",
                  "Distance d'un point à un plan ; positions relatives d'un plan et d'une sphère, et d'une droite et d'une sphère",
              ],
              statut='inchangé',
              remarque="Représentation paramétrique d'une droite (2.2.2) et positions relatives sphère/plan, sphère/droite (2.2.6) nommées par le cadre PC."),
    _chapitre('Fonctions exponentielles', 'Analyse',
              titre_officiel='Deuxième sous-domaine : Continuité, dérivation et étude de fonctions (items 1.2.20 et 1.2.21, et 1.2.22 appliqué aux exponentielles)',
              periode='Non donnée par le document (cadre d’examen) ; habituellement début du Semestre 2',
              capacites=[
                  '1.2.20. Maîtriser la résolution des équations, des inéquations et des systèmes comportant des exponentielles népériennes.',
                  '1.2.21. Maîtriser les limites de base de la fonction exponentielle népérienne et les appliquer.',
                  '(1.2.22, appliqué aux exponentielles) Étudier des fonctions ou des composées de fonctions figurant au programme et les représenter graphiquement.',
              ],
              theoremes=[
                  "Dérivée et propriétés de l'exponentielle",
                  "Limites usuelles de l'exponentielle",
                  'Fonction exponentielle de base a',
              ],
              contenus=[
                  'Équations, inéquations et systèmes comportant des exponentielles népériennes',
                  'Limites de base de la fonction exponentielle népérienne et leurs applications',
                  "Étude et représentation graphique de fonctions (et de composées) faisant intervenir l'exponentielle (item 1.2.22)",
              ],
              statut='inchangé'),
    _chapitre('Équations différentielles', 'Analyse',
              titre_officiel='Deuxième sous-domaine : Continuité, dérivation et étude de fonctions (items 1.2.23 et 1.2.24)',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 2, après les fonctions exponentielles',
              capacites=[
                  "1.2.23. Résoudre l'équation différentielle y' = ay + b.",
                  "1.2.24. Résoudre l'équation différentielle y'' + ay' + by = 0.",
              ],
              perimetre=[
                  "Équations y' = ay + b et y'' + ay' + by = 0, a et b réels, sans second membre pour le second ordre (1.2.23, 1.2.24).",
              ],
              theoremes=[
                  "Équation y' = ay + b",
                  "Équation y'' + ay' + by = 0",
              ],
              contenus=[
                  "Équation différentielle y' = ay + b",
                  "Équation différentielle y'' + ay' + by = 0",
              ],
              statut='inchangé'),
    _chapitre('Calcul intégral', 'Analyse',
              titre_officiel='Troisième sous-domaine : Calcul intégral',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 2',
              capacites=[
                  "1.3.1. Utiliser une fonction primitive ou la technique de l'intégration par parties pour calculer l'intégrale d'une fonction.",
                  "1.3.2. Utiliser les propriétés de l'intégrale.",
                  "1.3.3. Calculer l'aire d'un domaine du plan limité par deux courbes.",
                  "1.3.4. Calculer le volume d'un solide de révolution engendré par la rotation de la courbe d'une fonction autour de l'axe des abscisses.",
              ],
              hors_programme=[
                  'Sommes de Riemann et fonctions x ↦ ∫ₐ^{u(x)} f(t) dt : hors programme en 2ème Bac PC/SVT.',
              ],
              perimetre=[
                  "Volumes de révolution autour de l'axe des abscisses (1.3.4).",
                  "Techniques nommées : primitive et intégration par parties (1.3.1) ; un changement de variable n'est pas exigible mais peut être guidé par l'énoncé.",
              ],
              theoremes=[
                  "Théorème fondamental de l'analyse",
                  "Primitives et techniques d'intégration",
                  'Intégration par parties',
                  "Valeur moyenne d'une fonction",
                  "Calcul d'aires et de volumes",
              ],
              contenus=[
                  "Calcul de l'intégrale d'une fonction à l'aide d'une fonction primitive ou par intégration par parties",
                  "Propriétés de l'intégrale",
                  "Aire d'un domaine du plan limité par deux courbes",
                  "Volume d'un solide de révolution engendré par la rotation de la courbe d'une fonction autour de l'axe des abscisses",
              ],
              statut='inchangé',
              sources=[
                  'Cadres SM §1.4.5-1.4.6 ; absents du cadre PC.',
              ]),
    _chapitre('Produit vectoriel', 'Géométrie',
              titre_officiel='Troisième sous-domaine : Produit vectoriel',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 2',
              capacites=[
                  "2.3.1. Calculer l'aire d'un triangle en utilisant le produit vectoriel.",
                  "2.3.2. Déterminer une équation d'un plan défini par trois points non alignés.",
                  "2.3.3. Utiliser la distance d'un point à une droite pour résoudre des problèmes géométriques.",
                  '2.3.4. Appliquer le produit vectoriel pour résoudre des problèmes géométriques.',
              ],
              theoremes=[
                  'Expression analytique du produit vectoriel',
                  "Distance d'un point à une droite dans l'espace",
              ],
              contenus=[
                  "Aire d'un triangle à l'aide du produit vectoriel",
                  "Équation d'un plan défini par trois points non alignés",
                  "Distance d'un point à une droite, utilisée pour résoudre des problèmes géométriques",
                  'Applications du produit vectoriel à des problèmes géométriques',
              ],
              statut='inchangé'),
    _chapitre('Dénombrement', 'Probabilités',
              titre_officiel='Cinquième sous-domaine : Calcul de probabilités (item 2.5.1)',
              periode='Non donnée par le document (cadre d’examen) ; habituellement Semestre 2, en ouverture de la leçon de probabilités',
              capacites=[
                  '2.5.1. Utiliser le modèle de dénombrement convenable selon la situation étudiée.',
              ],
              theoremes=[
                  'Principe multiplicatif',
                  'Arrangements et combinaisons',
              ],
              contenus=[
                  'Choix du modèle de dénombrement adapté à la situation étudiée',
              ],
              statut='inchangé'),
    _chapitre('Probabilités', 'Probabilités',
              titre_officiel='Cinquième sous-domaine : Calcul de probabilités (items 2.5.2 à 2.5.6)',
              periode="Non donnée par le document (cadre d’examen) ; habituellement fin du Semestre 2, dernière leçon de l'année",
              capacites=[
                  "2.5.2. Calculer la probabilité de la réunion de deux évènements, de l'évènement contraire d'un évènement et de l'intersection de deux évènements.",
                  "2.5.3. Calculer la probabilité conditionnelle et l'appliquer pour le calcul de la probabilité de l'intersection de deux évènements.",
                  "2.5.4. Reconnaître l'indépendance de deux évènements.",
                  "2.5.5. Déterminer la loi de probabilité d'une variable aléatoire et calculer ses différents paramètres.",
                  "2.5.6. Reconnaître la loi binomiale et l'appliquer dans des situations variées.",
              ],
              hors_programme=[
                  'Fonction de répartition : hors programme en 2ème Bac PC/SVT.',
              ],
              theoremes=[
                  'Probabilité conditionnelle',
                  'Formule des probabilités totales',
                  "Indépendance d'événements",
                  'Variable aléatoire : espérance et variance',
                  'Loi binomiale',
              ],
              contenus=[
                  "Probabilité de la réunion de deux évènements, de l'évènement contraire et de l'intersection de deux évènements",
                  "Probabilité conditionnelle et son application au calcul de la probabilité de l'intersection de deux évènements",
                  'Indépendance de deux évènements',
                  'Variable aléatoire : loi de probabilité et ses différents paramètres',
                  'Loi binomiale et ses applications dans des situations variées',
                  'En appui : modèle de dénombrement adapté à la situation (item 2.5.1, voir le chapitre Dénombrement)',
              ],
              statut='inchangé',
              sources=[
                  'Cadres SM §2.3.6 ; absente du cadre PC.',
              ]),
]


PROGRAMME = {TC: _TC, SM1: _SM1, SM2: _SM2, PC: _PC}
for _chapitres in PROGRAMME.values():
    for _i, _c in enumerate(_chapitres, 1):
        _c['ordre'] = _i
    assert len({c['nom'] for c in _chapitres}) == len(_chapitres), 'chapitre en double dans un niveau'

# Un chapitre partagé entre niveaux est UNE ligne en base : même domaine partout.
DOMAINE_CHAPITRE = {}
for _chapitres in PROGRAMME.values():
    for _c in _chapitres:
        assert DOMAINE_CHAPITRE.setdefault(_c['nom'], _c['domaine']) == _c['domaine'], _c['nom']

# Domaine « maison » de chaque théorème (seeder et migration) : get_or_create(name, subject, subfield=ce domaine),
# quel que soit le domaine des chapitres qui le citent (binôme de Newton : Probabilités, même sous « Nombres
# complexes » ; raisonnement par récurrence : Algèbre, même sous « Suites numériques »).
DOMAINE_THEOREME = {
    # Algèbre
    "Application réciproque d'une bijection": 'Algèbre',
    "Base et dimension d'un espace vectoriel": 'Algèbre',
    'Composée de deux bijections': 'Algèbre',
    'Congruences modulo n': 'Algèbre',
    'Critères de divisibilité': 'Algèbre',
    "Discriminant et racines d'un trinôme": 'Algèbre',
    'Division euclidienne dans ℤ': 'Algèbre',
    'Division euclidienne et congruences': 'Algèbre',
    'Décomposition en facteurs premiers': 'Algèbre',
    'Familles libres et génératrices': 'Algèbre',
    'Forme trigonométrique et exponentielle': 'Algèbre',
    'Formule de Moivre': 'Algèbre',
    "Formules d'Euler": 'Algèbre',
    'Groupes, anneaux et corps': 'Algèbre',
    'Identités remarquables': 'Algèbre',
    'Infinité des nombres premiers': 'Algèbre',
    'Inégalité triangulaire': 'Algèbre',
    'Irrationalité de √2': 'Algèbre',
    'Lois de De Morgan': 'Algèbre',
    'Lois de composition interne': 'Algèbre',
    "Matrices carrées d'ordre 2 et 3": 'Algèbre',
    'Méthode du déterminant (Cramer) pour un système 2×2': 'Algèbre',
    'Numération dans une base donnée': 'Algèbre',
    'Opérations sur les ensembles et lois de De Morgan': 'Algèbre',
    'Ordre et opérations': 'Algèbre',
    'PGCD et PPCM par la décomposition en facteurs premiers': 'Algèbre',
    "PGCD, PPCM et algorithme d'Euclide": 'Algèbre',
    'Parité de la somme et du produit': 'Algèbre',
    'Petit théorème de Fermat': 'Algèbre',
    'Propriétés de la valeur absolue': 'Algèbre',
    'Propriétés des puissances': 'Algèbre',
    'Propriétés des racines carrées': 'Algèbre',
    "Racine d'un polynôme et factorisation par (x − a)": 'Algèbre',
    "Racines n-ièmes d'un nombre complexe": 'Algèbre',
    'Raisonnement par contraposée': 'Algèbre',
    "Raisonnement par l'absurde": 'Algèbre',
    'Raisonnement par récurrence': 'Algèbre',
    'Signe du trinôme': 'Algèbre',
    'Somme et produit des racines': 'Algèbre',
    'Sous-espaces vectoriels': 'Algèbre',
    'Sous-groupes et morphismes de groupes': 'Algèbre',
    'Structure de (ℤ/nℤ, +, ×)': 'Algèbre',
    'Théorème de Bézout': 'Algèbre',
    'Théorème de Gauss': 'Algèbre',
    'Transfert de structure par un morphisme': 'Algèbre',
    'Transformations du plan : translation, homothétie, rotation': 'Algèbre',
    'Égalité de deux polynômes': 'Algèbre',
    'Équations du second degré dans ℂ': 'Algèbre',
    # Analyse
    'Angles associés': 'Analyse',
    'Branches infinies et asymptotes': 'Analyse',
    "Calcul d'aires et de volumes": 'Analyse',
    "Centre et axe de symétrie d'une courbe": 'Analyse',
    "Concavité et point d'inflexion": 'Analyse',
    'Continuité de la fonction réciproque': 'Analyse',
    'Convergence et divergence': 'Analyse',
    "Dérivée d'une fonction composée": 'Analyse',
    "Dérivée d'une somme, d'un produit, d'un quotient": 'Analyse',
    'Dérivée de la fonction réciproque': 'Analyse',
    "Dérivée et propriétés de l'exponentielle": 'Analyse',
    'Dérivée et propriétés du logarithme': 'Analyse',
    'Fonction arc tangente': 'Analyse',
    'Fonction exponentielle de base a': 'Analyse',
    'Fonction logarithme de base a': 'Analyse',
    'Fonction majorée, minorée, bornée': 'Analyse',
    'Fonction périodique': 'Analyse',
    'Fonction racine n-ième et puissance rationnelle': 'Analyse',
    'Fonctions de référence (x², 1/x, √x, ax² + bx + c, (ax + b)/(cx + d))': 'Analyse',
    'Fonctions paires et impaires': 'Analyse',
    "Formules d'addition": 'Analyse',
    'Formules de duplication': 'Analyse',
    'Formules de transformation somme-produit': 'Analyse',
    "Image d'un intervalle par une fonction continue": 'Analyse',
    'Intégration par parties': 'Analyse',
    'Inégalité des accroissements finis': 'Analyse',
    "Limite et continuité d'une fonction composée": 'Analyse',
    'Limites et ordre': 'Analyse',
    'Limites trigonométriques usuelles': 'Analyse',
    "Limites usuelles de l'exponentielle": 'Analyse',
    'Limites usuelles du logarithme': 'Analyse',
    'Logarithme décimal': 'Analyse',
    "Monotonie d'une fonction composée": 'Analyse',
    'Méthode de dichotomie': 'Analyse',
    'Opérations sur les limites': 'Analyse',
    "Primitive d'une fonction continue sur un intervalle": 'Analyse',
    'Primitives des fonctions usuelles': 'Analyse',
    "Primitives et techniques d'intégration": 'Analyse',
    'Prolongement par continuité': 'Analyse',
    'Relation cos²x + sin²x = 1': 'Analyse',
    'Sens de variation et taux de variation': 'Analyse',
    'Signe de la dérivée et sens de variation': 'Analyse',
    'Somme de termes consécutifs': 'Analyse',
    'Sommes de Riemann': 'Analyse',
    'Suite majorée, minorée, monotone': 'Analyse',
    'Suite monotone et bornée : convergence': 'Analyse',
    'Suites adjacentes': 'Analyse',
    'Suites arithmétiques et géométriques': 'Analyse',
    'Suites récurrentes u(n+1) = f(u(n))': 'Analyse',
    'Théorème de Rolle': 'Analyse',
    'Théorème de la bijection': 'Analyse',
    'Théorème des accroissements finis (TAF)': 'Analyse',
    'Théorème des gendarmes': 'Analyse',
    'Théorème des valeurs intermédiaires (TVI)': 'Analyse',
    "Théorème fondamental de l'analyse": 'Analyse',
    'Transformation de a cos x + b sin x': 'Analyse',
    "Valeur moyenne d'une fonction": 'Analyse',
    'Équation de la tangente': 'Analyse',
    "Équation y' = ay + b": 'Analyse',
    "Équation y'' + ay' + by = 0": 'Analyse',
    'Équations trigonométriques de base': 'Analyse',
    # Géométrie
    'Associativité du barycentre': 'Géométrie',
    "Base de l'espace et coordonnées": 'Géométrie',
    "Caractérisation de l'orthogonalité par le produit scalaire": 'Géométrie',
    'Composée de deux symétries axiales': 'Géométrie',
    'Condition de colinéarité de deux vecteurs': 'Géométrie',
    'Condition de colinéarité par le déterminant': 'Géométrie',
    'Conservation du coefficient de colinéarité par projection': 'Géométrie',
    'Coordonnées du barycentre': 'Géométrie',
    "Distance d'un point à un plan": 'Géométrie',
    "Distance d'un point à une droite": 'Géométrie',
    "Distance d'un point à une droite dans l'espace": 'Géométrie',
    'Expression analytique du produit scalaire': 'Géométrie',
    'Expression analytique du produit vectoriel': 'Géométrie',
    "Image d'une droite et d'un cercle par une transformation": 'Géométrie',
    "Orthogonalité d'une droite et d'un plan": 'Géométrie',
    "Parallélisme d'une droite et d'un plan, de deux plans": 'Géométrie',
    'Parallélisme de deux droites': 'Géométrie',
    "Positions relatives d'une sphère et d'un plan ou d'une droite": 'Géométrie',
    'Propriétés de conservation des transformations': 'Géométrie',
    'Propriétés de la rotation': 'Géométrie',
    'Relation de Chasles': 'Géométrie',
    "Représentation paramétrique d'une droite": 'Géométrie',
    "Théorème d'Al-Kashi": 'Géométrie',
    'Théorème de Thalès': 'Géométrie',
    'Théorème de la médiane': 'Géométrie',
    'Théorème du toit': 'Géométrie',
    "Vecteur normal et équation d'un plan": 'Géométrie',
    'Vecteurs coplanaires': 'Géométrie',
    "Équation cartésienne d'un plan": 'Géométrie',
    "Équation cartésienne et équation réduite d'une droite": 'Géométrie',
    "Équation d'un cercle": 'Géométrie',
    "Équation d'une sphère": 'Géométrie',
    # Probabilités
    'Arrangements et combinaisons': 'Probabilités',
    'Fonction de répartition': 'Probabilités',
    'Formule des probabilités totales': 'Probabilités',
    'Formule du binôme de Newton': 'Probabilités',
    "Indépendance d'événements": 'Probabilités',
    'Loi binomiale': 'Probabilités',
    'Principe multiplicatif': 'Probabilités',
    'Probabilité conditionnelle': 'Probabilités',
    'Triangle de Pascal': 'Probabilités',
    'Variable aléatoire : espérance et variance': 'Probabilités',
    # Statistiques
    'Moyenne, variance et écart type': 'Statistiques',
}
_cites = {t for _chapitres in PROGRAMME.values() for _c in _chapitres for t in _c['theoremes']}
assert _cites == set(DOMAINE_THEOREME), sorted(_cites ^ set(DOMAINE_THEOREME))

# Anciens noms de chapitre (import de fiches, fiches IA en attente). None : toujours traduit. Un niveau : seulement
# pour une fiche de ce niveau ; l'ancien nom est gardé (et le nouveau ajouté) si un autre niveau de la fiche a
# encore l'ancien chapitre au programme — même règle que la migration pour un contenu à plusieurs niveaux.
ALIAS_CHAPITRES = {
    'Théorème des Accroissements Finis (TAF)': {None: ('Dérivation et étude des fonctions',)},
    'Fonctions logarithmiques et exponentielles': {None: ('Fonctions logarithmiques', 'Fonctions exponentielles')},
    'Calcul trigonométrique': {SM1: ('Trigonométrie (formules de transformation)',)},
    'Produit scalaire dans le plan': {SM1: ('Étude analytique du produit scalaire dans le plan',)},
    "Géométrie dans l'espace": {SM1: ("Géométrie analytique de l'espace",)},
    'Dénombrement': {SM2: ('Probabilités',)},
    # Noms proposés par une version précédente de la spécification.
    'Calcul trigonométrique : formules de transformation': {None: ('Trigonométrie (formules de transformation)',)},
    'Étude analytique du produit scalaire': {None: ('Étude analytique du produit scalaire dans le plan',)},
}

# Anciens noms de théorème → nouveaux ; () = retiré du programme, sans remplaçant (étiquette ôtée, avertissement).
ALIAS_THEOREMES = {
    "Applications du TAF à l'étude des fonctions": ('Théorème des accroissements finis (TAF)',),
    'Équations linéaires du premier ordre': ("Équation y' = ay + b",),
    'Méthode de variation de la constante': ("Équation y' = ay + b",),
    'Formule de combinaison et permutation': ('Arrangements et combinaisons',),
    'Théorème de Bolzano-Weierstrass': ("Image d'un intervalle par une fonction continue",),
    'Applications linéaires et matrices': ("Matrices carrées d'ordre 2 et 3",),
    'Définition et propriétés des groupes, anneaux et corps': ('Groupes, anneaux et corps',),
    'Théorème de Moivre': ('Formule de Moivre',),
    "Dérivée et propriétés du logarithme et de l'exponentielle": ('Dérivée et propriétés du logarithme',
                                                                  "Dérivée et propriétés de l'exponentielle"),
    "Positions relatives d'une sphère et d'un plan": ("Positions relatives d'une sphère et d'un plan ou d'une droite",),
    'Loi des grands nombres': (),
    'Théorème central limite': (),
    'Produit scalaire et propriétés': (),
}

# Anciennes adresses de dossier (/<rubrique>/niveau/<niveau>/<chapitre>) → nouvelle, par niveau : redirection 301.
# Celles du Tronc commun sont un filet (adresses jamais publiées, slug d'un chapitre de 1ère tapé au mauvais niveau).
ALIAS_SLUGS = {
    '1ere-bac-sm': {
        'calcul-trigonometrique': 'trigonometrie-formules-de-transformation',
        'produit-scalaire-dans-le-plan': 'etude-analytique-du-produit-scalaire-dans-le-plan',
        'geometrie-dans-lespace': 'geometrie-analytique-de-lespace',
    },
    '2eme-bac-sm': {
        'theoreme-des-accroissements-finis-taf': 'derivation-et-etude-des-fonctions',
        'denombrement': 'probabilites',
        'fonctions-logarithmiques-et-exponentielles': 'fonctions-logarithmiques',  # page des seeders de 2025
    },
    'tronc-commun-sciences': {
        'trigonometrie-formules-de-transformation': 'calcul-trigonometrique',
        'etude-analytique-du-produit-scalaire-dans-le-plan': 'produit-scalaire-dans-le-plan',
        'geometrie-analytique-de-lespace': 'geometrie-dans-lespace',
    },
}


# Anciennes adresses d'un NIVEAU (/<rubrique>/niveau/<ancien>[/<chapitre>]) → nouveau slug : redirection 301.
ALIAS_NIVEAUX = {
    '2eme-bac-pc': '2eme-bac-pc-svt',  # « 2ème Bac PC » → « 2ème Bac PC/SVT » (12/10/2026)
}

# Anciens noms de niveau encore écrits dans des fiches, l'import ou l'IA → nom actuel.
NOMS_NIVEAUX_ANCIENS = {
    '2ème bac pc': PC, '2eme bac pc': PC, '2 bac pc': PC, '2bac pc': PC, '2 pc': PC,
    '2ème bac svt': PC, '2eme bac svt': PC, '2 bac svt': PC, '2bac svt': PC, '2 svt': PC,
    '2ème bac pc/svt': PC, '2 pc/svt': PC, '2bac pc/svt': PC,
}


def nom_niveau_actuel(nom):
    """Nom actuel d'un niveau écrit sous un ancien nom (« 2ème Bac PC » → « 2ème Bac PC/SVT »), sinon tel quel."""
    return NOMS_NIVEAUX_ANCIENS.get(' '.join((nom or '').lower().split()), nom)


def _nom_niveau(niveau):
    nom = getattr(niveau, 'name', niveau)
    return nom_niveau_actuel(nom) if isinstance(nom, str) else nom


def _cle(nom):
    return (nom or '').strip().lower()


class _Rangs(dict):
    def __missing__(self, nom):
        return RANG_ABSENT


def rang(niveau):
    """{nom de chapitre: ordre dans le niveau} ; rang(niveau)[nom absent] = RANG_ABSENT."""
    return _Rangs((c['nom'], c['ordre']) for c in PROGRAMME.get(_nom_niveau(niveau), []))


def chapitre(niveau, nom):
    """Copie de l'entrée du programme de ce chapitre à ce niveau, ou None."""
    for c in PROGRAMME.get(_nom_niveau(niveau), []):
        if c['nom'] == nom:
            return copy.deepcopy(c)
    return None


def chapitres_du_niveau(level, queryset=None):
    """Chapitres de Mathématiques rattachés au niveau, dans l'ordre du programme (clé (rang, id))."""
    from apps.caracteristics.models import Chapter, ClassLevel

    if isinstance(level, str):
        level = ClassLevel.objects.filter(name=level).order_by('id').first()
    elif isinstance(level, int):
        level = ClassLevel.objects.filter(pk=level).first()
    if level is None:
        return []
    qs = (queryset if queryset is not None else Chapter.objects.all()).filter(class_levels=level,
                                                                                subject__name=MATIERE)
    rangs = rang(level.name)
    return sorted(qs.distinct(), key=lambda ch: (rangs[ch.name], ch.id))


# ── Annexe D de la consigne de l'IA

_A_VERIFIER = re.compile(r'\s*\(à vérifier\)')


def _liste(items):
    """Éléments d'une rubrique sur une ligne : « a ; b ; c. »"""
    propres = [_A_VERIFIER.sub('', x).strip().rstrip(' ;.') for x in items]
    return ' ; '.join(x for x in propres if x) + '.'


def annexe_d(niveaux=None):
    """Annexe D « Programme officiel » (Markdown) pour ces niveaux ; None ou vide = tous, dans l'ordre de NIVEAUX."""
    voulus = {_nom_niveau(n) for n in (niveaux or [])}
    lignes = [
        '## Annexe D — Programme officiel par niveau',
        '',
        "Pour chaque niveau, ses chapitres (noms exacts) dans l'ordre où ils sont habituellement enseignés (un "
        'repère, pas une règle), avec les capacités exigibles, ce qui est hors programme (exclusion nette) et le '
        'périmètre habituel (pas une interdiction : ne refuse pas une méthode pour cette seule raison).',
    ]
    for niveau, _ordre in NIVEAUX:
        if voulus and niveau not in voulus:
            continue
        lignes += ['', f'### {niveau} — ordre : {ORDRE_NATURE[niveau]}']
        if niveau in TITRES_SEULS:
            lignes.append('Le document officiel ne donne que les titres des leçons : les repères ci-dessous sont '
                          'indicatifs, à lire avec ton jugement, jamais comme des règles.')
        for c in PROGRAMME[niveau]:
            tete = f"{c['ordre']}. **{c['nom']}** ({c['domaine']})"
            if niveau in TITRES_SEULS and c['titre_officiel']:
                tete += f" — titre officiel : « {c['titre_officiel']} »"
            lignes.append(tete)
            for champ, titre in (('capacites', 'Capacités'), ('hors_programme', 'Hors programme'),
                                 ('perimetre', 'Périmètre habituel (pas une interdiction)'),
                                 ('reperes', 'Repères habituels du programme (indicatifs, non exhaustifs)'),
                                 ('vu_plus_tard', 'Habituellement vu plus tard (indicatif, pas une interdiction)')):
                if c[champ]:
                    lignes.append(f'   - {titre} : {_liste(c[champ])}')
    return '\n'.join(lignes)


# ── Anciens noms

_ALIAS_CH = {_cle(k): (k, v) for k, v in ALIAS_CHAPITRES.items()}
_ALIAS_TH = {_cle(k): v for k, v in ALIAS_THEOREMES.items()}


def _niveaux_au_programme(nom):
    return {n for n, chapitres in PROGRAMME.items() if any(c['nom'] == nom for c in chapitres)}


def traduire_noms(chapitres, theoremes=(), niveaux=()):
    """Traduit les anciens noms d'une fiche. Renvoie (chapitres, theoremes, avertissements), sans doublon, dans
    l'ordre d'origine. Alias de niveau B (scission, détachement) : appliqué seulement si B est un niveau de la fiche ;
    l'ancien chapitre est REMPLACÉ si aucun autre niveau de la fiche ne l'a au programme, sinon gardé et le nouveau
    AJOUTÉ. Un théorème retiré sans remplaçant est ôté."""
    niveaux_fiche = {_cle(_nom_niveau(n)) for n in niveaux or []}
    sortie_ch, avert = [], []
    for nom in chapitres or []:
        trouve = _ALIAS_CH.get(_cle(nom))
        if trouve is None:
            sortie_ch.append(nom)
            continue
        ancien, regles = trouve
        if None in regles:
            sortie_ch += list(regles[None])
            avert.append(f'chapitre « {nom} » → « {" », « ".join(regles[None])} » (ancien nom)')
            continue
        applique = False
        for niveau, nouveaux in regles.items():
            if _cle(niveau) not in niveaux_fiche:
                continue
            autres = {_cle(n) for n in _niveaux_au_programme(ancien) - {niveau}}
            garde = bool(niveaux_fiche & autres)
            sortie_ch += ([nom] if garde else []) + list(nouveaux)
            texte = ' », « '.join(nouveaux)
            avert.append(f'chapitre « {nom} » ({niveau}) : « {texte} » ' + ('ajouté' if garde else 'à la place'))
            applique = True
            break
        if not applique:
            sortie_ch.append(nom)
    sortie_th = []
    for nom in theoremes or []:
        nouveaux = _ALIAS_TH.get(_cle(nom))
        if nouveaux is None:
            sortie_th.append(nom)
        elif nouveaux:
            sortie_th += list(nouveaux)
            avert.append(f'théorème « {nom} » → « {" », « ".join(nouveaux)} » (ancien nom)')
        else:
            avert.append(f'théorème « {nom} » retiré (hors programme)')

    def unique(noms):
        vus, out = set(), []
        for n in noms:
            if _cle(n) not in vus:
                vus.add(_cle(n))
                out.append(n)
        return out
    return unique(sortie_ch), unique(sortie_th), avert


# ── Base = programme ?

def ecarts_base():
    """Écarts entre la base et ce programme, en lecture seule : {'chapitres': [...], 'theoremes': [...]}."""
    from apps.caracteristics.models import Chapter, ClassLevel, Subject, Theorem

    ecarts = {'chapitres': [], 'theoremes': []}
    maths = Subject.objects.filter(name=MATIERE).order_by('id').first()
    if maths is None:
        ecarts['chapitres'].append(f'matière « {MATIERE} » absente')
        return ecarts
    for niveau, _ordre in NIVEAUX:
        level = ClassLevel.objects.filter(name=niveau).order_by('id').first()
        if level is None:
            ecarts['chapitres'].append(f'{niveau} : niveau absent')
            continue
        attendus = [c['nom'] for c in PROGRAMME[niveau]]
        en_base = list(Chapter.objects.filter(class_levels=level, subject=maths).values_list('name', flat=True))
        for nom in attendus:
            if nom not in en_base:
                ecarts['chapitres'].append(f'{niveau} : « {nom} » manquant')
        for nom in sorted(set(en_base) - set(attendus)):
            ecarts['chapitres'].append(f'{niveau} : « {nom} » rattaché mais hors programme')
    for nom, domaine in DOMAINE_CHAPITRE.items():
        lignes = list(Chapter.objects.filter(name=nom, subject=maths).select_related('subfield'))
        if len(lignes) > 1:
            ecarts['chapitres'].append(f'« {nom} » : {len(lignes)} lignes')
        if lignes and (lignes[0].subfield is None or lignes[0].subfield.name != domaine):
            ecarts['chapitres'].append(f'« {nom} » : domaine {getattr(lignes[0].subfield, "name", None)} '
                                       f'au lieu de {domaine}')
    chapitres_de, niveaux_de = {}, {}
    for niveau, chapitres in PROGRAMME.items():
        for c in chapitres:
            for t in c['theoremes']:
                chapitres_de.setdefault(t, set()).add(c['nom'])
                niveaux_de.setdefault(t, set()).add(niveau)
    noms_niveaux = [n for n, _o in NIVEAUX]
    for nom, domaine in DOMAINE_THEOREME.items():
        lignes = list(Theorem.objects.filter(name=nom, subject=maths).select_related('subfield')
                      .prefetch_related('chapters', 'class_levels'))
        if not lignes:
            ecarts['theoremes'].append(f'« {nom} » manquant')
            continue
        if len(lignes) > 1:
            ecarts['theoremes'].append(f'« {nom} » : {len(lignes)} lignes')
        th = lignes[0]
        if th.subfield is None or th.subfield.name != domaine:
            ecarts['theoremes'].append(f'« {nom} » : domaine {getattr(th.subfield, "name", None)} au lieu de {domaine}')
        chapitres = {c.name for c in th.chapters.all() if c.subject_id == maths.id}
        if chapitres != chapitres_de[nom]:
            ecarts['theoremes'].append(f'« {nom} » : chapitres {sorted(chapitres)} au lieu de '
                                       f'{sorted(chapitres_de[nom])}')
        niveaux = {lv.name for lv in th.class_levels.all() if lv.name in noms_niveaux}
        if niveaux != niveaux_de[nom]:
            ecarts['theoremes'].append(f'« {nom} » : niveaux {sorted(niveaux)} au lieu de {sorted(niveaux_de[nom])}')
    en_trop = (Theorem.objects.filter(subject=maths, class_levels__name__in=noms_niveaux)
               .exclude(name__in=list(DOMAINE_THEOREME)).values_list('name', flat=True).distinct())
    for nom in sorted(en_trop):
        ecarts['theoremes'].append(f'« {nom} » : rattaché à un niveau mais hors programme')
    return ecarts
