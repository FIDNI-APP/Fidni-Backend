# Generated migration for NotebookAnnotation model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('notebooks', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotebookAnnotation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('annotation_id', models.CharField(max_length=100)),
                ('annotation_type', models.CharField(choices=[('highlight', 'Surlignage'), ('note', 'Note'), ('pen', 'Dessin')], max_length=20)),
                ('position_x', models.FloatField()),
                ('position_y', models.FloatField()),
                ('width', models.FloatField(blank=True, null=True)),
                ('height', models.FloatField(blank=True, null=True)),
                ('color', models.CharField(default='#ffeb3b', max_length=7)),
                ('content', models.TextField(blank=True)),
                ('path_data', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('lesson', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='annotations', to='things.lesson')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notebook_annotations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='notebookannotation',
            constraint=models.UniqueConstraint(fields=('user', 'lesson', 'annotation_id'), name='unique_user_lesson_annotation'),
        ),
    ]