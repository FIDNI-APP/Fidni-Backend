import os
import sys
import django
from pathlib import Path

# Add src directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
src_path = BASE_DIR / 'src'
sys.path.insert(0, str(src_path))

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Setup Django
django.setup()

# Now import models
from apps.caracteristics.models import ClassLevel, Subject, Chapter, Subfield, Theorem

import logging

logger = logging.getLogger('django')


# Taxonomie (niveaux → matières → domaines → chapitres → théorèmes), rejouée à chaque démarrage du
# conteneur : idempotente (get_or_create), on peut donc AJOUTER des lignes sans risque. Ne pas
# renommer une entrée existante : cela créerait un doublon (le nom fait office d'identifiant).
# Pour un nouveau niveau : l'ajouter dans NIVEAUX (ordre = position dans les menus, unique), puis
# ses chapitres dans TAXONOMIE. Un chapitre commun à plusieurs niveaux est partagé (même nom,
# même domaine) et rattaché à chacun.

NIVEAUX = [
    # (nom affiché, ordre) — ordre = position dans les menus, du plus jeune au plus avancé
    ("Tronc commun Sciences", 1),
    ("1ère Bac SM", 2),
    ("2ème Bac SM", 3),
    ("2ème Bac PC", 4),
]

mappings = {
    "2bacsm": {
        "Mathématiques": {
            "Algèbre": {
                "Nombres complexes": [
                        "Théorème de Moivre",
                        "Forme trigonométrique et exponentielle"
                    ]
                ,
                "Arithmétique": [
                        "Théorème de Bézout",
                        "Théorème de Gauss",
                        "Petit théorème de Fermat"
                    ]
                ,
                "Structures algébriques": [
                        "Définition et propriétés des groupes, anneaux et corps",
                        "Applications linéaires et matrices"
                    ]
                ,
                "Espaces vectoriels": [
                        "Base et dimension d'un espace vectoriel",
                        "Produit scalaire et propriétés"
                    ]
            },
            
            "Analyse": {
                "Limites et continuité": [
                        "Théorème des gendarmes",
                        "Théorème de Bolzano-Weierstrass"
                    ]
                ,
                "Dérivation et étude des fonctions": [
                        "Théorème de Rolle",
                        "Théorème des accroissements finis (TAF)"
                    ]
                ,
                "Théorème des Accroissements Finis (TAF)": [
                        "Applications du TAF à l'étude des fonctions"
                    ]
                ,
                "Suites numériques": [
                        "Convergence et divergence",
                        "Suites arithmétiques et géométriques"
                    ]
                ,
                "Fonctions logarithmiques" : [
                        "Dérivée et propriétés du logarithme"
                    ]
                ,
                "Fonctions exponentielles": [
                        "Dérivée et propriétés de l'exponentielle"
                    ],

                "Équations différentielles": [
                        "Équations linéaires du premier ordre",
                        "Méthode de variation de la constante"
                    ]
                ,
                "Calcul intégral": [
                        "Théorème fondamental de l'analyse",
                        "Primitives et techniques d'intégration"
                    ]
                ,
            },
            "Probabilités": {
                "Probabilités": [
                        "Loi des grands nombres",
                        "Théorème central limite"
                    ]
                ,
                "Dénombrement": [
                        "Formule de combinaison et permutation"
                    ]
                
            }
        },
        
}}

