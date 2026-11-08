# Reprise complémentaire des commentaires (08/11/2026) : ceux écrits sous les contenus entre la mise en ligne du
# serveur des discussions (0002) et celle du site sans discussion en bas de page rejoignent l'espace Discussions.
# Même reprise que 0002 (rejouable, sans doublon : legacy_comment_id) ; c'est la commande reprendre_commentaires,
# jouée au déploiement. Retour arrière : rien à faire (0002 défait toute la reprise).
import importlib

from django.db import migrations


def rattraper(apps, schema_editor):
    importlib.import_module('apps.discussions.migrations.0002_reprise_commentaires').reprendre(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('discussions', '0002_reprise_commentaires'),
    ]

    operations = [
        migrations.RunPython(rattraper, migrations.RunPython.noop),
    ]
