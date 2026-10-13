"""Théorèmes de chaque question (13/10/2026) : les anciennes « notions » (meta.skills) remplacées par les théorèmes de
la base (meta.theorems, apps/caracteristics/theoremes.py), question par question.

    python manage.py questions_theoremes --exporter questions.json
        Écrit, pour chaque exercice et examen, chaque question : énoncé et solution en texte, contexte, anciennes notions,
        théorèmes déjà posés et théorèmes candidats (ceux des niveaux et chapitres du contenu). Lecture seule.

    python manage.py questions_theoremes --appliquer theoremes.json [--a-blanc]
        theoremes.json = {"contenus": {"<id>": {"titre": "…", "questions": {"<chemin>": ["Nom exact", …]}}}}.
        Pose meta.theorems de chaque question listée (liste vide : aucun théorème), retire meta.skills de TOUTES les
        questions, ajoute ces théorèmes aux théorèmes du contenu (filtre « Théorème » des listes), retire le champ
        « notions » des fiches IA pas encore publiées. Un contenu dont le titre ne correspond plus est sauté (rapport).
        --a-blanc : tout est annulé, seul le rapport compte. Sans fichier : data/theoremes_questions.json de l'app.
"""
import html as html_lib
import json
import re
from pathlib import Path

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.caracteristics import theoremes as TH

DEFAUT = Path(__file__).resolve().parents[2] / 'data' / 'theoremes_questions.json'
TAGS = re.compile(r'<[^>]+>')


def texte(block):
    """Texte d'un bloc HTML (formules $…$ gardées)."""
    raw = (block or {}).get('html') if isinstance(block, dict) else block
    raw = re.sub(r'<(br|/p|/li|/div|/h\d)\s*/?>', '\n', raw or '', flags=re.I)
    return re.sub(r'\n\s*\n+', '\n', html_lib.unescape(TAGS.sub('', raw))).strip()


def questions(structure):
    """(chemin, libellé, contexte, énoncé, solution, meta) de chaque question, chemins de QuestionProgress."""
    contexte, qnum = '', 0
    for block in (structure or {}).get('blocks') or []:
        kind = block.get('type')
        if kind == 'section':
            contexte = ''
            continue
        if kind == 'context':
            contexte = texte(block.get('content'))
            continue
        if kind != 'question':
            continue
        qnum += 1
        enonce = texte(block.get('content'))
        subs = block.get('subQuestions') or []
        if subs:
            for i, sub in enumerate(subs):
                yield (f"{block.get('id')}.{sub.get('id')}", f'Q{qnum}{chr(97 + i)}', '\n'.join(x for x in (contexte, enonce) if x),
                       texte(sub.get('content')), texte(sub.get('solution')), sub.get('meta') or {})
        else:
            yield (str(block.get('id')), f'Q{qnum}', contexte, enonce, texte(block.get('solution')), block.get('meta') or {})


def _metas(structure):
    """{chemin: dict meta modifiable} (le crée au besoin)."""
    out = {}
    for block in (structure or {}).get('blocks') or []:
        if block.get('type') != 'question':
            continue
        subs = block.get('subQuestions') or []
        if subs:
            for sub in subs:
                out[f"{block.get('id')}.{sub.get('id')}"] = sub.setdefault('meta', {})
        else:
            out[str(block.get('id'))] = block.setdefault('meta', {})
    return out


