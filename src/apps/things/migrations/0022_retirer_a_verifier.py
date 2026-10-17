# Bandeau « Correction en cours de vérification » retiré à la demande de Natsu (17/10/2026) : on efface la clé
# json_content["a_verifier"] de tous les contenus. update() ligne par ligne : updated_at intact, pas de signaux.
# Retour arrière : rien (les marques effacées ne sont pas remises).
from django.db import migrations


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for pk, js in Content.objects.filter(json_content__has_key='a_verifier').values_list('pk', 'json_content'):
        js.pop('a_verifier', None)
        Content.objects.filter(pk=pk).update(json_content=js)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0021_devoirs_chapitre_par_exercice'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
