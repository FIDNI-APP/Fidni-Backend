# Annule 0024 (Natsu, 18/10/2026 : « non pour les leçons tu peux les mettre dans les deux ») : les leçons tirées d'un
# document de 2ème Bac PC/SVT retrouvent le niveau 2ème Bac SM et leurs chapitres (marques json_content["sm_retire"]
# posées par 0024). Les exercices et devoirs (0023) ne bougent pas. Retour arrière : rien.
from django.db import migrations


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.filter(type='lesson', json_content__has_key='sm_retire'):
        js = c.json_content
        r = js.pop('sm_retire') or {}
        if r.get('niveau'):
            c.class_levels.add(r['niveau'])
        if r.get('chapitres'):
            c.chapters.add(*r['chapitres'])
        Content.objects.filter(pk=c.pk).update(json_content=js)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0024_lecons_pc_sans_sm'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
