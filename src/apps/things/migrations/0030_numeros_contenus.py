"""Numéro d'un contenu dans son niveau et son chapitre (15/11/2026, things/numeros.py).

Les contenus déjà en ligne sont numérotés dans l'ordre où ils sont arrivés (date de création, puis identifiant),
séparément pour chaque type, niveau et chapitre. Code figé ici (copie de numeros.paires au 15/11/2026).
"""
from django.db import migrations, models
import django.db.models.deletion


def paires(content, chapitres_niveaux):
    niveaux = [lv.id for lv in content.class_levels.all()]
    chapitres = [ch.id for ch in content.chapters.all()]
    if not niveaux or content.is_national_exam:  # Bac national : sa rubrique par année, pas de numéro
        return set()
    if not chapitres:
        return {(lv, None) for lv in niveaux}
    out = set()
    for ch in chapitres:
        siens = chapitres_niveaux.get(ch, set())
        for lv in niveaux:
            if not siens or lv in siens:
                out.add((lv, ch))
    return out or {(lv, ch) for lv in niveaux for ch in chapitres}


def numeroter(apps, schema_editor):
    Content = apps.get_model('things', 'Content')
    Chapter = apps.get_model('caracteristics', 'Chapter')
    NumeroContenu = apps.get_model('things', 'NumeroContenu')
    chapitres_niveaux = {}
    for ch_id, lv_id in Chapter.class_levels.through.objects.values_list('chapter_id', 'classlevel_id'):
        chapitres_niveaux.setdefault(ch_id, set()).add(lv_id)
    compteurs, lignes = {}, []
    for c in Content.objects.order_by('created_at', 'id').prefetch_related('class_levels', 'chapters'):
        for lv, ch in sorted(paires(c, chapitres_niveaux), key=lambda p: (p[0], p[1] or 0)):
            cle = (c.type, lv, ch)
            compteurs[cle] = compteurs.get(cle, 0) + 1
            lignes.append(NumeroContenu(content_id=c.id, type=c.type, class_level_id=lv, chapter_id=ch,
                                        numero=compteurs[cle]))
    NumeroContenu.objects.bulk_create(lignes, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('caracteristics', '0004_pc_svt'),
        ('things', '0029_enseignants_depuis_credits'),
    ]

    operations = [
        migrations.CreateModel(
            name='NumeroContenu',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(max_length=10)),
                ('numero', models.PositiveIntegerField()),
                ('content', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='numeros', to='things.content')),
                ('class_level', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='caracteristics.classlevel')),
                ('chapter', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='caracteristics.chapter')),
            ],
            options={
                'ordering': ['class_level_id', 'chapter_id'],
                'constraints': [
                    models.UniqueConstraint(fields=('content', 'class_level', 'chapter'), name='numero_un_par_chapitre', nulls_distinct=False),
                    models.UniqueConstraint(fields=('type', 'class_level', 'chapter', 'numero'), name='numero_unique_dans_chapitre', nulls_distinct=False),
                ],
            },
        ),
        migrations.RunPython(numeroter, migrations.RunPython.noop),
    ]
