"""Un exercice = un niveau (Natsu, 26/10/2026) : dédouble les exercices publiés sur 2ème Bac SM ET 2ème Bac PC/SVT.

Pour chacun : l'original reste en 2ème Bac SM (avec ses chapitres SM, ses élèves, ses statistiques) ; une copie
séparée est créée pour 2ème Bac PC/SVT, avec SA difficulté (jugée pour un élève de PC/SVT, question par question)
donnée par le plan JSON, et les chapitres PC. Les progressions déjà faites restent sur l'original.

Plan : {"<id>": {"difficulte": "facile|moyen|difficile", "questions": {"<chemin>": "facile|moyen|difficile"}}}
Usage : manage.py dedoubler_pc --plan /tmp/plan.json [--ids 10 11] [--essai]
Réversible : l'original garde dans json_content.import « copie_2pc » (id de la copie) ; supprimer la copie et lui
rendre le niveau PC/SVT et ses chapitres PC (« chapitres_pc_retires ») défait tout.
"""
import copy
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from apps.caracteristics.models import ClassLevel
from apps.things.models import Content, Solution

SM, PC = '2ème Bac SM', '2ème Bac PC/SVT'
DIFF = {'facile': 'easy', 'moyen': 'medium', 'difficile': 'hard'}


def appliquer_difficultes(structure, par_chemin):
    """Difficulté de chaque question (meta.difficulty) d'après {chemin: facile|moyen|difficile} ; renvoie les chemins
    du plan absents de la structure (à signaler)."""
    vus = set()
    for b in (structure or {}).get('blocks') or []:
        if b.get('type') != 'question':
            continue
        cibles = [(b.get('id'), b)] + [(f"{b.get('id')}.{sq.get('id')}", sq) for sq in b.get('subQuestions') or []]
        for chemin, bloc in cibles:
            if chemin in par_chemin:
                bloc.setdefault('meta', {})['difficulty'] = DIFF[par_chemin[chemin]]
                vus.add(chemin)
    return sorted(set(par_chemin) - vus)


def a_dedoubler():
    return (Content.objects.filter(type='exercise').annotate(n=Count('class_levels', distinct=True)).filter(n__gt=1)
            .filter(class_levels__name=SM).filter(class_levels__name=PC).distinct().order_by('id'))


def dedoubler(orig, plan, sm, pc):
    """Crée la copie PC/SVT de `orig` et retire PC/SVT de l'original → (copie, chemins inconnus du plan)."""
    structure = copy.deepcopy(orig.json_content or {})
    inconnus = appliquer_difficultes(structure, plan.get('questions') or {})
    imp = structure.setdefault('import', {})
    cle = imp.get('cle') or f'contenu-{orig.id}'
    imp.update({'cle': f'{cle}-2pc', 'copie_de': orig.id})
    tous = list(orig.chapters.all().prefetch_related('class_levels'))
    ch_pc = [c for c in tous if pc in c.class_levels.all()]
    ch_sm = [c for c in tous if sm in c.class_levels.all()]
    retires = [c.id for c in tous if c not in ch_sm]
    copie = Content.objects.create(
        type=orig.type, title=orig.title, json_content=structure, author=orig.author, subject=orig.subject,
        school=orig.school, difficulty=DIFF[plan['difficulte']], is_national_exam=orig.is_national_exam,
        national_year=orig.national_year, duration_minutes=orig.duration_minutes)
    copie.class_levels.set([pc])
    copie.chapters.set(ch_pc)
    copie.theorems.set(orig.theorems.all())
    copie.subfields.set(orig.subfields.all())
    sol = Solution.objects.filter(content_item=orig).first()
    if sol:
        Solution.objects.create(content_item=copie, solution_text=sol.solution_text, author=sol.author)
    orig.class_levels.remove(pc)
    orig.chapters.set(ch_sm)
    oi = (orig.json_content or {}).setdefault('import', {})
    oi.update({'copie_2pc': copie.id, 'chapitres_pc_retires': retires})
    Content.objects.filter(pk=orig.pk).update(json_content=orig.json_content)
    return copie, inconnus


class Command(BaseCommand):
    help = 'Dédouble les exercices SM + PC/SVT : original en SM, copie PC/SVT avec sa propre difficulté.'

    def add_arguments(self, parser):
        parser.add_argument('--plan', required=True, help='JSON : difficulté PC/SVT par contenu et par question')
        parser.add_argument('--ids', nargs='*', type=int)
        parser.add_argument('--essai', action='store_true')

    def handle(self, plan, ids, essai, **options):
        with open(plan, encoding='utf-8') as fh:
            plans = {int(k): v for k, v in json.load(fh).items()}
        sm, pc = ClassLevel.objects.get(name=SM), ClassLevel.objects.get(name=PC)
        cibles = a_dedoubler()
        if ids:
            cibles = cibles.filter(pk__in=ids)
        faits = sans_plan = 0
        for orig in cibles:
            p = plans.get(orig.id)
            if not p or p.get('difficulte') not in DIFF or any(v not in DIFF for v in (p.get('questions') or {}).values()):
                sans_plan += 1
                self.stdout.write(f'{orig.id} : pas de plan valide, laissé tel quel — « {orig.title[:60]} »')
                continue
            if essai:
                self.stdout.write(f'{orig.id} : copie PC/SVT en « {p["difficulte"]} » (SM : {orig.difficulty}) — « {orig.title[:60]} »')
                faits += 1
                continue
            with transaction.atomic():
                copie, inconnus = dedoubler(orig, p, sm, pc)
            faits += 1
            self.stdout.write(f'{orig.id} → copie {copie.id} (PC/SVT, {p["difficulte"]})'
                              + (f' ; chemins inconnus : {inconnus}' if inconnus else ''))
        if sans_plan and not faits:
            raise CommandError('Aucun contenu dédoublé : plan manquant ou invalide.')
        self.stdout.write(f"{'À dédoubler' if essai else 'Dédoublés'} : {faits} ; laissés faute de plan : {sans_plan}.")
