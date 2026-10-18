# Suite de 0023 pour les leçons (Natsu, 18/10/2026 : « Limites des suites : les méthodes », tirée de « suite méthode
# (2PC) », était aussi en 2ème Bac SM, et la page d'un contenu sur deux niveaux affichait « 2ème Bac SM »). Même
# règle (document de 2ème Bac PC/SVT → PC/SVT seulement), mêmes marques json_content["sm_retire"], réversible.
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
    for c in Content.objects.filter(type='lesson', class_levels=sm):
        if not _document_pc(c.json_content):
            continue
        autres = set(c.class_levels.exclude(pk=sm.pk).values_list('pk', flat=True))
        if not autres:
            continue
        chapitres = [ch.pk for ch in c.chapters.all() if not set(ch.class_levels.values_list('pk', flat=True)) & autres]
        c.class_levels.remove(sm)
        if chapitres:
            c.chapters.remove(*chapitres)
        js = c.json_content
        js['sm_retire'] = {'niveau': sm.pk, 'chapitres': chapitres}
        Content.objects.filter(pk=c.pk).update(json_content=js)


def backwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.filter(type='lesson', json_content__has_key='sm_retire'):
        js = c.json_content
        r = js.pop('sm_retire') or {}
        c.class_levels.add(r['niveau'])
        if r.get('chapitres'):
            c.chapters.add(*r['chapitres'])
        Content.objects.filter(pk=c.pk).update(json_content=js)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0023_documents_pc_sans_sm'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
