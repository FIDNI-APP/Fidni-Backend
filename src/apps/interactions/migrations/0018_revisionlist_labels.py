# Étiquettes facultatives des listes de révision (niveau, matière, chapitres), pour les filtrer.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('caracteristics', '0002_school'),
        ('interactions', '0017_remove_unused_report_evaluate'),
    ]

    operations = [
        migrations.AddField(
            model_name='revisionlist',
            name='class_levels',
            field=models.ManyToManyField(blank=True, related_name='revision_lists', to='caracteristics.classlevel'),
        ),
        migrations.AddField(
            model_name='revisionlist',
            name='subjects',
            field=models.ManyToManyField(blank=True, related_name='revision_lists', to='caracteristics.subject'),
        ),
        migrations.AddField(
            model_name='revisionlist',
            name='chapters',
            field=models.ManyToManyField(blank=True, related_name='revision_lists', to='caracteristics.chapter'),
        ),
    ]
