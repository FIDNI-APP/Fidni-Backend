# Generated by Django 5.1.6 on 2025-02-28 20:51

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0003_exercise_subfield'),
    ]

    operations = [
        migrations.RenameField(
            model_name='exercise',
            old_name='subfield',
            new_name='subfields',
        ),
    ]
