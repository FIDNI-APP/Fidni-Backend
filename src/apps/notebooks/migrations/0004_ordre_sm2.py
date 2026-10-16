# 2ème Bac SM : la dérivation passe avant les suites dans l'ordre du programme (Natsu, 16/10/2026, ordre suivi par
# M. Haddar ; caracteristics/programme.py). Les cahiers déjà créés rangent leurs sections dans l'ancien ordre : on les
# renumérote dans l'ordre du programme (sections hors programme : à la fin, dans leur ordre actuel).
from django.db import migrations

from apps.caracteristics.programme import RANG_ABSENT, rang


def forwards(apps, schema_editor):
    Notebook = apps.get_model('notebooks', 'Notebook')
    NotebookSection = apps.get_model('notebooks', 'NotebookSection')
    for nb in Notebook.objects.filter(class_level__name='2ème Bac SM'):
        r = rang('2ème Bac SM')
        sections = list(NotebookSection.objects.filter(notebook=nb).select_related('chapter').order_by('order', 'id'))
        ordre = sorted(sections, key=lambda s: (r[s.chapter.name] if r[s.chapter.name] != RANG_ABSENT else 10 ** 7, s.order, s.id))
        for i, s in enumerate(ordre):
            if s.order != i:
                NotebookSection.objects.filter(pk=s.pk).update(order=i)


class Migration(migrations.Migration):

    dependencies = [
        ('notebooks', '0003_annotation_surface'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
