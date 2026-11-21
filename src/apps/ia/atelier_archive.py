"""Validation et dépôt des archives issues de l’atelier Windows."""
import io
import json
from pathlib import Path
import re
import tempfile
import zipfile

LIMIT = 64 * 1024 * 1024
FIGURE = re.compile(r'figures/[\w.-]+\.(?:png|jpg|jpeg|webp)', re.ASCII | re.I)


def unpack(data, directory):
    if len(data) > LIMIT:
        raise ValueError("Le dossier dépasse 64 Mio.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(names) > 160 or len(set(names)) != len(names) or 'fiche.json' not in names:
            raise ValueError("Contenu du dossier invalide.")
        documents = 0
        total = 0
        for entry in entries:
            name = entry.filename
            total += entry.file_size
            if entry.compress_type != zipfile.ZIP_STORED or total > LIMIT:
                raise ValueError("Format ou taille de dossier invalide.")
            if name.startswith('document/'):
                basename = name[len('document/'):]
                documents += 1
                if (documents > 1 or not basename or '/' in basename or '\\' in basename or
                        any(ord(c) < 32 for c in basename) or
                        Path(basename).suffix.lower() not in {'.pdf', '.docx', '.png', '.jpg', '.jpeg', '.webp'}):
                    raise ValueError("Nom du document non accepté.")
            elif name not in ('fiche.json', 'commentaires.json') and not FIGURE.fullmatch(name):
                raise ValueError("Fichier non accepté.")
            target = directory / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(archive.read(entry))


def traiter_archive(action, data, user):
    from django.core.management import call_command
    from django.db import connection, transaction
    with tempfile.TemporaryDirectory(prefix='fidni-import-') as tmp:
        directory = Path(tmp)
        unpack(data, directory)
        fiche = json.loads((directory / 'fiche.json').read_text(encoding='utf-8'))
        key = fiche['cle']
        if not isinstance(key, str) or not re.fullmatch(r'[a-z0-9-]{1,200}', key):
            raise ValueError("Clé de fiche invalide.")
        log = io.StringIO()
        preview = directory / 'apercu.json'
        try:
            call_command('importer_contenu', str(directory), verifier=True, apercu=str(preview), stdout=log)
        except Exception as e:
            raise ValueError(log.getvalue() + str(e)) from e
        if action == 'verifier':
            from apps.things.models import Content
            old = Content.objects.filter(json_content__import__cle=key).first()
            meta = None if old is None else dict(difficulte=old.difficulty,
                sous_domaines=list(old.subfields.values_list('name', flat=True)),
                theoremes=list(old.theorems.values_list('name', flat=True)))
            return {'apercu': json.loads(preview.read_text()), 'controle': log.getvalue(), 'existant': meta}
        if not (directory / 'document').is_dir():
            raise ValueError("Le document original doit être joint.")
        from apps.ia.depot import deposer
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['import-professeur:' + key])
            job, _ = deposer(str(directory))
            job.created_by = user
            job.save(update_fields=['created_by'])
        return {'id': job.pk}
