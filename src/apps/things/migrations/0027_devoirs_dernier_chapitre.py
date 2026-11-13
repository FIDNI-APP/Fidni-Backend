# Devoir (et exercice) = son DERNIER chapitre du programme seulement (Natsu, 13/11/2026) : « un devoir qui contient les
# chapitres 1, 2 et 3 va dans le 3 ; l'élève qui ouvre Dérivation n'a pas encore vu ln ni exp ». Annule l'esprit de 0021
# (un devoir allait aussi dans le chapitre de chacun de ses exercices). À chaque niveau du contenu, on garde le chapitre
# au plus grand rang du programme (un chapitre absent du programme compte comme le premier) ; un chapitre d'aucun des
# niveaux du contenu est gardé (comme importing.chapitres_principaux). Leçons intactes.
# Chapitres retirés notés dans json_content["chapitres_reduits_1311"] : le retour arrière les remet.
from django.db import migrations

from apps.caracteristics.programme import RANG_ABSENT, rang


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.filter(type__in=('exam', 'exercise')).prefetch_related('chapters', 'class_levels'):
        chapitres = list(c.chapters.all())
        if len(chapitres) < 2:
            continue
        niveaux = list(c.class_levels.all())
        garder = set()
        for lvl in niveaux:
            du_niveau = [ch for ch in chapitres if ch.class_levels.filter(pk=lvl.pk).exists()]
            if du_niveau:
                r = rang(lvl.name)
                garder.add(max(du_niveau, key=lambda ch: (-1 if r[ch.name] == RANG_ABSENT else r[ch.name], ch.pk)).pk)
        ids = [lvl.pk for lvl in niveaux]
        garder |= {ch.pk for ch in chapitres if not ch.class_levels.filter(pk__in=ids).exists()}
        retirer = [ch.pk for ch in chapitres if ch.pk not in garder]
        if not garder or not retirer:
            continue
        c.chapters.remove(*retirer)
        js = c.json_content if isinstance(c.json_content, dict) else {}
        js['chapitres_reduits_1311'] = sorted(retirer)
        Content.objects.filter(pk=c.pk).update(json_content=js)  # sans toucher updated_at


def backwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.filter(json_content__has_key='chapitres_reduits_1311'):
        js = c.json_content
        c.chapters.add(*(js.pop('chapitres_reduits_1311') or []))
        Content.objects.filter(pk=c.pk).update(json_content=js)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0026_recalibrage_difficulte'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
