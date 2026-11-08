# Reprise des commentaires en discussions (08/11/2026, Natsu) : la discussion quitte le bas des pages des contenus.
# Chaque commentaire racine devient une discussion du salon « Entraide », qui tague son contenu, au niveau du contenu ;
# ses réponses (réponses aux réponses comprises) deviennent les réponses de la discussion, « en réponse à » gardé.
# Dates, auteurs, votes « j'aime » (devenus « utile ») et pièces jointes (copies du même fichier) suivent. Rien n'est
# modifié ni supprimé : les commentaires restent en base avec leurs pièces jointes (l'ancien site et l'appli mobile les
# lisent encore) ; un commentaire n'est repris qu'une fois (legacy_comment_id, unique).
# Retour arrière : les discussions reprises, leurs votes et leurs copies de pièces jointes sont supprimés.
import html
import re
import unicodedata

from django.db import migrations

TITRE_MAX = 90


def _texte(body):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', body or '')).split())


def _normalize(text):
    text = unicodedata.normalize('NFKD', str(text or ''))
    return ' '.join(''.join(c for c in text if not unicodedata.combining(c)).lower().split())


def _titre(texte, contenu):
    """Première phrase du commentaire (coupée à un mot), ou « À propos de … » s'il est trop court."""
    phrase = re.split(r'(?<=[.?!])\s', texte, maxsplit=1)[0].strip()
    if len(phrase) > TITRE_MAX:
        phrase = phrase[:TITRE_MAX].rsplit(' ', 1)[0].rstrip(' ,;:') + '…'
    if len(phrase) < 6:
        phrase = f'À propos de « {contenu} »'
    return phrase[:160]


def reprendre(apps, schema_editor):
    Comment = apps.get_model('things', 'Comment')
    Discussion = apps.get_model('discussions', 'Discussion')
    Reply = apps.get_model('discussions', 'Reply')
    Follow = apps.get_model('discussions', 'Follow')
    Vote = apps.get_model('interactions', 'Vote')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    FileAttachment = apps.get_model('uploads', 'FileAttachment')

    ct_comment = ContentType.objects.filter(app_label='things', model='comment').first()
    ct_disc, _ = ContentType.objects.get_or_create(app_label='discussions', model='discussion')
    ct_reply, _ = ContentType.objects.get_or_create(app_label='discussions', model='reply')

    comments = list(Comment.objects.order_by('created_at', 'id'))
    children = {}
    for c in comments:
        if c.parent_id:
            children.setdefault(c.parent_id, []).append(c)

    def suivre(old, new_ct, new_id):
        """Votes « j'aime » et pièces jointes du commentaire, recopiés sur son nouveau message. Copies du même fichier :
        le commentaire garde les siennes (ancien site, appli mobile) ; FileAttachment.delete_file ne l'efface du stockage
        que quand plus aucune pièce jointe n'y renvoie."""
        if ct_comment is None:
            return
        for user_id in Vote.objects.filter(content_type=ct_comment, object_id=str(old.id), value=1) \
                .values_list('user_id', flat=True):
            Vote.objects.get_or_create(user_id=user_id, content_type=new_ct, object_id=str(new_id), defaults={'value': 1})
        for att in FileAttachment.objects.filter(content_type=ct_comment, object_id=old.id):
            FileAttachment.objects.create(
                content_type=new_ct, object_id=new_id, file=att.file.name, file_name=att.file_name,
                file_size=att.file_size, file_type=att.file_type, mime_type=att.mime_type,
                uploaded_by_id=att.uploaded_by_id, width=att.width, height=att.height,
            )

    # Rejouable (commande reprendre_commentaires) : un fil déjà repris ne reçoit que ses nouvelles réponses.
    for root in (c for c in comments if not c.parent_id):
        d = Discussion.objects.filter(legacy_comment_id=root.id).first()
        if d is None:
            content = root.content_item
            level = content.class_levels.order_by('order').first()
            texte = _texte(root.content)
            titre = _titre(texte, content.title)
            d = Discussion.objects.create(
                title=titre, body=root.content, author_id=root.author_id, salon='entraide', class_level=level,
                created_at=root.created_at, last_activity_at=root.created_at, legacy_comment_id=root.id,
                search_text=_normalize(f'{titre} {texte}'),
            )
            d.contents.add(content.id)
            Follow.objects.get_or_create(discussion=d, user_id=root.author_id)
            suivre(root, ct_disc, d.id)

        # Toutes les réponses du fil, dans l'ordre où elles ont été écrites.
        thread, frontier = [], list(children.get(root.id, []))
        while frontier:
            c = frontier.pop(0)
            thread.append(c)
            frontier.extend(children.get(c.id, []))
        thread.sort(key=lambda c: (c.created_at, c.id))
        new_ids = dict(Reply.objects.filter(discussion=d, legacy_comment_id__isnull=False)
                       .values_list('legacy_comment_id', 'id'))
        added = False
        for c in thread:
            if c.id in new_ids:
                continue
            r = Reply.objects.create(
                discussion=d, author_id=c.author_id, body=c.content, created_at=c.created_at,
                reply_to_id=new_ids.get(c.parent_id) if c.parent_id != root.id else None, legacy_comment_id=c.id,
            )
            new_ids[c.id] = r.id
            added = True
            Follow.objects.get_or_create(discussion=d, user_id=c.author_id)
            suivre(c, ct_reply, r.id)
        if added:
            last = Reply.objects.filter(discussion=d).order_by('-created_at').values_list('created_at', flat=True).first()
            Discussion.objects.filter(pk=d.pk).update(reply_count=Reply.objects.filter(discussion=d).count(),
                                                      last_activity_at=max(last, d.last_activity_at))


def annuler(apps, schema_editor):
    Discussion = apps.get_model('discussions', 'Discussion')
    Reply = apps.get_model('discussions', 'Reply')
    Vote = apps.get_model('interactions', 'Vote')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    FileAttachment = apps.get_model('uploads', 'FileAttachment')
    for model, name in ((Discussion, 'discussion'), (Reply, 'reply')):
        ct = ContentType.objects.filter(app_label='discussions', model=name).first()
        if ct is None:
            continue
        ids = list(model.objects.filter(legacy_comment_id__isnull=False).values_list('id', flat=True))
        Vote.objects.filter(content_type=ct, object_id__in=[str(i) for i in ids]).delete()
        # Copies seulement : le fichier reste au commentaire (lignes supprimées, stockage intact).
        FileAttachment.objects.filter(content_type=ct, object_id__in=ids).delete()
    Discussion.objects.filter(legacy_comment_id__isnull=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('discussions', '0001_initial'),
        ('things', '0026_recalibrage_difficulte'),
        ('interactions', '0024_journal_reprise'),
        ('uploads', '0001_initial'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(reprendre, annuler),
    ]
