# Modèles jamais utilisés (tables vides en production le 2026-09-28) : « signaler un
# contenu » (Report) et « difficulté ressentie » (Evaluate). Supprimer directement les
# tables ; retirer les champs un à un d'abord échoue sur SQLite (index sur content_type).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('interactions', '0016_remove_exam_author_remove_exam_chapters_and_more'),
    ]

    operations = [
        migrations.DeleteModel(name='Evaluate'),
        migrations.DeleteModel(name='Report'),
    ]
