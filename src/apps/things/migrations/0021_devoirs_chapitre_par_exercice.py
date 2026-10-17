# Devoirs rangés dans un seul chapitre par 0017 (le dernier du devoir), alors que chacun de leurs exercices relève
# d'un chapitre (Natsu, 17/10/2026 : « les DS n° 1 contiennent aussi les ensembles de nombres »). On remet, parmi les
# chapitres retirés par 0017 (json_content["chapitres_retires"]), le dernier chapitre de chaque exercice : celui des
# théorèmes de ses questions (meta.theorems), comme importing.chapitres_par_exercice. On n'enlève rien.
# Chapitres remis notés dans json_content["chapitres_remis"] : le retour arrière les retire.
from django.db import migrations

from apps.caracteristics.programme import RANG_ABSENT, rang


def _parties(structure):
    """Théorèmes de chaque exercice : les blocs « section » séparent les exercices d'un devoir."""
    out, cur = [], None
    for b in (structure or {}).get('blocks') or []:
        if not isinstance(b, dict):
            continue
        if b.get('type') == 'section':
            cur = set()
            out.append(cur)
            continue
        if cur is None:
            cur = set()
            out.append(cur)
        for q in [b] + [s for s in b.get('subQuestions') or [] if isinstance(s, dict)]:
            cur |= {t for t in ((q.get('meta') or {}).get('theorems') or []) if isinstance(t, str)}
    return out


def forwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    Chapter = apps.get_model('caracteristics', 'Chapter')
    for c in Content.objects.filter(type='exam', json_content__has_key='chapitres_retires'):
        js = c.json_content
        actuels = set(c.chapters.values_list('pk', flat=True))
        retires = [ch for ch in Chapter.objects.filter(pk__in=js.get('chapitres_retires') or [])
                   if ch.pk not in actuels]
        candidats = list(Chapter.objects.filter(pk__in=actuels)) + retires
        remettre = set()
        for lvl in c.class_levels.all():
            r = rang(lvl.name)
            du_niveau = [ch for ch in candidats if ch.class_levels.filter(pk=lvl.pk).exists()]
            for noms in _parties(js):
                avec = [ch for ch in du_niveau if noms and ch.theorems.filter(name__in=noms).exists()]
                if avec:
                    remettre.add(max(avec, key=lambda ch: (-1 if r[ch.name] == RANG_ABSENT else r[ch.name], ch.pk)).pk)
        ajout = [ch.pk for ch in retires if ch.pk in remettre]
        if not ajout:
            continue
        c.chapters.add(*ajout)
        js['chapitres_retires'] = [pk for pk in js['chapitres_retires'] if pk not in ajout]
        js['chapitres_remis'] = sorted(set(js.get('chapitres_remis') or []) | set(ajout))
        Content.objects.filter(pk=c.pk).update(json_content=js)  # sans toucher updated_at


def backwards(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    for c in Content.objects.filter(json_content__has_key='chapitres_remis'):
        js = c.json_content
        remis = js.pop('chapitres_remis') or []
        c.chapters.remove(*remis)
        js['chapitres_retires'] = sorted(set(js.get('chapitres_retires') or []) | set(remis))
        Content.objects.filter(pk=c.pk).update(json_content=js)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0020_chapitres_corriges_2'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