# Théorèmes et résultats du programme de 2ème Bac SM ajoutés le 28/09/2026 (il manquait notamment
# le TVI). (domaine, chapitre) → noms. Un même nom dans plusieurs chapitres = un seul théorème,
# rattaché à chacun.
THEOREMES_AJOUTES = {
    ("Analyse", "Limites et continuité"): [
        "Théorème des valeurs intermédiaires (TVI)",
        "Théorème de la bijection",
        "Image d'un intervalle par une fonction continue",
        "Continuité de la fonction réciproque",
        "Prolongement par continuité",
        "Limite et continuité d'une fonction composée",
        "Fonction arc tangente",
        "Fonction racine n-ième et puissance rationnelle",
    ],
    ("Analyse", "Dérivation et étude des fonctions"): [
        "Dérivée d'une fonction composée",
        "Dérivée de la fonction réciproque",
        "Inégalité des accroissements finis",
        "Concavité et point d'inflexion",
        "Branches infinies et asymptotes",
    ],
    ("Analyse", "Suites numériques"): [
        "Suite monotone et bornée : convergence",
        "Suites adjacentes",
        "Suites récurrentes u(n+1) = f(u(n))",
        "Théorème des gendarmes",
    ],
    ("Analyse", "Fonctions logarithmiques"): [
        "Limites usuelles du logarithme",
        "Fonction logarithme de base a",
    ],
    ("Analyse", "Fonctions exponentielles"): [
        "Limites usuelles de l'exponentielle",
        "Fonction exponentielle de base a",
    ],
    ("Analyse", "Calcul intégral"): [
        "Intégration par parties",
        "Valeur moyenne d'une fonction",
        "Calcul d'aires et de volumes",
        "Sommes de Riemann",
    ],
    ("Analyse", "Équations différentielles"): [
        "Équation y' = ay + b",
        "Équation y'' + ay' + by = 0",
    ],
    ("Algèbre", "Nombres complexes"): [
        "Formules d'Euler",
        "Racines n-ièmes d'un nombre complexe",
        "Équations du second degré dans ℂ",
        "Transformations du plan : translation, homothétie, rotation",
    ],
    ("Algèbre", "Arithmétique"): [
        "Division euclidienne et congruences",
        "PGCD, PPCM et algorithme d'Euclide",
        "Décomposition en facteurs premiers",
    ],
    ("Algèbre", "Structures algébriques"): [
        "Lois de composition interne",
        "Sous-groupes et morphismes de groupes",
    ],
    ("Algèbre", "Espaces vectoriels"): [
        "Sous-espaces vectoriels",
        "Familles libres et génératrices",
    ],
    ("Probabilités", "Probabilités"): [
        "Probabilité conditionnelle",
        "Formule des probabilités totales",
        "Indépendance d'événements",
        "Variable aléatoire : espérance et variance",
        "Loi binomiale",
    ],
    ("Probabilités", "Dénombrement"): [
        "Arrangements et combinaisons",
        "Formule du binôme de Newton",
    ],
}
for (subfield_name, chapter_name), names in THEOREMES_AJOUTES.items():
    chapters_of = mappings["2bacsm"]["Mathématiques"][subfield_name]
    assert chapter_name in chapters_of, chapter_name
    for name in names:
        if name not in chapters_of[chapter_name]:
            chapters_of[chapter_name].append(name)


# Tronc commun Sciences (option française / BIOF) et 1ère Bac Sciences Mathématiques, ajoutés le
# 29/09/2026 d'après le programme officiel (orientations pédagogiques 2007, chapitres dans l'ordre
# du programme). Un chapitre qui porte le même nom qu'à un autre niveau est partagé (« Suites
# numériques », « Dénombrement », « Généralités sur les fonctions »…) ; ses théorèmes gardent chacun
# leurs niveaux, et le filtre croise niveau ET chapitre.
mappings["tcs"] = {
    "Mathématiques": {
        "Algèbre": {
            "Ensembles de nombres ℕ, ℤ, 𝔻, ℚ et ℝ": [
                "Identités remarquables",
                "Propriétés des puissances",
                "Propriétés des racines carrées",
                "Irrationalité de √2",
            ],
            "Arithmétique dans ℕ": [
                "Critères de divisibilité",
                "Parité de la somme et du produit",
                "Décomposition en facteurs premiers",
                "PGCD et PPCM par la décomposition en facteurs premiers",
            ],
            "Ordre dans ℝ": [
                "Ordre et opérations",
                "Propriétés de la valeur absolue",
                "Inégalité triangulaire",
            ],
            "Polynômes": [
                "Égalité de deux polynômes",
                "Racine d'un polynôme et factorisation par (x − a)",
            ],
            "Équations, inéquations et systèmes": [
                "Discriminant et racines d'un trinôme",
                "Signe du trinôme",
                "Somme et produit des racines",
                "Méthode du déterminant (Cramer) pour un système 2×2",
            ],
        },
        "Analyse": {
            "Calcul trigonométrique": [
                "Relation cos²x + sin²x = 1",
                "Angles associés",
                "Équations trigonométriques de base",
            ],
            "Généralités sur les fonctions": [
                "Fonctions paires et impaires",
                "Sens de variation et taux de variation",
                "Fonctions de référence (x², 1/x, √x, ax² + bx + c, (ax + b)/(cx + d))",
            ],
        },
        "Géométrie": {
            "Calcul vectoriel dans le plan": [
                "Relation de Chasles",
                "Condition de colinéarité de deux vecteurs",
            ],
            "Projection dans le plan": [
                "Théorème de Thalès",
                "Conservation du coefficient de colinéarité par projection",
            ],
            "Droite dans le plan": [
                "Condition de colinéarité par le déterminant",
                "Équation cartésienne et équation réduite d'une droite",
                "Parallélisme de deux droites",
            ],
            "Transformations du plan": [
                "Propriétés de conservation des transformations",
                "Image d'une droite et d'un cercle par une transformation",
            ],
            "Produit scalaire dans le plan": [
                "Théorème d'Al-Kashi",
                "Théorème de la médiane",
                "Caractérisation de l'orthogonalité par le produit scalaire",
            ],
            "Géométrie dans l'espace": [
                "Théorème du toit",
                "Parallélisme d'une droite et d'un plan, de deux plans",
                "Orthogonalité d'une droite et d'un plan",
            ],
        },
        "Statistiques": {
            "Statistiques": [
                "Moyenne, variance et écart type",
            ],
        },
    },
}

