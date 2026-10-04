from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0005_remove_content_legacy_text'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.CharField(choices=[('statement', "Erreur dans l'énoncé"), ('solution', 'Erreur dans la solution'), ('scale', 'Barème incorrect'), ('typo', "Faute de frappe ou d'orthographe"), ('display', 'Formule ou figure mal affichée'), ('other', 'Autre')], max_length=20)),
                ('item_path', models.CharField(blank=True, default='', max_length=120)),
                ('item_label', models.CharField(blank=True, default='', max_length=160)),
                ('description', models.TextField(blank=True, default='')),
                ('status', models.CharField(choices=[('open', 'À traiter'), ('resolved', 'Corrigé'), ('dismissed', 'Sans suite')], db_index=True, default='open', max_length=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('handled_at', models.DateTimeField(blank=True, null=True)),
                ('content', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reports', to='things.content')),
                ('handled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_reports', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'things_contentreport',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['status', '-created_at'], name='contentreport_status_date')],
            },
        ),
    ]