class Command(BaseCommand):
    help = 'Théorèmes de chaque question : export pour l’étiquetage, puis application (à la place des notions).'

    def add_arguments(self, parser):
        parser.add_argument('--exporter', metavar='FICHIER')
        parser.add_argument('--appliquer', metavar='FICHIER', nargs='?', const=str(DEFAUT))
        parser.add_argument('--a-blanc', action='store_true', dest='a_blanc')

    def handle(self, *args, exporter=None, appliquer=None, a_blanc=False, **options):
        if bool(exporter) == bool(appliquer):
            raise CommandError('--exporter FICHIER ou --appliquer [FICHIER]')
        if exporter:
            self.exporter(exporter)
        else:
            self.appliquer(appliquer, a_blanc)

    # ── Export (lecture seule)
    def exporter(self, chemin):
        from apps.caracteristics.models import Theorem
        from apps.things.models import Content
        par_niveau = {}
        for th in Theorem.objects.prefetch_related('class_levels', 'chapters'):
            for lv in th.class_levels.all():
                par_niveau.setdefault(lv.id, set()).add((th.name, tuple(sorted(ch.name for ch in th.chapters.all()))))
        contenus = []
        qs = (Content.objects.filter(type__in=('exercise', 'exam')).prefetch_related('class_levels', 'chapters', 'theorems')
              .order_by('id'))
        for c in qs:
            rows = list(questions(c.json_content))
            if not rows:
                continue
            chap = {ch.name for ch in c.chapters.all()}
            cand = set()
            for lv in c.class_levels.all():
                cand |= par_niveau.get(lv.id, set())
            contenus.append({
                'id': c.id, 'type': c.type, 'titre': c.title, 'maj': c.updated_at.isoformat(),
                'niveaux': [lv.name for lv in c.class_levels.all()], 'chapitres': sorted(chap),
                'theoremes_du_contenu': sorted(t.name for t in c.theorems.all()),
                # Candidats : ceux des chapitres du contenu d'abord, puis les autres de ses niveaux.
                'theoremes_candidats': [n for n, chs in sorted(cand, key=lambda x: (not set(x[1]) & chap, x[0]))],
                'questions': [{'chemin': p, 'label': lab, 'contexte': ctx, 'enonce': en, 'solution': sol,
                               'notions': list(meta.get('skills') or []), 'theoremes': TH.de_la_question(meta)}
                              for p, lab, ctx, en, sol, meta in rows],
            })
        Path(chemin).write_text(json.dumps({'exporte_le': timezone.now().isoformat(), 'contenus': contenus},
                                           ensure_ascii=False, indent=1), encoding='utf-8')
        n = sum(len(c['questions']) for c in contenus)
        self.stdout.write(self.style.SUCCESS(f'{len(contenus)} contenus, {n} questions → {chemin}'))

    # ── Application
    def appliquer(self, chemin, a_blanc):
        from apps.ia.models import IAJob
        from apps.things.models import Content
        try:
            data = json.loads(Path(chemin).read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            raise CommandError(f'{chemin} : {e}')
        voulus = data.get('contenus') or {}
        TH.oublier()
        rapport = {'contenus': 0, 'questions': 0, 'sans_theoreme': 0, 'notions_retirees': 0, 'titres': [],
                   'introuvables': [], 'inconnus': {}, 'chemins_inconnus': [], 'fiches_ia': 0}
        with transaction.atomic():
            for c in Content.objects.filter(type__in=('exercise', 'exam')).prefetch_related('theorems').order_by('id'):
                structure = c.json_content or {}
                metas = _metas(structure)
                if not metas:
                    continue
                changed = False
                for meta in metas.values():
                    if 'skills' in meta:
                        meta.pop('skills')
                        rapport['notions_retirees'] += 1
                        changed = True
                cible = voulus.get(str(c.id))
                ajout = []
                if cible is not None:
                    if cible.get('titre') and cible['titre'].strip() != c.title.strip():
                        rapport['titres'].append(f'#{c.id} « {c.title} » ≠ « {cible["titre"]} » : sauté')
                        cible = None
                if cible is not None:
                    for path, noms in (cible.get('questions') or {}).items():
                        meta = metas.get(path)
                        if meta is None:
                            rapport['chemins_inconnus'].append(f'#{c.id} {path}')
                            continue
                        connus, inconnus = TH.traduire(noms or [])
                        for nom in inconnus:
                            rapport['inconnus'].setdefault(nom, []).append(f'#{c.id} {path}')
                        if connus:
                            meta['theorems'] = connus
                            ajout += connus
                        else:
                            meta.pop('theorems', None)
                            rapport['sans_theoreme'] += 1
                        rapport['questions'] += 1
                        changed = True
                for path, meta in metas.items():
                    if not meta:
                        _vider(structure, path)
                if changed:
                    Content.objects.filter(pk=c.pk).update(json_content=structure, updated_at=timezone.now())
                    rapport['contenus'] += 1
                if ajout:
                    ids = [TH.index()[TH.cle(n)]['id'] for n in dict.fromkeys(ajout)]
                    c.theorems.add(*ids)
            rapport['introuvables'] = sorted(set(voulus) - set(map(str, Content.objects.values_list('id', flat=True))))
            for job in IAJob.objects.exclude(status__in=(IAJob.PUBLIE, IAJob.APPLIQUE, IAJob.REJETE)):
                fiches = (job.result or {}).get('fiches') if isinstance(job.result, dict) else None
                if not isinstance(fiches, list):
                    continue
                touche = False
                for f in fiches:
                    for b in (f.get('blocs') or []) if isinstance(f, dict) else []:
                        for q in [b] + list(b.get('sous_questions') or []):
                            if isinstance(q, dict) and 'notions' in q:
                                q.pop('notions')
                                touche = True
                if touche:
                    IAJob.objects.filter(pk=job.pk).update(result=job.result)
                    rapport['fiches_ia'] += 1
            self._rapport(rapport, a_blanc)
            if a_blanc:
                transaction.set_rollback(True)
        if not a_blanc:
            for key in ('similar_index_v3',):
                cache.delete(key)

    def _rapport(self, r, a_blanc):
        w = self.stdout.write
        w(('Répétition à blanc (rien n’est gardé)' if a_blanc else 'Appliqué') + ' :')
        w(f'  {r["contenus"]} contenus modifiés, {r["questions"]} questions étiquetées '
          f'({r["sans_theoreme"]} sans théorème), {r["notions_retirees"]} anciennes notions retirées')
        if r['fiches_ia']:
            w(f'  {r["fiches_ia"]} travaux IA en attente : champ « notions » retiré')
        for t in r['titres']:
            w(self.style.WARNING('  titre changé : ' + t))
        if r['introuvables']:
            w(self.style.WARNING('  contenus introuvables : ' + ', '.join(r['introuvables'])))
        for p in r['chemins_inconnus']:
            w(self.style.WARNING('  question introuvable : ' + p))
        for nom, ou in sorted(r['inconnus'].items()):
            w(self.style.ERROR(f'  théorème inconnu « {nom} » : {", ".join(ou[:5])}'))


def _vider(structure, path):
    """Retire un meta devenu vide (pas de clé « meta »: {} laissée dans le JSON)."""
    for block in structure.get('blocks') or []:
        if block.get('type') != 'question':
            continue
        subs = block.get('subQuestions') or []
        for sub in subs:
            if f"{block.get('id')}.{sub.get('id')}" == path and sub.get('meta') == {}:
                sub.pop('meta')
        if not subs and str(block.get('id')) == path and block.get('meta') == {}:
            block.pop('meta')
