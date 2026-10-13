"""Seuils de « Ma progression » (apps/users/maitrise.py, objectif.py), tous ici (13/10/2026).

PROVISOIRES : à ajuster avec les avis des élèves (« Ce diagnostic te semble juste ? », Pilotage › Usage, carte
« Avis sur les diagnostics ») et l'audit d'usage. Changer une valeur ici suffit (tests : tests/checks/check_maitrise.py).
"""

# ── Un chapitre est-il évalué ?
MIN_QUESTIONS = 4             # questions évaluées (état courant) ; en dessous : « Pas encore évalué »
SELF_WEIGHT = 0.6             # maîtrise = 60 % auto-évaluation + 40 % quiz du chapitre (si quiz), comme avant

# ── États
SEUIL_MAITRISE = 80           # % : nécessaire pour « Maîtrisé », pas suffisant (critères de couverture)
SEUIL_BONNE_VOIE = 60         # %
SEUIL_RENFORCER = 40          # % : en dessous, « À renforcer » (sauf résultats récents bien meilleurs)
MIN_QUESTIONS_MAITRISE = 6
MIN_EXERCICES_MAITRISE = 2    # exercices différents réussis
EXERCICE_REUSSI = 60          # % de réussite d'un exercice (sur ses questions du chapitre) pour le compter réussi
MAX_NOTIONS_EXIGEES = 3       # notions différentes réussies : min(3, notions présentes dans les exercices)
AUTONOMIE_SUFFISANTE = 60     # % de réussites sans aide (quand l'aide est connue)

# ── Résultats récents et tendance
RECENTS_N = 10                # les 10 dernières questions évaluées…
RECENTS_JOURS = 30            # …des 30 derniers jours
RECENTS_MIN = 6               # comptés à partir de 6 questions
HAUSSE_MIN = 10               # pts en 30 jours : « en hausse »

# ── Maîtrise durable et autonomie
DELAI_DURABLE_JOURS = 3       # revérifier au moins 3 jours après une réussite, sur d'autres questions, sans aide
MIN_AUTONOMIE = 5             # réussites dont l'aide est connue, pour afficher « Je sais résoudre seul »
MIN_TRANSFERT = 3             # essais après une aide, pour afficher « Je m'en passe de plus en plus »
TRANSFERT_JOURS = 14          # la question suivante doit venir dans les 14 jours

# ── Évolution sur 30 jours (aperçu)
EVOLUTION_JOURS = 30
MIN_CHAPITRES_COMPARES = 2    # chapitres évalués aux deux dates
MIN_QUESTIONS_PERIODE = 6     # questions évaluées pendant la période
SURTOUT_FACILE = 70           # % des réussites de la période en « facile » : mise en garde
CONCENTRE = 60                # % du gain venu d'un seul chapitre : mise en garde
SERIE_SEMAINES = 8

# ── Régularité (au second plan)
REGULARITE_JOURS = 28
ACTIF_MIN_SECONDES = 60       # un jour « actif » : au moins une minute d'étude, une évaluation ou une aide ouverte

# ── Prochain objectif
DS_PRIORITE_JOURS = 7         # un DS dans 7 jours au plus oriente l'objectif
OBJECTIF_EXERCICES = 5
VERIFIER_EXERCICES = 3
EVALUER_EXERCICES = 3
