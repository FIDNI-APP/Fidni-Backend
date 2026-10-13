"""« 2ème Bac PC » devient « 2ème Bac PC/SVT » (12/10/2026).

La ligne ClassLevel existante est renommée : même id, donc contenus, profils, classes, cahiers et devoirs suivent.
À faire AVANT le seeder (tests/base_tables.py cherche les niveaux par leur nom) : l'entrypoint lance `migrate` d'abord.
Les titres de cahiers générés (« Mathématiques - 2ème Bac PC ») suivent aussi. Réversible.
"""
from django.db import migrations

ANCIEN, NOUVEAU = '2ème Bac PC', '2ème Bac PC/SVT'


def _renommer(apps, de, vers):
    ClassLevel = apps.get_model('caracteristics', 'ClassLevel')
    Notebook = apps.get_model('notebooks', 'Notebook')
    if ClassLevel.objects.filter(name=vers).exists():
        if ClassLevel.objects.filter(name=de).exists():
            raise RuntimeError(f'Les niveaux « {de} » et « {vers} » existent tous les deux : à fusionner à la main.')
        return  # déjà fait
    ClassLevel.objects.filter(name=de).update(name=vers)
    for nb in Notebook.objects.filter(title__endswith=f' - {de}'):
        titre = nb.title[: -len(de)] + vers
        if not Notebook.objects.filter(user_id=nb.user_id, title=titre).exists():
            Notebook.objects.filter(pk=nb.pk).update(title=titre)


def avant(apps, schema_editor):
    _renommer(apps, ANCIEN, NOUVEAU)


def arriere(apps, schema_editor):
    _renommer(apps, NOUVEAU, ANCIEN)


class Migration(migrations.Migration):
    dependencies = [
        ('caracteristics', '0003_programme_officiel'),
        ('notebooks', '0002_initial'),
    ]
    operations = [migrations.RunPython(avant, arriere)]