mappings["1bacsm"] = {
    "Mathématiques": {
        "Algèbre": {
            "Logique mathématique": [
                "Lois de De Morgan",
                "Raisonnement par contraposée",
                "Raisonnement par l'absurde",
                "Raisonnement par récurrence",
            ],
            "Ensembles et applications": [
                "Opérations sur les ensembles et lois de De Morgan",
                "Composée de deux bijections",
                "Application réciproque d'une bijection",
            ],
            "Arithmétique dans ℤ": [
                "Division euclidienne dans ℤ",
                "Congruences modulo n",
                "PGCD, PPCM et algorithme d'Euclide",
                "Décomposition en facteurs premiers",
                "Infinité des nombres premiers",
            ],
        },
        "Analyse": {
            "Généralités sur les fonctions": [
                "Fonction majorée, minorée, bornée",
                "Monotonie d'une fonction composée",
                "Fonction périodique",
            ],
            "Calcul trigonométrique": [
                "Formules d'addition",
                "Formules de duplication",
                "Transformation de a cos x + b sin x",
                "Formules de transformation somme-produit",
            ],
            "Suites numériques": [
                "Suites arithmétiques et géométriques",
                "Somme de termes consécutifs",
                "Suite majorée, minorée, monotone",
            ],
            "Limites d'une fonction": [
                "Opérations sur les limites",
                "Limites trigonométriques usuelles",
                "Limites et ordre",
                "Théorème des gendarmes",
            ],
            "Dérivation": [
                "Dérivée d'une somme, d'un produit, d'un quotient",
                "Équation de la tangente",
                "Dérivée d'une fonction composée",
                "Signe de la dérivée et sens de variation",
            ],
            "Étude des fonctions": [
                "Branches infinies et asymptotes",
                "Concavité et point d'inflexion",
                "Centre et axe de symétrie d'une courbe",
            ],
        },
        "Géométrie": {
            "Barycentre dans le plan": [
                "Associativité du barycentre",
                "Coordonnées du barycentre",
            ],
            "Produit scalaire dans le plan": [
                "Expression analytique du produit scalaire",
                "Distance d'un point à une droite",
                "Équation d'un cercle",
            ],
            "Rotation dans le plan": [
                "Propriétés de la rotation",
                "Composée de deux symétries axiales",
            ],
            "Vecteurs de l'espace": [
                "Vecteurs coplanaires",
                "Base de l'espace et coordonnées",
            ],
            "Géométrie dans l'espace": [
                "Représentation paramétrique d'une droite",
                "Équation cartésienne d'un plan",
            ],
            "Produit scalaire dans l'espace": [
                "Vecteur normal et équation d'un plan",
                "Équation d'une sphère",
                "Distance d'un point à un plan",
            ],
        },
        "Probabilités": {
            "Dénombrement": [
                "Principe multiplicatif",
                "Arrangements et combinaisons",
                "Formule du binôme de Newton",
                "Triangle de Pascal",
            ],
        },
    },
}

