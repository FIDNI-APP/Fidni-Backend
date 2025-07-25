# Generated by Django 5.0.1 on 2025-07-20 13:36

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('caracteristics', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Exam',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('content', models.TextField()),
                ('difficulty', models.CharField(choices=[('easy', 'easy'), ('medium', 'medium'), ('hard', 'hard')], max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('view_count', models.PositiveIntegerField(default=0)),
                ('is_national_exam', models.BooleanField(default=False, help_text='Indicates if this exam is a national exam')),
                ('national_year', models.PositiveIntegerField(blank=True, help_text='Year of the exam if it is a national exam (YYYY format)', null=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exams', to=settings.AUTH_USER_MODEL)),
                ('chapters', models.ManyToManyField(related_name='exams', to='caracteristics.chapter')),
                ('class_levels', models.ManyToManyField(related_name='exams', to='caracteristics.classlevel')),
                ('subfields', models.ManyToManyField(related_name='exams', to='caracteristics.subfield')),
                ('subject', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='exams', to='caracteristics.subject')),
                ('theorems', models.ManyToManyField(related_name='exams', to='caracteristics.theorem')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Exercise',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('content', models.TextField()),
                ('difficulty', models.CharField(choices=[('easy', 'easy'), ('medium', 'medium'), ('hard', 'hard')], max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('view_count', models.PositiveIntegerField(default=0)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exercises', to=settings.AUTH_USER_MODEL)),
                ('chapters', models.ManyToManyField(related_name='exercises', to='caracteristics.chapter')),
                ('class_levels', models.ManyToManyField(related_name='exercises', to='caracteristics.classlevel')),
                ('subfields', models.ManyToManyField(related_name='exercises', to='caracteristics.subfield')),
                ('subject', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='exercises', to='caracteristics.subject')),
                ('theorems', models.ManyToManyField(related_name='exercises', to='caracteristics.theorem')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Lesson',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('content', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('view_count', models.PositiveIntegerField(default=0)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lessons', to=settings.AUTH_USER_MODEL)),
                ('chapters', models.ManyToManyField(related_name='lessons', to='caracteristics.chapter')),
                ('class_levels', models.ManyToManyField(related_name='lessons', to='caracteristics.classlevel')),
                ('subfields', models.ManyToManyField(related_name='lessons', to='caracteristics.subfield')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lessons', to='caracteristics.subject')),
                ('theorems', models.ManyToManyField(related_name='lessons', to='caracteristics.theorem')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Comment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='comments', to=settings.AUTH_USER_MODEL)),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='replies', to='things.comment')),
                ('exam', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='comments', to='things.exam')),
                ('exercise', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='comments', to='things.exercise')),
                ('lesson', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='comments', to='things.lesson')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Solution',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='solutions', to=settings.AUTH_USER_MODEL)),
                ('exercise', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='solution', to='things.exercise')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
