# Generated migration for skilliq app
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('caracteristics', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SkillQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question', models.TextField()),
                ('options', models.JSONField(help_text='List of answer options')),
                ('correct_answer', models.PositiveSmallIntegerField(help_text='Index of correct answer (0-based)')),
                ('difficulty', models.CharField(choices=[('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')], default='medium', max_length=10)),
                ('explanation', models.TextField(blank=True, help_text='Explanation shown after answering')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('chapter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='skill_questions', to='caracteristics.chapter')),
            ],
            options={
                'ordering': ['difficulty', 'id'],
            },
        ),
        migrations.CreateModel(
            name='SkillAssessment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.PositiveSmallIntegerField(default=0)),
                ('max_score', models.PositiveSmallIntegerField(default=0)),
                ('level', models.CharField(choices=[('beginner', 'Beginner'), ('intermediate', 'Intermediate'), ('advanced', 'Advanced'), ('expert', 'Expert')], default='beginner', max_length=20)),
                ('answers', models.JSONField(default=dict, help_text="Question ID -> user's answer index")),
                ('time_spent', models.PositiveIntegerField(default=0, help_text='Time spent in seconds')),
                ('completed_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('chapter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assessments', to='caracteristics.chapter')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='skill_assessments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-completed_at'],
                'unique_together': {('user', 'chapter')},
            },
        ),
    ]
