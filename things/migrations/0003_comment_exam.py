# Generated by Django 5.0.1 on 2025-05-30 22:24

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0002_exam_chapters_exam_class_levels_exam_difficulty_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='comment',
            name='exam',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='comments', to='things.exam'),
        ),
    ]
