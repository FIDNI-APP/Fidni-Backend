import json
from pathlib import Path

from django.db import migrations, models

DATA = Path(__file__).resolve().parent.parent / 'data' / 'schools_ma.json'


def load_schools(apps, schema_editor):
    """Charge les ~10 400 établissements publiés par le ministère (juillet 2026)."""
    from apps.caracteristics.models import school_search_key
    School = apps.get_model('caracteristics', 'School')
    rows = json.loads(DATA.read_text(encoding='utf-8'))['rows']
    School.objects.bulk_create(
        [School(name=n, name_ar=ar, city=c, region=r, kind=k, search=school_search_key(n, ar, c))
         for n, ar, c, r, k in rows],
        batch_size=1000,
    )


def unload_schools(apps, schema_editor):
    apps.get_model('caracteristics', 'School').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('caracteristics', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='School',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('name_ar', models.CharField(blank=True, max_length=255)),
                ('city', models.CharField(blank=True, max_length=120)),
                ('region', models.CharField(blank=True, max_length=120)),
                ('kind', models.CharField(choices=[('lycee', 'Lycée public'), ('college', 'Collège public'), ('cpge', 'CPGE'), ('prive', 'Établissement privé')], max_length=10)),
                ('search', models.CharField(editable=False, max_length=700)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.RunPython(load_schools, unload_schools),
    ]
