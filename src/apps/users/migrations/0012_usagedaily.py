from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0011_profile_birth_date'),
    ]

    operations = [
        migrations.CreateModel(
            name='UsageDaily',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('kind', models.CharField(max_length=10)),
                ('name', models.CharField(max_length=80)),
                ('count', models.PositiveIntegerField(default=0)),
                ('visitors', models.PositiveIntegerField(default=0)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('date', 'kind', 'name'), name='unique_usage_day')],
                'indexes': [models.Index(fields=['date'], name='usage_date')],
            },
        ),
    ]
