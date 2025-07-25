# Generated by Django 5.0.1 on 2025-07-20 13:36

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ClassLevel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('order', models.PositiveIntegerField(unique=True)),
            ],
            options={
                'ordering': ['order'],
            },
        ),
        migrations.CreateModel(
            name='Subject',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('class_levels', models.ManyToManyField(related_name='subjects', to='caracteristics.classlevel')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Subfield',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('class_levels', models.ManyToManyField(related_name='subfields', to='caracteristics.classlevel')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='subfields', to='caracteristics.subject')),
            ],
        ),
        migrations.CreateModel(
            name='Chapter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('class_levels', models.ManyToManyField(related_name='chapters', to='caracteristics.classlevel')),
                ('subfield', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='chapters', to='caracteristics.subfield')),
                ('subject', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='chapters', to='caracteristics.subject')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Theorem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('chapters', models.ManyToManyField(related_name='theorems', to='caracteristics.chapter')),
                ('class_levels', models.ManyToManyField(related_name='theorems', to='caracteristics.classlevel')),
                ('subfield', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='theorems', to='caracteristics.subfield')),
                ('subject', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='theorems', to='caracteristics.subject')),
            ],
        ),
    ]
