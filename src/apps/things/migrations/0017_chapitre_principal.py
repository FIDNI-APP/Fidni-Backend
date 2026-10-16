# Exercices et examens rangés dans plusieurs chapitres d'un même niveau (ex. un DS de dérivabilité aussi dans « Limites
# et continuité ») : Natsu, 16/10/2026, un contenu ne va que dans le DERNIER chapitre du programme dont il a besoin,
# les précédents sont des prérequis (l'élève qui ouvre « Limites et continuité » n'a pas vu la dérivation).
# Même règle que l'import (importing.chapitres_principaux). Les chapitres retirés sont notés dans
# json_content["chapitres_retires"] : le retour arrière les remet.
from django.db import migrations

from apps.caracteristics.programme import RANG_ABSENT, rang


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.filter(type__in=('exercise', 'exam')).prefetch_related('chapters__class_levels', 'class_levels'):
        chapters = list(c.chapters.all())
        if len(chapters) < 2:
            continue
        levels = list(c.class_levels.all())
        garder = set()
        for lvl in levels:
            du_niveau = [ch for ch in chapters if any(cl.pk == lvl.pk for cl in ch.class_levels.all())]
            if du_niveau:
                r = rang(lvl.name)
                garder.add(max(du_niveau, key=lambda ch: (-1 if r[ch.name] == RANG_ABSENT else r[ch.name], ch.id)).pk)
        level_ids = {lvl.pk for lvl in levels}
        garder |= {ch.pk for ch in chapters if not {cl.pk for cl in ch.class_levels.all()} & level_ids}
        retires = [ch.pk for ch in chapters if ch.pk not in garder]
        if not garder or not retires:
            continue
        c.chapters.remove(*retires)
        js = c.json_content if isinstance(c.json_content, dict) else {}
        js['chapitres_retires'] = sorted(set(js.get('chapitres_retires') or []) | set(retires))
        Content.objects.filter(pk=c.pk).update(json_content=js)  # sans toucher updated_at


def backwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.filter(json_content__has_key='chapitres_retires'):
        js = c.json_content
        c.chapters.add(*(js.pop('chapitres_retires') or []))
        Content.objects.filter(pk=c.pk).update(json_content=js)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0016_ecole_sanaa'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
