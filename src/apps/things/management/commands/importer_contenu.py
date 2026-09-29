"""python manage.py importer_contenu <fiche.json | dossier> [--verifier] [--apercu sortie.json]

Importe une fiche au format fidni-fiche/1 (voir apps/things/importing.py) :
  --verifier   contrôle complet (format, HTML, formules, barème, taxonomie, doublons) sans rien écrire ;
  --apercu F   écrit aussi la structure convertie dans F (figures intégrées) pour l'aperçu local ;
  sans option  importe : crée le contenu, ou le met à jour si la même clé existe déjà.
Code de sortie 1 si la fiche contient une erreur.
"""
import base64
import json
import mimetypes
import os

from django.core.management.base import BaseCommand, CommandError

from apps.things import importing


class Command(BaseCommand):
    help = "Vérifie et importe une fiche de contenu (exercice, examen, leçon)."

    def add_arguments(self, parser):
        parser.add_argument('chemin', help='fiche.json, ou dossier qui la contient')
        parser.add_argument('--verifier', action='store_true', help='Contrôler sans rien écrire.')
        parser.add_argument('--apercu', help='Écrire la structure convertie (aperçu local).')
        parser.add_argument('--api-base', default='https://api.fidni.fr')

    def handle(self, chemin, verifier, apercu, api_base, **options):
        path = os.path.join(chemin, 'fiche.json') if os.path.isdir(chemin) else chemin
        base_dir = os.path.dirname(os.path.abspath(path))
        try:
            with open(path, encoding='utf-8') as fh:
                fiche = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f'Lecture impossible de {path} : {exc}')

        errors, warnings, images = importing.validate(fiche)
        errors += importing.check_figures(base_dir, images)
        if not errors:
            db_errors, db_warnings, res = importing.check_against_db(fiche)
            errors += db_errors
            warnings += db_warnings
        else:
            res = {}

        for w in warnings:
            self.stdout.write(self.style.WARNING(f'  ⚠ {w}'))
        if errors:
            for e in errors:
                self.stdout.write(self.style.ERROR(f'  ✗ {e}'))
            raise CommandError(f'{len(errors)} erreur(s) : rien n’a été importé.')

        if apercu:
            src_map = {}
            for rel in images:
                mime = mimetypes.guess_type(rel)[0] or 'image/png'
                with open(os.path.join(base_dir, rel), 'rb') as fh:
                    src_map[rel] = f'data:{mime};base64,{base64.b64encode(fh.read()).decode()}'
            structure = importing.to_structure(fiche, src_map)
            with open(apercu, 'w', encoding='utf-8') as fh:
                json.dump({'type': importing.TYPES[fiche['type']], 'title': fiche['titre'],
                           'structure': structure}, fh, ensure_ascii=False)

        existing = res.get('existing')
        what = f'mise à jour de #{existing.display_id}' if existing else 'nouveau contenu'
        if verifier:
            self.stdout.write(self.style.SUCCESS(f'✓ Fiche valide ({what}).'))
            return

        content, created = importing.import_fiche(fiche, base_dir, api_base=api_base)
        route = {'exercise': 'exercises', 'exam': 'exams', 'lesson': 'lessons'}[content.type]
        self.stdout.write(self.style.SUCCESS(
            f'✓ {"Créé" if created else "Mis à jour"} : #{content.display_id} « {content.title} » '
            f'→ https://fidni.fr/{route}/{content.pk}'))
