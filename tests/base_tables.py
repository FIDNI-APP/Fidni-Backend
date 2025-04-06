import os
import sys
import django

# Add backend directory to sys.path so Python can find it
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")  # Update with your project name

# Setup Django
django.setup()

# Now import models
from caracteristics.models import ClassLevel, Subject, Chapter, Subfield, Theorem

import logging

logger = logging.getLogger('django')


bac_math = ClassLevel.objects.get_or_create(name="2ème Bac SM", order=1)[0]
bac_phys = ClassLevel.objects.get_or_create(name="2ème Bac PC", order=2)[0]





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
                "Suites numériques": [
                        "Convergence et divergence",
                        "Suites arithmétiques et géométriques"
                    ]
                ,
                "Fonctions logarithmiques et exponentielles": [
                        "Dérivée et propriétés du logarithme et de l'exponentielle"
                    ]
                ,
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
        "Physique": {
            "Mécanique": {
                "Lois de Newton": [
                        "Principe d'inertie",
                        "Principe fondamental de la dynamique"
                    ]
                ,
                "Mouvements plans": [
                        "Mouvement parabolique",
                        "Mouvement circulaire uniforme"
                    ]
                ,
                "Mouvement des satellites et des planètes": [
                        "Loi de la gravitation universelle",
                        "Lois de Kepler"
                    ]
                ,
                "Mouvement de rotation d'un solide autour d'un axe fixe": [
                        "Théorème du moment cinétique",
                        "Moment d'inertie"
                    ]
                
            },
            "Electricité": {
                "Dipôle RC": [
                        "Charge et décharge d'un condensateur",
                        "Constante de temps"
                    ]
                ,
                "Dipôle RL": [
                        "Établissement et interruption du courant",
                        "Inductance et auto-induction"
                    ]
                ,
                "Oscillations libres d'un circuit RLC série": [
                        "Régime sinusoïdal forcé",
                        "Résonance électrique"
                    ]
                ,
                "Ondes électromagnétiques": [
                        "Propagation et caractéristiques",
                        "Spectre électromagnétique"
                    ]
                
            }
        },
        "Chimie": {
            "Transformations chimiques": {"Transformations chimiques": [
                    "Équilibre chimique et loi d'action de masse",
                    "Théories acide-base",
                    "Oxydoréduction et potentiel standard"
                ]
            
        }
    }
}}




for subject_name, subfields in mappings["2bacsm"].items():
    subject, _ = Subject.objects.get_or_create(name=subject_name)
    subject.class_levels.add(bac_math)
    logger.info(subject)
    logger.info(subfields)



    # 3️⃣ Création des domaines (Subfields)
    for subfield_name, chapters in subfields.items():
        subfield, _ = Subfield.objects.get_or_create(name=subfield_name, subject=subject)
        subfield.class_levels.add(bac_math)
        logger.info(subfield)
        logger.info(chapters)

        # 4️⃣ Création des chapitres
        for chapter_name, theorems in chapters.items():
            chapter, _ = Chapter.objects.get_or_create(name=chapter_name, subject=subject, subfield=subfield)
            chapter.class_levels.add(bac_math)
            logger.info(chapter)
            logger.info(theorems)
            logger.info(subject)

            # 5️⃣ Création des théorèmes et association aux chapitres
            for theorem_name in theorems:
                theorem, _ = Theorem.objects.get_or_create(name=theorem_name, subject=subject, subfield=subfield)
                theorem.chapters.add(chapter)
                theorem.class_levels.add(bac_math)

# for subject_name, subfields in mappings["2bacpc"].items():
#     subject, _ = Subject.objects.get_or_create(name=subject_name)
#     subject.class_levels.add(bac_phys)

#     # 3️⃣ Création des domaines (Subfields)
#     for subfield_name, chapters in subfields.items():
#         subfield, _ = Subfield.objects.get_or_create(name=subfield_name, subject=subject)
#         subfield.class_levels.add(bac_phys)

#         # 4️⃣ Création des chapitres
#         for chapter_name, theorems in chapters.items():
#             chapter, _ = Chapter.objects.get_or_create(name=chapter_name, subject=subject, subfield=subfield, order=1)
#             chapter.class_levels.add(bac_phys)

#             # 5️⃣ Création des théorèmes et association aux chapitres
#             for theorem_name in theorems:
#                 theorem, _ = Theorem.objects.get_or_create(name=theorem_name, subject=subject, subfield=subfield)
#                 theorem.chapters.add(chapter)
#                 theorem.class_levels.add(bac_phys)

logger.info("✅ Données insérées avec succès !")