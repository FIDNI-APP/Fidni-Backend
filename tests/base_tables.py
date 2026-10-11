import os
import sys
import django
from pathlib import Path

# Add src directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
src_path = BASE_DIR / 'src'
sys.path.insert(0, str(src_path))

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Setup Django
django.setup()

# Now import models
from apps.caracteristics.models import ClassLevel, Subject, Chapter, Subfield, Theorem

import logging

logger = logging.getLogger('django')


# Taxonomie (niveaux → matières → domaines → chapitres → théorèmes), rejouée à chaque démarrage du
# conteneur : idempotente (get_or_create), elle n'AJOUTE que. Elle vient du programme officiel,
# src/apps/caracteristics/programme.py (source unique) : y modifier les chapitres et les théorèmes, pas ici.
# Un chapitre commun à plusieurs niveaux est une seule ligne (même nom, même domaine) rattachée à chacun ; un
# théorème est créé dans son domaine « maison » (DOMAINE_THEOREME), quel que soit le domaine du chapitre qui le cite.
# Ne jamais renommer une entrée existante sans migration : le nom fait office d'identifiant (doublon sinon).
# Chapitres et théorèmes retirés du programme : migration caracteristics/0003_programme_officiel.

from apps.caracteristics.programme import DOMAINE_THEOREME, MATIERE, NIVEAUX, PROGRAMME  # noqa: E402

TAXONOMIE = {}
for _niveau, _chapitres in PROGRAMME.items():
    _domaines = TAXONOMIE.setdefault(_niveau, {}).setdefault(MATIERE, {})
    for _c in _chapitres:
        _domaines.setdefault(_c['domaine'], {})[_c['nom']] = list(_c['theoremes'])

# « order » est unique : un nouveau niveau naît en fin de liste, puis on remet tout dans l'ordre de
# NIVEAUX en passant par des valeurs provisoires (sinon deux niveaux voudraient le même rang).
def _free_order():
    return (max(ClassLevel.objects.values_list('order', flat=True), default=0) or 0) + 1


levels = {}
for name, _ in NIVEAUX:
    level = ClassLevel.objects.filter(name=name).first() or ClassLevel.objects.create(name=name, order=_free_order())
    levels[name] = level
wanted = dict(NIVEAUX)
if any(level.order != wanted[name] for name, level in levels.items()):
    base = _free_order() + 1000
    for i, level in enumerate(levels.values()):
        level.order = base + i
        level.save(update_fields=['order'])
    for name, level in levels.items():
        level.order = wanted[name]
        level.save(update_fields=['order'])

for level_name, subjects in TAXONOMIE.items():
    level = levels[level_name]
    for subject_name, subfields in subjects.items():
        subject, _ = Subject.objects.get_or_create(name=subject_name)
        subject.class_levels.add(level)
        for subfield_name, chapters in subfields.items():
            subfield, _ = Subfield.objects.get_or_create(name=subfield_name, subject=subject)
            subfield.class_levels.add(level)
            for chapter_name, theorems in chapters.items():
                chapter, _ = Chapter.objects.get_or_create(name=chapter_name, subject=subject, subfield=subfield)
                chapter.class_levels.add(level)
                for theorem_name in theorems:
                    home, _ = Subfield.objects.get_or_create(name=DOMAINE_THEOREME[theorem_name], subject=subject)
                    theorem, _ = Theorem.objects.get_or_create(name=theorem_name, subject=subject, subfield=home)
                    theorem.chapters.add(chapter)
                    theorem.class_levels.add(level)

logger.info("Taxonomie à jour : %d niveau(x), %d chapitre(s)", len(levels), Chapter.objects.count())
