# Recalibrage de la difficulté affichée (Natsu, 07/11/2026), d'après le rapport d'usage du 07/11 : cinq contenus
# nettement plus réussis que leur difficulté ne le dit (borne de Wilson à 80 % hors de la bande affichée).
# Prudence : l'auto-évaluation est optimiste (réussite moyenne vers 85 % quelle que soit la difficulté). Un contenu
# descend jusqu'à la bande la plus haute que son intervalle de confiance touche encore :
#   #120 [73 %, 100 %], #57 [79 %, 100 %], #293 [70 %, 93 %] → Facile ;
#   #16 [58 %, 95 %], #191 [52 %, 88 %] → Moyen (pas Facile : l'intervalle déborde encore sur Moyen).
# Seulement si la difficulté est toujours celle du rapport (corrigée à la main depuis : on n'y touche pas).
# Retour arrière : la difficulté d'avant.
from django.db import migrations

CHANGEMENTS = [  # (id, difficulté du rapport, nouvelle difficulté)
    (120, 'hard', 'easy'),
    (57, 'medium', 'easy'),
    (293, 'medium', 'easy'),
    (16, 'hard', 'medium'),
    (191, 'hard', 'medium'),
]


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for pk, avant, apres in CHANGEMENTS:
        Content.objects.filter(pk=pk, difficulty=avant).update(difficulty=apres)


def backwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for pk, avant, apres in CHANGEMENTS:
        Content.objects.filter(pk=pk, difficulty=apres).update(difficulty=avant)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0025_lecons_deux_niveaux'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
