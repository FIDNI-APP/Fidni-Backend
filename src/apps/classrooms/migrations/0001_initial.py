# Generated migration for classrooms app
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('caracteristics', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Classroom',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('description', models.TextField(blank=True)),
                ('join_code', models.CharField(db_index=True, max_length=12, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('class_level', models.ForeignKey(blank=True, null=True,
                                                  on_delete=django.db.models.deletion.SET_NULL,
                                                  related_name='classrooms',
                                                  to='caracteristics.classlevel')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                            related_name='owned_classrooms',
                                            to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ClassroomSubject',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                related_name='subjects',
                                                to='classrooms.classroom')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='classroom_subjects',
                                              to='caracteristics.subject')),
                ('teacher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='taught_classroom_subjects',
                                              to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['subject__name'],
                'unique_together': {('classroom', 'subject')},
            },
        ),
        migrations.CreateModel(
            name='ClassroomMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('joined_at', models.DateTimeField(default=timezone.now)),
                ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                related_name='memberships',
                                                to='classrooms.classroom')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='classroom_memberships',
                                              to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-joined_at'],
                'unique_together': {('classroom', 'student')},
            },
        ),
        migrations.AddIndex(
            model_name='classroommembership',
            index=models.Index(fields=['student'], name='classrooms__student_idx'),
        ),
        migrations.AddIndex(
            model_name='classroommembership',
            index=models.Index(fields=['classroom'], name='classrooms__classr_idx'),
        ),
    ]