# 2ème Bac Sciences Physiques (option française / BIOF), ajouté le 03/10/2026 d'après le programme
# (12 chapitres, mêmes leçons qu'en 2ème Bac SVT). Les chapitres communs avec le 2ème Bac SM portent le
# même nom (donc partagés) ; seuls les théorèmes au programme de PC y sont rattachés : pas d'arc
# tangente, de suites adjacentes, de racines n-ièmes complexes ni de sommes de Riemann, propres au SM.
mappings["2bacpc"] = {
    "Mathématiques": {
        "Analyse": {
            "Limites et continuité": [
                "Théorème des gendarmes",
                "Théorème des valeurs intermédiaires (TVI)",
                "Théorème de la bijection",
                "Image d'un intervalle par une fonction continue",
                "Continuité de la fonction réciproque",
                "Prolongement par continuité",
                "Limite et continuité d'une fonction composée",
                "Fonction racine n-ième et puissance rationnelle",
            ],
            "Dérivation et étude des fonctions": [
                "Dérivée d'une fonction composée",
                "Dérivée de la fonction réciproque",
                "Concavité et point d'inflexion",
                "Branches infinies et asymptotes",
            ],
            "Suites numériques": [
                "Convergence et divergence",
                "Suites arithmétiques et géométriques",
                "Suite monotone et bornée : convergence",
                "Suites récurrentes u(n+1) = f(u(n))",
                "Théorème des gendarmes",
            ],
            "Fonctions primitives": [
                "Primitives des fonctions usuelles",
                "Primitive d'une fonction continue sur un intervalle",
            ],
            "Fonctions logarithmiques": [
                "Dérivée et propriétés du logarithme",
                "Limites usuelles du logarithme",
                "Fonction logarithme de base a",
            ],
            "Fonctions exponentielles": [
                "Dérivée et propriétés de l'exponentielle",
                "Limites usuelles de l'exponentielle",
                "Fonction exponentielle de base a",
            ],
            "Calcul intégral": [
                "Théorème fondamental de l'analyse",
                "Primitives et techniques d'intégration",
                "Intégration par parties",
                "Valeur moyenne d'une fonction",
                "Calcul d'aires et de volumes",
            ],
            "Équations différentielles": [
                "Équation y' = ay + b",
                "Équation y'' + ay' + by = 0",
            ],
        },
        "Algèbre": {
            "Nombres complexes": [
                "Forme trigonométrique et exponentielle",
                "Théorème de Moivre",
                "Formules d'Euler",
                "Équations du second degré dans ℂ",
                "Transformations du plan : translation, homothétie, rotation",
            ],
        },
        "Géométrie": {
            "Produit scalaire dans l'espace": [
                "Vecteur normal et équation d'un plan",
                "Équation d'une sphère",
                "Distance d'un point à un plan",
            ],
            "Produit vectoriel": [
                "Expression analytique du produit vectoriel",
                "Distance d'un point à une droite dans l'espace",
            ],
        },
        "Probabilités": {
            "Dénombrement": [
                "Principe multiplicatif",
                "Arrangements et combinaisons",
            ],
            "Probabilités": [
                "Probabilité conditionnelle",
                "Formule des probabilités totales",
                "Indépendance d'événements",
                "Variable aléatoire : espérance et variance",
                "Loi binomiale",
            ],
        },
    },
}

TAXONOMIE = {
    "Tronc commun Sciences": mappings["tcs"],
    "1ère Bac SM": mappings["1bacsm"],
    "2ème Bac SM": mappings["2bacsm"],
    "2ème Bac PC": mappings["2bacpc"],
}

# « order » est unique : un nouveau niveau naît en fin de liste, puis on remet tout dans l'ordre de
# NIVEAUX en passant par des valeurs provisoires (sinon deux niveaux voudraient le même rang).
def _free_order():
    return (max(ClassLevel.objects.values_list('order', flat=True), default=0) or 0) + 1


levels = {}
for name, _ in NIVEAUX:
    level = ClassLevel.objects.filter(name=name).first() or ClassLevel.objects.create(name=name, order=_free_order())
    levels[name] = level
wanted = dict(NIVEAUX)
if any(level.order != wanted[name] for name, level in levels.items()):
    base = _free_order() + 1000
    for i, level in enumerate(levels.values()):
        level.order = base + i
        level.save(update_fields=['order'])
    for name, level in levels.items():
        level.order = wanted[name]
        level.save(update_fields=['order'])

for level_name, subjects in TAXONOMIE.items():
    level = levels[level_name]
    for subject_name, subfields in subjects.items():
        subject, _ = Subject.objects.get_or_create(name=subject_name)
        subject.class_levels.add(level)
        for subfield_name, chapters in subfields.items():
            subfield, _ = Subfield.objects.get_or_create(name=subfield_name, subject=subject)
            subfield.class_levels.add(level)
            for chapter_name, theorems in chapters.items():
                chapter, _ = Chapter.objects.get_or_create(name=chapter_name, subject=subject, subfield=subfield)
                chapter.class_levels.add(level)
                for theorem_name in theorems:
                    theorem, _ = Theorem.objects.get_or_create(name=theorem_name, subject=subject, subfield=subfield)
                    theorem.chapters.add(chapter)
                    theorem.class_levels.add(level)

logger.info("Taxonomie à jour : %d niveau(x), %d chapitre(s)", len(levels), Chapter.objects.count())
