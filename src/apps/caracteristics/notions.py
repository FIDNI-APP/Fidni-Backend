"""Référentiel des notions (étiquettes « notions » des questions, qui alimentent Skill IQ et l'onglet
Activité).

Liste FERMÉE : l'import refuse une notion absente d'ici et l'éditeur ne propose que celles-ci, pour
que la même notion porte toujours le même identifiant (sinon les statistiques se dispersent entre
« derivee », « derivation », « derivee-fonction »…).

Rangées par chapitre (nom exact de la taxonomie, backend/tests/base_tables.py) pour que l'éditeur
propose d'abord celles du chapitre ; une notion reste utilisable dans n'importe quel chapitre.

Ajouter une notion : une ligne ici (identifiant court en minuscules-avec-tirets, libellé). Ne jamais
renommer un identifiant déjà utilisé : les questions existantes le portent.
"""

TRANSVERSAL = 'Méthodes transversales'

NOTIONS: dict[str, dict[str, str]] = {
    TRANSVERSAL: {
        'calcul-algebrique': 'Calcul algébrique',
        'equations': 'Équations et inéquations',
        'signe': 'Étude de signe',
        'encadrement': 'Encadrement et inégalités',
        'valeur-absolue': 'Valeur absolue',
        'partie-entiere': 'Partie entière',
        'somme-telescopique': 'Somme télescopique',
        'equation-fonctionnelle': 'Équation fonctionnelle',
        'recurrence': 'Raisonnement par récurrence',
        'raisonnement-absurde': 'Raisonnement par l’absurde',
        'contraposee': 'Raisonnement par contraposée',
        'disjonction-cas': 'Disjonction des cas',
    },

    # ─────────────────────────────── Tronc commun Sciences
    'Ensembles de nombres ℕ, ℤ, 𝔻, ℚ et ℝ': {
        'ensembles-nombres': 'Ensembles de nombres',
        'puissances': 'Puissances',
        'racines-carrees': 'Racines carrées',
        'identites-remarquables': 'Identités remarquables',
    },
    'Arithmétique dans ℕ': {
        'multiples-diviseurs': 'Multiples et diviseurs',
        'nombres-pairs-impairs': 'Nombres pairs et impairs',
        'criteres-divisibilite': 'Critères de divisibilité',
        'nombres-premiers': 'Nombres premiers',
        'decomposition-facteurs-premiers': 'Décomposition en facteurs premiers',
        'pgcd-ppcm': 'PGCD et PPCM',
    },
    'Ordre dans ℝ': {
        'ordre-operations': 'Ordre et opérations',
        'intervalles': 'Intervalles',
        'valeurs-approchees': 'Valeurs approchées',
    },
    'Polynômes': {
        'polynomes': 'Polynômes',
        'racines-polynome': 'Racines d’un polynôme',
        'factorisation': 'Factorisation',
    },
    'Équations, inéquations et systèmes': {
        'second-degre': 'Équations du second degré',
        'signe-trinome': 'Signe du trinôme',
        'systemes': 'Systèmes d’équations',
    },
    'Calcul trigonométrique': {
        'cercle-trigonometrique': 'Cercle trigonométrique',
        'formules-trigonometriques': 'Formules trigonométriques',
        'equations-trigonometriques': 'Équations et inéquations trigonométriques',
        'a-cos-b-sin': 'Transformation de a cos x + b sin x',
    },
    'Généralités sur les fonctions': {
        'domaine-definition': 'Domaine de définition',
        'parite': 'Parité d’une fonction',
        'monotonie': 'Monotonie',
        'extremums': 'Extremums',
        'fonctions-reference': 'Fonctions de référence',
        'composition-fonctions': 'Composée de fonctions',
        'fonction-bornee': 'Fonction majorée, minorée, bornée',
        'periodicite': 'Fonction périodique',
        'representation-graphique': 'Représentation graphique',
    },
    'Calcul vectoriel dans le plan': {
        'vecteurs': 'Vecteurs et opérations',
        'colinearite': 'Colinéarité',
    },
    'Projection dans le plan': {
        'projection': 'Projection',
        'thales': 'Théorème de Thalès',
    },
    'Droite dans le plan': {
        'repere-coordonnees': 'Repère et coordonnées',
        'equation-droite': 'Équation d’une droite',
        'positions-droites': 'Positions relatives de deux droites',
    },
    'Transformations du plan': {
        'translation': 'Translation',
        'homothetie': 'Homothétie',
        'symetries': 'Symétries',
    },
    'Produit scalaire dans le plan': {
        'produit-scalaire': 'Produit scalaire',
        'orthogonalite': 'Orthogonalité',
        'relations-metriques': 'Relations métriques dans le triangle',
        'equation-cercle': 'Équation d’un cercle',
        'distance-point-droite': 'Distance d’un point à une droite',
    },
    'Géométrie dans l\'espace': {
        'positions-espace': 'Positions relatives dans l’espace',
        'parallelisme-espace': 'Parallélisme dans l’espace',
        'orthogonalite-espace': 'Orthogonalité dans l’espace',
        'representation-parametrique': 'Représentation paramétrique d’une droite',
        'equation-plan': 'Équation cartésienne d’un plan',
    },
    'Statistiques': {
        'parametres-position': 'Moyenne, médiane, mode',
        'parametres-dispersion': 'Variance et écart type',
    },

    # ─────────────────────────────── 1ère Bac SM
    'Logique mathématique': {
        'connecteurs-logiques': 'Propositions et connecteurs logiques',
        'quantificateurs': 'Quantificateurs',
    },
    'Ensembles et applications': {
        'operations-ensembles': 'Opérations sur les ensembles',
        'injection-surjection': 'Injection et surjection',
        'image-directe-reciproque': 'Image directe et image réciproque',
    },
    'Arithmétique dans ℤ': {
        'divisibilite': 'Divisibilité',
        'division-euclidienne': 'Division euclidienne',
        'congruences': 'Congruences',
    },
    'Barycentre dans le plan': {
        'barycentre': 'Barycentre',
        'lignes-niveau': 'Lignes de niveau',
    },
    'Rotation dans le plan': {
        'angles-orientes': 'Angles orientés',
        'rotation': 'Rotation',
    },
    'Suites numériques': {
        'suite-arithmetique': 'Suite arithmétique',
        'suite-geometrique': 'Suite géométrique',
        'suite-bornee-monotone': 'Suite majorée, minorée, monotone',
        'suite-recurrente': 'Suite récurrente',
        'limite-suite': 'Limite d’une suite',
        'suites-adjacentes': 'Suites adjacentes',
    },
    'Limites d\'une fonction': {
        'limites': 'Limites',
        'formes-indeterminees': 'Formes indéterminées',
        'expression-conjuguee': 'Expression conjuguée',
        'limites-trigonometriques': 'Limites trigonométriques',
    },
    'Dérivation': {
        'derivee': 'Dérivée',
        'tangente': 'Nombre dérivé et tangente',
        'derivee-composee': 'Dérivée d’une composée',
    },
    'Étude des fonctions': {
        'tableau-variations': 'Tableau de variations',
        'branches-infinies': 'Branches infinies et asymptotes',
        'concavite': 'Concavité et point d’inflexion',
        'symetrie-courbe': 'Centre et axe de symétrie',
        'position-relative-courbes': 'Position relative de courbes',
    },
    'Vecteurs de l\'espace': {
        'vecteurs-espace': 'Vecteurs de l’espace',
        'coplanarite': 'Vecteurs coplanaires',
    },
    'Dénombrement': {
        'principe-multiplicatif': 'Principe multiplicatif',
        'arrangements': 'Arrangements',
        'permutations': 'Permutations',
        'combinaisons': 'Combinaisons',
        'binome-newton': 'Binôme de Newton',
    },
    'Produit scalaire dans l\'espace': {
        'produit-scalaire-espace': 'Produit scalaire dans l’espace',
        'vecteur-normal': 'Vecteur normal et équation d’un plan',
        'sphere': 'Sphère',
        'distance-point-plan': 'Distance d’un point à un plan',
    },

    # ─────────────────────────────── 2ème Bac SM
    'Limites et continuité': {
        'continuite': 'Continuité',
        'prolongement-continuite': 'Prolongement par continuité',
        'tvi': 'Théorème des valeurs intermédiaires',
        'dichotomie': 'Dichotomie',
        'point-fixe': 'Point fixe',
        'bijection': 'Bijection',
        'fonction-reciproque': 'Fonction réciproque',
        'arctan': 'Fonction arc tangente',
        'racine-nieme': 'Racine n-ième',
    },
    'Dérivation et étude des fonctions': {
        'derivee-reciproque': 'Dérivée de la fonction réciproque',
        'rolle': 'Théorème de Rolle',
        'accroissements-finis': 'Accroissements finis',
    },
    'Fonctions logarithmiques': {
        'logarithme': 'Fonction logarithme',
        'limites-logarithme': 'Limites du logarithme',
    },
    'Fonctions exponentielles': {
        'exponentielle': 'Fonction exponentielle',
        'limites-exponentielle': 'Limites de l’exponentielle',
    },
    'Équations différentielles': {
        'equa-diff-ordre-1': 'Équation y′ = ay + b',
        'equa-diff-ordre-2': 'Équation y″ + ay′ + by = 0',
    },
    'Calcul intégral': {
        'primitives': 'Primitives',
        'integrale': 'Intégrale',
        'integration-parties': 'Intégration par parties',
        'aires-volumes': 'Calcul d’aires et de volumes',
        'valeur-moyenne': 'Valeur moyenne',
        'sommes-riemann': 'Sommes de Riemann',
    },
    'Nombres complexes': {
        'forme-algebrique': 'Forme algébrique',
        'module-argument': 'Module et argument',
        'forme-trigonometrique': 'Forme trigonométrique et exponentielle',
        'second-degre-complexe': 'Équations du second degré dans ℂ',
        'racines-n-iemes-complexes': 'Racines n-ièmes d’un complexe',
        'complexes-geometrie': 'Complexes et géométrie',
    },
    'Arithmétique': {
        'bezout': 'Théorème de Bézout',
        'gauss': 'Théorème de Gauss',
        'fermat': 'Petit théorème de Fermat',
    },
    'Structures algébriques': {
        'lois-composition': 'Lois de composition interne',
        'groupes': 'Groupes',
        'anneaux-corps': 'Anneaux et corps',
        'morphismes': 'Morphismes',
    },
    'Espaces vectoriels': {
        'sous-espace-vectoriel': 'Sous-espace vectoriel',
        'famille-libre-generatrice': 'Famille libre, génératrice',
        'base-dimension': 'Base et dimension',
    },
    'Probabilités': {
        'probabilite-conditionnelle': 'Probabilité conditionnelle',
        'probabilites-totales': 'Probabilités totales',
        'independance': 'Indépendance',
        'variable-aleatoire': 'Variable aléatoire',
        'loi-binomiale': 'Loi binomiale',
    },
    # ─────────────────────────────── 2ème Bac PC (chapitres propres ; les autres sont communs avec le SM)
    'Fonctions primitives': {
        'primitives-usuelles': 'Primitives des fonctions usuelles',
    },
    'Produit vectoriel': {
        'produit-vectoriel': 'Produit vectoriel',
    },
}


