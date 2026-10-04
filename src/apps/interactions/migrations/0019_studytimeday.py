# Temps d'étude jour par jour (statistiques par période). Reprise de l'existant : le cumul de chaque
# contenu est rattaché au jour de sa dernière mise à jour.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def reprise(apps, schema_editor):
    Tracker = apps.get_model('interactions', 'StudyTimeTracker')
    Day = apps.get_model('interactions', 'StudyTimeDay')
    rows = [Day(user_id=t.user_id, object_id=t.object_id, date=t.recorded_at.date(), seconds=t.time_spent_seconds)
            for t in Tracker.objects.filter(time_spent_seconds__gt=0).iterator()]
    Day.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('interactions', '0018_revisionlist_labels'),
    ]

    operations = [
        migrations.CreateModel(
            name='StudyTimeDay',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.PositiveIntegerField()),
                ('date', models.DateField()),
                ('seconds', models.PositiveIntegerField(default=0)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='study_time_days', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user', 'object_id', 'date')},
                'indexes': [models.Index(fields=['user', 'date'], name='studytimeday_user_date')],
            },
        ),
        migrations.RunPython(reprise, migrations.RunPython.noop),
    ]
