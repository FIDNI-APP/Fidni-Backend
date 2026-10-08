"""Réponses enregistrées à plat : la page d'un contenu envoyait « parent_id », que le serveur ignorait,
si bien que chaque réponse devenait un commentaire à part (corrigé le 08/10/2026).

Une réponse commençait toujours par « @pseudo » (champ prérempli par le bouton « Répondre ») : on la
rattache au dernier commentaire de ce membre sur le même contenu, publié avant elle. Ce qui ne
commence pas par une mention, ou ne trouve pas de commentaire à qui répondre, ne bouge pas.
"""
import re

from django.db import migrations

MENTION = re.compile(r'^\s*(?:<p>)?\s*@([\w.@+-]+)')


def rattacher(apps, schema_editor):
    Comment = apps.get_model('things', 'Comment')
    rows = (Comment.objects.order_by('content_item_id', 'created_at', 'id')
            .values_list('id', 'content_item_id', 'author__username', 'parent_id', 'content'))
    last_by_user, current, links = {}, None, {}
    for cid, content_id, author, parent_id, text in rows:
        if content_id != current:
            current, last_by_user = content_id, {}
        m = MENTION.match(text or '')
        if parent_id is None and m and m.group(1) != author and m.group(1) in last_by_user:
            links[cid] = last_by_user[m.group(1)]
        last_by_user[author] = cid
    for cid, parent in links.items():
        Comment.objects.filter(pk=cid).update(parent_id=parent)


class Migration(migrations.Migration):

    dependencies = [
        ('things', '0008_catchupskip'),
    ]

    operations = [
        migrations.RunPython(rattacher, migrations.RunPython.noop),
    ]
