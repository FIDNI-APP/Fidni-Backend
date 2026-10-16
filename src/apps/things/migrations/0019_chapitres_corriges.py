# Audit du 16/10/2026 : 16 exercices et examens rangés trop loin par la règle « dernier chapitre utilisé » (0017/0018),
# parce que leur fiche listait un chapitre de trop (ex. DS1 2ème Bac SM 2020 : f′ ne sert qu'aux variations, outil de
# 1ère Bac ; c'est un devoir de « Limites et continuité »). Chapitre remis à la main, à chacun des niveaux du contenu.
# Copie figée de importing.CHAPITRES_FORCES (qui sert aux brouillons et aux prochains imports). Retour arrière : rien.
from django.db import migrations

CORRECTIONS = {
    'ds1-2sm-2020': ['Limites et continuité'],
    'ds1-2sm-2022': ['Limites et continuité'],
    'serie2-continuite-arctan-ex02': ['Limites et continuité'],
    'serie2-continuite-arctan-ex10': ['Limites et continuité'],
    'serie-continuite-reciproque-ex11': ['Limites et continuité'],
    'serie-continuite-reciproque-ex12': ['Limites et continuité'],
    'serie-continuite-reciproque-ex16': ['Limites et continuité'],
    'haddar-lc-ex16': ['Limites et continuité'],
    'ds2-tcs-2022': ['Ordre dans ℝ'],
    'ds2-tcs-2023': ['Ordre dans ℝ'],
    'ordre-tcs-ex15': ['Ordre dans ℝ'],
    'ordre-tcs-ex16': ['Ordre dans ℝ'],
    'ordre-tcs-ex17': ['Ordre dans ℝ'],
    'ordre-tcs-ex18': ['Ordre dans ℝ'],
    'ordre-tcs-ex19': ['Ordre dans ℝ'],
    'logique-1sm-ex5': ['Logique mathématique'],
}


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    Chapter = apps.get_model('caracteristics', 'Chapter')
    for cle, noms in CORRECTIONS.items():
        for c in Content.objects.filter(json_content__import__cle=cle):
            chapitres = []
            for lvl in c.class_levels.all():
                for nom in noms:
                    ch = Chapter.objects.filter(name=nom, class_levels=lvl).first()
                    if ch and ch not in chapitres:
                        chapitres.append(ch)
            if chapitres:
                c.chapters.set(chapitres)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0018_chapitre_principal_ordre_sm'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
