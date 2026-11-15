"""Ordre des exercices d'une série (15/11/2026) : `position`, rempli dans l'ordre d'ajout (le plus ancien d'abord),
c'est-à-dire l'ordre choisi dans le panneau « Série d'exercices » au moment de la créer."""
from django.db import migrations, models


def remplir(apps, schema_editor):
    Item = apps.get_model('interactions', 'RevisionListItem')
    courant, n, lot = None, 0, []
    for item in Item.objects.order_by('revision_list_id', 'added_at', 'id').only('id', 'revision_list_id'):
        if item.revision_list_id != courant:
            courant, n = item.revision_list_id, 0
        n += 1
        item.position = n
        lot.append(item)
    Item.objects.bulk_update(lot, ['position'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('interactions', '0024_journal_reprise'),
    ]

    operations = [
        migrations.AddField(
            model_name='revisionlistitem',
            name='position',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name='revisionlistitem',
            options={'ordering': ['position', 'added_at', 'id']},
        ),
        migrations.RunPython(remplir, migrations.RunPython.noop),
    ]
