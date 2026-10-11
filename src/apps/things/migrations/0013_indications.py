# « Méthode : » en tête des solutions → indication de la question (champ `hint`, bouton « Indication »).
# Réversible : le retour arrière remet la méthode en tête de chaque solution.
from django.db import migrations

from apps.things.structure_utils import merge_hints_into_solutions, move_methods_to_hints


def _apply(apps, fn):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.exclude(json_content__isnull=True).only('id', 'json_content').iterator():
        js = c.json_content
        if isinstance(js, dict) and fn(js):
            Content.objects.filter(pk=c.pk).update(json_content=js)  # sans toucher updated_at


def forwards(apps, schema_editor):
    _apply(apps, move_methods_to_hints)


def backwards(apps, schema_editor):
    _apply(apps, merge_hints_into_solutions)


class Migration(migrations.Migration):

    dependencies = [
        ("things", "0012_reponse_signalement"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
