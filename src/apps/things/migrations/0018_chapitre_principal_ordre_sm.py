# 2ème Bac SM : la dérivation passe avant les suites dans l'ordre du programme (Natsu, 16/10/2026 : ordre suivi par
# M. Haddar). La règle « dernier chapitre du programme utilisé » (0017) est rejouée avec ce nouvel ordre : chapitres
# retirés remis, puis la règle réappliquée.
import importlib

from django.db import migrations

_m17 = importlib.import_module('apps.things.migrations.0017_chapitre_principal')


def forwards(apps, schema_editor):
    _m17.backwards(apps, schema_editor)
    _m17.forwards(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0017_chapitre_principal'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
