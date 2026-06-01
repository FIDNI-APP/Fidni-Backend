from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classrooms', '0002_rename_classrooms__student_idx_classrooms__student_4a9d4d_idx_and_more'),
        ('things', '0002_remove_content_structure_remove_content_version'),
        ('caracteristics', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TDList',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('due_date', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                related_name='td_lists',
                                                to='classrooms.classroom')),
                ('subject', models.ForeignKey(blank=True, null=True,
                                              on_delete=django.db.models.deletion.SET_NULL,
                                              related_name='td_lists',
                                              to='caracteristics.subject')),
                ('created_by', models.ForeignKey(null=True,
                                                 on_delete=django.db.models.deletion.SET_NULL,
                                                 related_name='created_td_lists',
                                                 to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='tdlist',
            index=models.Index(fields=['classroom'], name='classrooms__td_classr_idx'),
        ),
        migrations.AddIndex(
            model_name='tdlist',
            index=models.Index(fields=['due_date'], name='classrooms__td_due_idx'),
        ),
        migrations.CreateModel(
            name='TDListItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField(default=0)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('content', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='td_items',
                                              to='things.content')),
                ('td_list', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='items',
                                              to='classrooms.tdlist')),
            ],
            options={
                'ordering': ['position', 'added_at'],
                'unique_together': {('td_list', 'content')},
            },
        ),
    ]
