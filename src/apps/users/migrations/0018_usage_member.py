"""Pages vues et gestes rattachés au membre connecté (UsageMember), pour son journal dans Pilotage › Membres."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('users', '0017_avatars_lionceaux'),
    ]

    operations = [
        migrations.CreateModel(
            name='UsageMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('kind', models.CharField(max_length=10)),
                ('name', models.CharField(max_length=80)),
                ('count', models.PositiveIntegerField(default=0)),
                ('first_at', models.DateTimeField()),
                ('last_at', models.DateTimeField()),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='usage_jours',
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['user', 'date'], name='usage_member_user_date'),
                            models.Index(fields=['date'], name='usage_member_date')],
                'constraints': [models.UniqueConstraint(fields=('user', 'date', 'kind', 'name'),
                                                        name='unique_usage_member_day')],
            },
        ),
    ]
