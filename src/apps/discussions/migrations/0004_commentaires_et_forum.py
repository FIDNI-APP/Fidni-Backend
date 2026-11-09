# Forum et commentaires séparés (09/11/2026, Natsu : « des fois, les gens commentent sans poser de question »). Jusqu'ici un
# message écrit sous un contenu devenait une discussion du forum, avec sa première phrase pour titre. Le genre devient explicite.
# Commentaire : un seul contenu tagué, et repris d'un ancien commentaire (legacy_comment_id) ou dont le titre n'est que sa
# première phrase (écrit dans l'onglet du contenu, 08-09/11/2026). Son titre fabriqué est vidé. Le reste reste du forum.
# Retour arrière : les titres sont refabriqués, avec la règle de la reprise (0002).
import html
import importlib
import re

from django.db import migrations, models


def _texte(body):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', body or '')).split())


def titre_fabrique(titre, corps):
    """Le titre est-il celui que le site fabriquait pour un message écrit sous un contenu ? Comparaison sans espaces :
    le site et le serveur ne retirent pas les balises de la même façon (« <b>a</b>, b »)."""
    if titre.startswith('À propos de « '):
        return True
    sans_espaces = lambda s: re.sub(r'\s+', '', s)  # noqa: E731
    debut = sans_espaces(titre.removesuffix('…'))
    return bool(debut) and sans_espaces(_texte(corps)).startswith(debut)


def classer(apps, schema_editor):
    Discussion = apps.get_model('discussions', 'Discussion')
    for d in Discussion.objects.filter(genre='forum').prefetch_related('contents'):
        if len(d.contents.all()) != 1:
            continue
        if d.legacy_comment_id is not None or titre_fabrique(d.title, d.body):
            d.genre, d.title = 'commentaire', ''
            d.save(update_fields=['genre', 'title'])


def annuler(apps, schema_editor):
    fabriquer = importlib.import_module('apps.discussions.migrations.0002_reprise_commentaires')._titre
    Discussion = apps.get_model('discussions', 'Discussion')
    for d in Discussion.objects.filter(genre='commentaire').prefetch_related('contents'):
        contenu = next(iter(d.contents.all()), None)
        d.genre, d.title = 'forum', fabriquer(_texte(d.body), contenu.title if contenu else '')
        d.save(update_fields=['genre', 'title'])


class Migration(migrations.Migration):

    dependencies = [
        ('caracteristics', '0004_pc_svt'),
        ('discussions', '0003_reprise_complement'),
        ('things', '0026_recalibrage_difficulte'),
    ]

    operations = [
        migrations.AddField(
            model_name='discussion',
            name='genre',
            field=models.CharField(choices=[('forum', 'Discussion du forum'), ('commentaire', 'Commentaire sous un contenu')], default='forum', max_length=12),
        ),
        migrations.AlterField(
            model_name='discussion',
            name='title',
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddIndex(
            model_name='discussion',
            index=models.Index(fields=['genre', '-last_activity_at'], name='disc_genre_activite'),
        ),
        migrations.RunPython(classer, annuler),
    ]
