# Exercices et devoirs tirés d'un document de 2ème Bac PC/SVT rangés aussi en 2ème Bac SM (Natsu, 18/10/2026 :
# « enlève ça ») : on retire le niveau 2ème Bac SM et les chapitres qui ne sont rattachés qu'à lui. Même règle que
# l'import (importing.est_document_pc). Retirés notés dans json_content["sm_retire"] : le retour arrière les remet.
import re

from django.db import migrations

SM = '2ème Bac SM'
_DOC_PC = re.compile(r'2\s*-?\s*pc', re.I)
_DOC_SM = re.compile(r'2\s*-?\s*sm', re.I)


def _document_pc(js):
    src = ((js or {}).get('import') or {}).get('source')
    nom = src.get('document') if isinstance(src, dict) else None
    return isinstance(nom, str) and bool(_DOC_PC.search(nom)) and not _DOC_SM.search(nom)


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    ClassLevel = apps.get_model('caracteristics', 'ClassLevel')
    sm = ClassLevel.objects.filter(name=SM).first()
    if sm is None:
        return
    for c in Content.objects.filter(type__in=('exercise', 'exam'), class_levels=sm):
        if not _document_pc(c.json_content):
            continue
        autres = set(c.class_levels.exclude(pk=sm.pk).values_list('pk', flat=True))
        if not autres:  # un contenu ne reste jamais sans niveau
            continue
        chapitres = [ch.pk for ch in c.chapters.all() if not set(ch.class_levels.values_list('pk', flat=True)) & autres]
        c.class_levels.remove(sm)
        if chapitres:
            c.chapters.remove(*chapitres)
        js = c.json_content
        js['sm_retire'] = {'niveau': sm.pk, 'chapitres': chapitres}
        Content.objects.filter(pk=c.pk).update(json_content=js)  # sans toucher updated_at


def backwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.filter(json_content__has_key='sm_retire'):
        js = c.json_content
        r = js.pop('sm_retire') or {}
        c.class_levels.add(r['niveau'])
        if r.get('chapitres'):
            c.chapters.add(*r['chapitres'])
        Content.objects.filter(pk=c.pk).update(json_content=js)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0022_retirer_a_verifier'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