def all_notions() -> dict[str, dict]:
    """identifiant → {'label', 'chapter'} (chapitre de rangement ; None pour les transversales)."""
    out: dict[str, dict] = {}
    for chapter, notions in NOTIONS.items():
        for slug, label in notions.items():
            if slug in out:
                raise ValueError(f'notion « {slug} » rangée deux fois')
            out[slug] = {'label': label, 'chapter': None if chapter == TRANSVERSAL else chapter}
    return out


NOTION_INDEX = all_notions()


def closest_notions(text: str, n: int = 3) -> list[str]:
    """Identifiants les plus proches d'une notion inconnue (sur l'identifiant ET le libellé)."""
    import difflib
    import unicodedata

    def fold(s: str) -> str:
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
        return ''.join(c if c.isalnum() else ' ' for c in s).strip()

    target = fold(text)

    def score(slug: str) -> float:
        best = 0.0
        for cand in (fold(slug), fold(NOTION_INDEX[slug]['label'])):
            ratio = difflib.SequenceMatcher(None, target, cand).ratio()
            prefix = len(target) >= 4 and cand[:5] == target[:5]
            best = max(best, ratio + (0.3 if prefix else 0))
        return best

    ranked = sorted(NOTION_INDEX, key=score, reverse=True)
    return [slug for slug in ranked[:n] if score(slug) >= 0.5]


def notion_label(slug: str) -> str:
    entry = NOTION_INDEX.get(slug)
    return entry['label'] if entry else slug.replace('-', ' ').capitalize()
