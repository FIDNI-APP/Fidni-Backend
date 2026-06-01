import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('caracteristics', '0001_initial'),
        ('uploads', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ConcoursExam
        migrations.CreateModel(
            name='ConcoursExam',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('concours_type', models.CharField(
                    choices=[('ensa', 'ENSA'), ('ensam', 'ENSAM'),
                             ('medecine', 'Médecine')],
                    db_index=True, max_length=10)),
                ('year', models.PositiveIntegerField(db_index=True)),
                ('title', models.CharField(blank=True, max_length=200,
                                           help_text="Optional title — auto-generated if empty (e.g. 'ENSA 2023').")),
                ('description', models.TextField(blank=True)),
                ('duration_minutes', models.PositiveIntegerField(default=180)),
                ('display_id', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='concours_exams',
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-year', 'concours_type'],
            },
        ),
        migrations.AddConstraint(
            model_name='concoursexam',
            constraint=models.UniqueConstraint(
                fields=('concours_type', 'year'),
                name='unique_concours_exam_year'),
        ),
        migrations.AddIndex(
            model_name='concoursexam',
            index=models.Index(fields=['concours_type', 'year'],
                               name='concours_co_concour_e9437b_idx'),
        ),

        # ConcoursTip
        migrations.CreateModel(
            name='ConcoursTip',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True,
                                                 help_text='Markdown / rich text')),
                ('concours_types', models.JSONField(
                    blank=True, default=list,
                    help_text='List of concours type keys this tip applies to')),
                ('video_url', models.URLField(
                    blank=True,
                    help_text='External video URL (YouTube, Vimeo, ...)')),
                ('view_count', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('chapters', models.ManyToManyField(
                    blank=True, related_name='concours_tips',
                    to='caracteristics.chapter')),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='concours_tips',
                    to=settings.AUTH_USER_MODEL)),
                ('subject', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='concours_tips',
                    to='caracteristics.subject')),
                ('subfield', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='concours_tips',
                    to='caracteristics.subfield')),
                ('video_file', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='concours_tip_videos',
                    to='uploads.fileattachment')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='concourstip',
            index=models.Index(fields=['subject'],
                               name='concours_co_subject_8d211b_idx'),
        ),
        migrations.AddIndex(
            model_name='concourstip',
            index=models.Index(fields=['subfield'],
                               name='concours_co_subfiel_2c8e44_idx'),
        ),

        # ConcoursComment
        migrations.CreateModel(
            name='ConcoursComment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('target_type', models.CharField(
                    choices=[('exam', 'Exam'), ('tip', 'Tip')],
                    db_index=True, max_length=4)),
                ('target_id', models.PositiveIntegerField(db_index=True)),
                ('content', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='concours_comments',
                    to=settings.AUTH_USER_MODEL)),
                ('parent', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='replies', to='concours.concourscomment')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='concourscomment',
            index=models.Index(fields=['target_type', 'target_id'],
                               name='concours_co_target__d2f2b1_idx'),
        ),

        # SimulationSession
        migrations.CreateModel(
            name='SimulationSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ('mode', models.CharField(
                    choices=[('exam', 'Specific exam'),
                             ('random_year', 'Random year'),
                             ('random_mix', 'Random questions')],
                    max_length=20)),
                ('concours_type', models.CharField(
                    choices=[('ensa', 'ENSA'), ('ensam', 'ENSAM'),
                             ('medecine', 'Médecine')],
                    db_index=True, max_length=10)),
                ('duration_minutes', models.PositiveIntegerField(
                    help_text='Total time allotted for this session')),
                ('questions_snapshot', models.JSONField(default=list)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[('in_progress', 'In progress'),
                             ('submitted', 'Submitted'),
                             ('expired', 'Expired')],
                    db_index=True, default='in_progress', max_length=15)),
                ('total_questions', models.PositiveIntegerField(default=0)),
                ('correct_count', models.PositiveIntegerField(default=0)),
                ('exam', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sessions', to='concours.concoursexam',
                    help_text='Set for MODE_EXAM and MODE_RANDOM_YEAR (the picked year).')),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='concours_sessions',
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-started_at'],
            },
        ),
        migrations.AddIndex(
            model_name='simulationsession',
            index=models.Index(fields=['user', '-started_at'],
                               name='concours_si_user_id_4d6e91_idx'),
        ),
        migrations.AddIndex(
            model_name='simulationsession',
            index=models.Index(fields=['user', 'status'],
                               name='concours_si_user_id_7b2c10_idx'),
        ),

        # SimulationAnswer
        migrations.CreateModel(
            name='SimulationAnswer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField()),
                ('chosen_key', models.CharField(blank=True, max_length=8,
                                                help_text='Empty string = unanswered')),
                ('is_correct', models.BooleanField(default=False)),
                ('subject_id', models.PositiveIntegerField(blank=True,
                                                           db_index=True, null=True)),
                ('subfield_id', models.PositiveIntegerField(blank=True,
                                                            db_index=True, null=True)),
                ('chapter_id', models.PositiveIntegerField(blank=True, null=True)),
                ('tip_id', models.PositiveIntegerField(blank=True, null=True)),
                ('answered_at', models.DateTimeField(auto_now=True)),
                ('session', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='answers',
                    to='concours.simulationsession')),
            ],
            options={
                'ordering': ['session', 'position'],
                'unique_together': {('session', 'position')},
            },
        ),
        migrations.AddIndex(
            model_name='simulationanswer',
            index=models.Index(fields=['session', 'position'],
                               name='concours_si_session_77c4f9_idx'),
        ),
        migrations.AddIndex(
            model_name='simulationanswer',
            index=models.Index(fields=['session', 'is_correct'],
                               name='concours_si_session_3a8e22_idx'),
        ),
    ]
