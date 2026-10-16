# Second lot de chapitres remis à la main (Natsu, 16/10/2026) : DS de synthèse de M. Belkhatir (les bonus ne comptent
# pas pour le classement), exercices 4 et 5 de la série 2PC (ni dérivabilité en un point ni f″), exercice 10 de 1ère
# Bac SM (« A ≠ ∅ ou B ≠ ∅ » : de la logique). Mêmes clés dans importing.CHAPITRES_FORCES (brouillons encore en
# attente). Retour arrière : rien.
from django.db import migrations

CORRECTIONS = {
    'ds-synthese1-2sm-2026-belkhatir': ['Limites et continuité'],
    'etude-fonctions-2pc-serie-ex4': ['Limites et continuité'],
    'etude-fonctions-2pc-serie-ex5': ['Limites et continuité'],
    'logique-ens-app-1sm-ex10': ['Logique mathématique'],
}


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    Chapter = apps.get_model('caracteristics', 'Chapter')
    for cle, noms in CORRECTIONS.items():
        for c in Content.objects.filter(json_content__import__cle=cle):
            chapitres = []
            for lvl in c.class_levels.all():
                for nom in noms:
                    ch = Chapter.objects.filter(name=nom, class_levels=lvl).first()
                    if ch and ch not in chapitres:
                        chapitres.append(ch)
            if chapitres:
                c.chapters.set(chapitres)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0019_chapitres_corriges'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
