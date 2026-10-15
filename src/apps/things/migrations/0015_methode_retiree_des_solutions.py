# Solutions qui commençaient par « Méthode : » alors que la question avait déjà son indication : le site montrait
# « Indication » puis « Méthode » (doublon). La méthode est retirée de la solution, l'indication reste.
# Le retour arrière ne remet rien (l'indication écrite à part suffit).
from django.db import migrations

from apps.things.structure_utils import move_methods_to_hints


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.exclude(json_content__isnull=True).only('id', 'json_content').iterator():
        js = c.json_content
        if isinstance(js, dict) and move_methods_to_hints(js):
            Content.objects.filter(pk=c.pk).update(json_content=js)  # sans toucher updated_at


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0014_content_school'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
