"""Passage de la taxonomie au programme officiel : code de la migration caracteristics/0003_programme_officiel
(et de sa répétition à blanc, `python manage.py programme_officiel --a-blanc`).

FIGÉ : ne plus modifier après le déploiement de 0003. Ce module n'importe ni programme.py ni le code des apps :
modèles historiques seulement (apps.get_model), données passées en argument (DONNEES, littéraux de 0003).

appliquer(apps, donnees, a_blanc=False, log=print) -> rapport (dict sérialisable en JSON)

Étapes : doublons → scissions → fusions → détachement → ancien chapitre ln/exp → rattachements (+ primitives,
produit vectoriel) → théorèmes → TaxonomyTimeSpent → identifiants (UsageDaily, concours) → cahiers → fiches IA →
suppressions → rapport (imprimé, et enregistré dans logging.SystemEvent s'il y a eu des changements).

Garanties : base vide (aucun niveau) ou sans matière « Mathématiques » → rien ; atomique ; idempotente (une
deuxième exécution ne change rien) ; noms absents ignorés ; chapitres et théorèmes d'administrateurs laissés tels
quels (listés) ; aucun Content supprimé ni enregistré par save() (tables de liaison et queryset.update() seulement :
updated_at, sitemap et « nouveautés » inchangés) ; un chapitre ou un théorème n'est supprimé que si plus rien de
bloquant ne le référence, sinon il est détaché, renommé « <nom> (ancien #<id>) » et signalé.
"""
import re
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Q

STATUTS_IA = ('en_attente', 'en_cours', 'pret', 'erreur')
SEUILS_QUIZ = ((90, 'expert'), (70, 'advanced'), (50, 'intermediate'))
FILTRE = re.compile(r'^(?P<liste>exercise|exam|lesson):(?P<quoi>chapitre|theoreme):(?P<id>\d+)$')


def _cle(nom):
    return (nom or '').strip().lower()


def _modele(apps, app, nom):
    try:
        return apps.get_model(app, nom)
    except LookupError:
        return None


def _questions(structure):
    """Notions (non vides ou vides) de chaque question, sous-questions comprises (comme users/my_stats._questions)."""
    for bloc in (structure or {}).get('blocks', []) if isinstance(structure, dict) else []:
        if not isinstance(bloc, dict) or bloc.get('type') != 'question':
            continue
        subs = [s for s in bloc.get('subQuestions') or [] if isinstance(s, dict)]
        for q in subs or [bloc]:
            yield [n for n in (q.get('meta') or {}).get('skills') or [] if isinstance(n, str)]


def _qcm(questions):
    """Questions de QCM d'un sujet de concours (json_content['questions']) ou d'une session (questions_snapshot :
    {exam_id, question: {...}, position})."""
    for q in questions if isinstance(questions, list) else []:
        if isinstance(q, dict):
            yield q.get('question') if isinstance(q.get('question'), dict) else q


class _M2M:
    """Table de liaison d'un ManyToMany (propriétaire a ↔ cible b), écrite directement : jamais de save() du
    propriétaire, donc ni signal ni updated_at."""

    def __init__(self, mig, modele, champ, touche=None):
        f = modele._meta.get_field(champ)
        self.mig, self.t = mig, f.remote_field.through
        self.a, self.b = f.m2m_field_name() + '_id', f.m2m_reverse_field_name() + '_id'
        self.touche = touche

    def qs(self, a=None, b=None):
        filtre = {}
        if a is not None:
            filtre[self.a] = a
        if b is not None:
            filtre[self.b] = b
        return self.t.objects.filter(**filtre)

    def cibles(self, a):
        return set(self.qs(a=a).values_list(self.b, flat=True))

    def proprietaires(self, b):
        return sorted(set(self.qs(b=b).values_list(self.a, flat=True)))

    def par_proprietaire(self, ids):
        out = defaultdict(set)
        for a, b in self.t.objects.filter(**{self.a + '__in': list(ids)}).values_list(self.a, self.b):
            out[a].add(b)
        return out

    def ajouter(self, a, b):
        if b is None or self.qs(a, b).exists():
            return False
        self.t.objects.create(**{self.a: a, self.b: b})
        self._change(b)
        return True

    def retirer(self, a, b):
        if self.qs(a, b).delete()[0]:
            self._change(b)
            return True
        return False

    def remplacer(self, a, source, cible):
        ajoute = self.ajouter(a, cible)
        return self.retirer(a, source) or ajoute

    def _change(self, b):
        self.mig.n += 1
        if self.touche is not None:
            self.touche.add(b)


class _Migration:
    def __init__(self, apps, donnees, a_blanc, log):
        self.apps, self.d, self.a_blanc, self.log = apps, donnees, a_blanc, log
        self.n = 0  # écritures effectives
        g = lambda app, nom: _modele(apps, app, nom)  # noqa: E731
        self.ClassLevel, self.Subject = g('caracteristics', 'ClassLevel'), g('caracteristics', 'Subject')
        self.Subfield, self.Chapter = g('caracteristics', 'Subfield'), g('caracteristics', 'Chapter')
        self.Theorem, self.Content = g('caracteristics', 'Theorem'), g('things', 'Content')
        self.RevisionList, self.UpcomingTest = g('interactions', 'RevisionList'), g('interactions', 'UpcomingTest')
        self.StudyTimeTracker = g('interactions', 'StudyTimeTracker')
        self.TaxonomyTimeSpent = g('interactions', 'TaxonomyTimeSpent')
        self.ConcoursTip, self.ConcoursExam = g('concours', 'ConcoursTip'), g('concours', 'ConcoursExam')
        self.SimulationSession = g('concours', 'SimulationSession')
        self.SimulationAnswer = g('concours', 'SimulationAnswer')
        self.SkillQuestion, self.SkillAssessment = g('skilliq', 'SkillQuestion'), g('skilliq', 'SkillAssessment')
        self.Notebook, self.NotebookSection = g('notebooks', 'Notebook'), g('notebooks', 'NotebookSection')
        self.NotebookLessonEntry = g('notebooks', 'NotebookLessonEntry')
        self.LearningPath, self.PathChapter = g('learningpath', 'LearningPath'), g('learningpath', 'PathChapter')
        self.UserProfile, self.UsageDaily = g('users', 'UserProfile'), g('users', 'UsageDaily')
        self.IAJob, self.SystemEvent = g('ia', 'IAJob'), g('logging', 'SystemEvent')
        self.ContentType = g('contenttypes', 'ContentType')
        # Taxonomies dont l'ensemble des contenus a changé (TaxonomyTimeSpent à reconstruire).
        self.touches = {'chapter': set(), 'theorem': set(), 'subfield': set()}
        self.remplace_ch, self.remplace_th = {}, {}  # identifiant source → cible (None : théorème sans remplaçant)
        self.a_supprimer = {'chapitres': [], 'theoremes': []}
        self.sans_niveau = set()
        self.r = {'version': '0003_programme_officiel', 'a_blanc': a_blanc}

    # ── accès
    def niveau(self, nom):
        return self.ClassLevel.objects.filter(name=nom).order_by('id').first()

    def domaine(self, nom):
        sf = self.Subfield.objects.filter(name=nom, subject=self.maths).order_by('id').first()
        if sf is None:
            sf = self.Subfield.objects.create(name=nom, subject=self.maths)
            self.n += 1
        return sf

    def chapitre(self, nom):
        return self.Chapter.objects.filter(name=nom, subject=self.maths).order_by('id').first()

    def theoreme(self, nom):
        return self.Theorem.objects.filter(name=nom, subject=self.maths).order_by('id').first()

    def creer_chapitre(self, nom, domaine, niveaux=()):
        ch = self.chapitre(nom)
        if ch is None:
            ch = self.Chapter.objects.create(name=nom, subject=self.maths, subfield=self.domaine(domaine))
            self.n += 1
            self.r.setdefault('crees', {'chapitres': [], 'theoremes': []})['chapitres'].append(nom)
            for lv in niveaux:
                self.chl.ajouter(ch.id, lv)
        return ch

    def creer_theoreme(self, nom):
        th = self.theoreme(nom)
        if th is None:
            th = self.Theorem.objects.create(name=nom, subject=self.maths,
                                             subfield=self.domaine(self.d['domaine_theoreme'][nom]))
            self.n += 1
            self.r.setdefault('crees', {'chapitres': [], 'theoremes': []})['theoremes'].append(nom)
        return th

    def niveaux_contenus(self, ids):
        out = self.cl.par_proprietaire(ids)
        for cid in ids:
            if not out.get(cid):
                self.sans_niveau.add(cid)
        return out

    def ajouter_chapitre(self, cid, ch):
        ajoute = self.cc.ajouter(cid, ch.id)
        if ch.subfield_id:
            self.cs.ajouter(cid, ch.subfield_id)
        return ajoute

    def remplacer_chapitre(self, cid, source, cible):
        ajoute = self.ajouter_chapitre(cid, cible)
        return self.cc.retirer(cid, source.id) or ajoute

    # ── point d'entrée
    def executer(self):
        if self.ClassLevel is None or not self.ClassLevel.objects.exists():
            self.log('Programme officiel : base vide, rien à faire (le seeder créera la taxonomie).')
            return None
        self.maths = self.Subject.objects.filter(name=self.d['matiere']).order_by('id').first()
        if self.maths is None:
            self.log('Programme officiel : pas de matière « Mathématiques », rien à faire.')
            return None
        C, T = self.Chapter, self.Theorem
        self.cc = _M2M(self, self.Content, 'chapters', self.touches['chapter'])
        self.ct = _M2M(self, self.Content, 'theorems', self.touches['theorem'])
        self.cs = _M2M(self, self.Content, 'subfields', self.touches['subfield'])
        self.cl = _M2M(self, self.Content, 'class_levels')
        self.chl, self.thl = _M2M(self, C, 'class_levels'), _M2M(self, T, 'class_levels')
        self.thc = _M2M(self, T, 'chapters')
        self.rl = _M2M(self, self.RevisionList, 'chapters') if self.RevisionList else None
        self.rll = _M2M(self, self.RevisionList, 'class_levels') if self.RevisionList else None
        self.ut = _M2M(self, self.UpcomingTest, 'chapters') if self.UpcomingTest else None
        self.tip = _M2M(self, self.ConcoursTip, 'chapters') if self.ConcoursTip else None
        self.lpl = _M2M(self, self.LearningPath, 'class_level') if self.LearningPath else None
        with transaction.atomic():
            self.inventaire()
            self.doublons()
            for op in self.d['scissions']:
                self.scission(op)
            for op in self.d['fusions']:
                self.fusion_programme(op)
            for op in self.d['detachements']:
                self.detachement(op)
            self.ancien_ln_exp()
            self.rattachements()
            self.theoremes()
            self.temps()
            self.identifiants()
            self.cahiers()
            self.fiches_ia()
            self.suppressions()
            self.r['contenus_sans_niveau'] = sorted(self.sans_niveau)
            self.r['changements'] = self.n
            texte = rendre(self.r)
            self.log(texte)
            if self.n and self.SystemEvent is not None:
                self.SystemEvent.objects.create(
                    event_type='migration', description=texte, metadata=self.r,
                    title='Programme officiel (caracteristics 0003)' + (' — à blanc' if self.a_blanc else ''))
        return self.r

    # ── inventaire (avant tout changement)
    def inventaire(self):
        noms = [n for n in self.d['niveaux']]
        hors = []
        for ch in (self.Chapter.objects.filter(class_levels__name__in=noms, subject__isnull=False)
                   .exclude(subject=self.maths).select_related('subject').distinct().order_by('subject__name', 'name')):
            hors.append({'matiere': ch.subject.name if ch.subject else None, 'chapitre': ch.name, 'id': ch.id,
                         'niveaux': sorted(set(ch.class_levels.values_list('name', flat=True))),
                         'contenus': len(self.cc.proprietaires(ch.id))})
        self.r['hors_maths'] = hors
        connus_ch = {_cle(n) for n in self.d['noms_connus']['chapitres']}
        connus_th = {_cle(n) for n in self.d['noms_connus']['theoremes']}
        ancien = re.compile(r' \(ancien #\d+\)$')
        self.r['administrateurs'] = {
            'chapitres': [{'id': i, 'nom': n} for i, n in self.Chapter.objects.filter(
                Q(subject=self.maths) | Q(subject__isnull=True)).order_by('id').values_list('id', 'name')
                if _cle(n) not in connus_ch and not ancien.search(n)],
            'theoremes': [{'id': i, 'nom': n} for i, n in self.Theorem.objects.filter(
                Q(subject=self.maths) | Q(subject__isnull=True)).order_by('id').values_list('id', 'name')
                if _cle(n) not in connus_th and not ancien.search(n)],
        }

    # ── étape 0 : doublons, et lignes du programme ramenées à la clé du seeder (nom, matière, domaine)
    def doublons(self):
        rapport = self.r.setdefault('doublons', {'cles_corrigees': [], 'fusionnes': []})
        cles_ch = {_cle(n): (n, dom) for n, dom in self.d['domaine_chapitre'].items()}
        cles_th = {_cle(n): (n, dom) for n, dom in self.d['domaine_theoreme'].items()}
        for modele, cles, fusion, quoi in ((self.Chapter, cles_ch, self.fusion_chapitre, 'chapitre'),
                                          (self.Theorem, cles_th, self.fusion_theoreme, 'théorème')):
            groupes = defaultdict(list)
            for ligne in modele.objects.filter(Q(subject=self.maths) | Q(subject__isnull=True)).order_by('id'):
                groupes[_cle(ligne.name)].append(ligne)
            for cle, lignes in groupes.items():
                if cle in cles:
                    nom, dom = cles[cle]
                    sf = self.domaine(dom)
                    survivant = next((x for x in lignes if (x.name, x.subject_id, x.subfield_id)
                                      == (nom, self.maths.id, sf.id)), lignes[0])
                    if (survivant.name, survivant.subject_id, survivant.subfield_id) != (nom, self.maths.id, sf.id):
                        modele.objects.filter(pk=survivant.pk).update(name=nom, subject=self.maths, subfield=sf)
                        self.n += 1
                        rapport['cles_corrigees'].append(f'{quoi} #{survivant.pk} « {survivant.name} » → « {nom} », '
                                                         f'{self.d["matiere"]}, {dom}')
                        survivant = modele.objects.get(pk=survivant.pk)
                elif len(lignes) > 1:
                    survivant = lignes[0]
                else:
                    continue
                for autre in lignes:
                    if autre.pk != survivant.pk:
                        rapport['fusionnes'].append(f'{quoi} #{autre.pk} « {autre.name} » → #{survivant.pk}')
                        fusion(autre, survivant, doublon=True)

    # ── niveau d'une ligne (liste de révision, devoir) pour une scission ou un détachement
    def cote(self, niveaux_ligne, profil, cote_b, cote_k):
        b, k = bool(niveaux_ligne & cote_b), bool(niveaux_ligne & cote_k)
        if b != k:
            return 'B' if b else 'K'
        if profil in cote_b:
            return 'B'
        if profil in cote_k:
            return 'K'
        return None

    def profils(self, user_ids):
        if self.UserProfile is None:
            return {}
        return dict(self.UserProfile.objects.filter(user_id__in=list(user_ids)).values_list('user_id', 'class_level_id'))

    def lignes_par_niveau(self, source, cible, b_ids, k_ids):
        """RevisionList et UpcomingTest de `source` : niveau B → remplacer par `cible` ; ambigu → ajouter ;
        côté K → rien."""
        bilan = defaultdict(list)
        for modele, lien, quoi, remplace, ajoute in (
                (self.RevisionList, self.rl, 'listes', 'listes_remplacees', 'listes_ajoutees'),
                (self.UpcomingTest, self.ut, 'devoirs', 'devoirs_remplaces', 'devoirs_ajoutes')):
            if modele is None:
                continue
            ids = lien.proprietaires(source.id)
            if not ids:
                continue
            lignes = list(modele.objects.filter(pk__in=ids).values('id', 'user_id', *(
                ['class_level_id'] if quoi == 'devoirs' else [])))
            profils = self.profils({x['user_id'] for x in lignes})
            niveaux = (self.rll.par_proprietaire(ids) if quoi == 'listes'
                       else {x['id']: {x['class_level_id']} - {None} for x in lignes})
            for x in lignes:
                cote = self.cote(niveaux.get(x['id'], set()), profils.get(x['user_id']), b_ids, k_ids)
                if cote == 'B':
                    if lien.remplacer(x['id'], source.id, cible.id):
                        bilan[remplace].append(x['id'])
                elif cote is None and lien.ajouter(x['id'], cible.id):
                    bilan[ajoute].append(x['id'])
        return dict(bilan)

    # ── références d'un chapitre source repliées dans une cible (« fusion »)
    def replier_section(self, sec, cible, nom_source):
        S = self.NotebookSection
        autre = S.objects.filter(notebook_id=sec.notebook_id, chapter_id=cible.id).first()
        if autre is None:
            S.objects.filter(pk=sec.pk).update(chapter_id=cible.id)
            self.n += 1
            return 'repointee'
        E = self.NotebookLessonEntry
        deja = set(E.objects.filter(section_id=autre.pk).values_list('lesson_id', 'content_start', 'content_end'))
        suivant = (E.objects.filter(section_id=autre.pk).aggregate(m=Max('page_order'))['m'] or 0) + 1
        for e in E.objects.filter(section_id=sec.pk).order_by('page_order', 'id'):
            cle = (e.lesson_id, e.content_start, e.content_end)
            if cle in deja:
                E.objects.filter(pk=e.pk).delete()
            else:
                E.objects.filter(pk=e.pk).update(section_id=autre.pk, page_order=suivant)
                suivant += 1
                deja.add(cle)
            self.n += 1
        if (sec.user_notes or '').strip():
            notes = sec.user_notes.strip()
            if (autre.user_notes or '').strip():
                notes = f'{autre.user_notes.rstrip()}\n\n— {nom_source} —\n{notes}'
            S.objects.filter(pk=autre.pk).update(user_notes=notes)
        S.objects.filter(pk=sec.pk).delete()
        self.n += 1
        return 'repliee'

    def replier_evaluations(self, source, cible):
        A = self.SkillAssessment
        bilan = {'repointees': 0, 'repliees': 0}
        for a in A.objects.filter(chapter_id=source.id).order_by('id'):
            b = A.objects.filter(user_id=a.user_id, chapter_id=cible.id).first()
            if b is None:
                A.objects.filter(pk=a.pk).update(chapter_id=cible.id)
                bilan['repointees'] += 1
            else:
                score, total = a.score + b.score, a.max_score + b.max_score
                reponses = dict(a.answers or {}) if isinstance(a.answers, dict) else {}
                reponses.update(b.answers or {} if isinstance(b.answers, dict) else {})
                pct = score * 100 / total if total else 0
                niveau = next((nom for seuil, nom in SEUILS_QUIZ if pct >= seuil), 'beginner')
                A.objects.filter(pk=b.pk).update(
                    score=score, max_score=total, answers=reponses, time_spent=a.time_spent + b.time_spent,
                    attempts=max(a.attempts, b.attempts), completed_at=max(a.completed_at, b.completed_at),
                    level=niveau)
                A.objects.filter(pk=a.pk).delete()
                bilan['repliees'] += 1
            self.n += 1
        return {k: v for k, v in bilan.items() if v}

    def quiz_laisses(self, ch):
        out = {}
        if self.SkillQuestion is not None:
            qs = [{'id': i, 'chapitre': ch.name, 'enonce': (q or '')[:80]}
                  for i, q in self.SkillQuestion.objects.filter(chapter_id=ch.id).order_by('id').values_list('id', 'question')]
            if qs:
                out['quiz_a_reaffecter'] = qs
        if self.SkillAssessment is not None:
            n = self.SkillAssessment.objects.filter(chapter_id=ch.id).count()
            if n:
                out['resultats_quiz_laisses'] = n
        if self.PathChapter is not None:
            pcs = list(self.PathChapter.objects.filter(chapter_id=ch.id).values_list('id', flat=True))
            if pcs:
                out['parcours_laisses'] = pcs
        return out

    def fusion_chapitre(self, source, cible, doublon=False, contenus=True, garder_quiz=False):
        """Toutes les références de `source` vers `cible` (politique par table) ; `source` à supprimer ensuite."""
        if source.pk == cible.pk:
            return {}
        bilan = defaultdict(list)
        if contenus:
            for cid in self.cc.proprietaires(source.id):
                if self.remplacer_chapitre(cid, source, cible):
                    bilan['contenus'].append(cid)
        for tid in self.thc.proprietaires(source.id):
            if self.thc.remplacer(tid, source.id, cible.id):
                bilan['theoremes'].append(tid)
        for lien, quoi in ((self.rl, 'listes'), (self.ut, 'devoirs'), (self.tip, 'astuces_concours')):
            if lien is not None:
                for oid in lien.proprietaires(source.id):
                    if lien.remplacer(oid, source.id, cible.id):
                        bilan[quoi].append(oid)
        if garder_quiz:
            bilan.update(self.quiz_laisses(source))
        else:
            if self.SkillQuestion is not None:
                n = self.SkillQuestion.objects.filter(chapter_id=source.id).update(chapter_id=cible.id)
                if n:
                    self.n += n
                    bilan['questions_quiz_repointees'] = n
            if self.SkillAssessment is not None:
                bilan.update({f'resultats_quiz_{k}': v for k, v in self.replier_evaluations(source, cible).items()})
            if self.PathChapter is not None:
                for pc in self.PathChapter.objects.filter(chapter_id=source.id).order_by('id'):
                    if self.PathChapter.objects.filter(learning_path_id=pc.learning_path_id, chapter_id=cible.id).exists():
                        bilan['parcours_en_conflit'].append(pc.id)
                    else:
                        self.PathChapter.objects.filter(pk=pc.pk).update(chapter_id=cible.id)
                        self.n += 1
                        bilan['parcours_repointes'].append(pc.id)
        if self.NotebookSection is not None:
            for sec in self.NotebookSection.objects.filter(chapter_id=source.id).order_by('id'):
                bilan['sections_cahier_' + self.replier_section(sec, cible, source.name)].append(sec.id)
        if doublon:
            for lv in self.chl.cibles(source.id):
                self.chl.ajouter(cible.id, lv)
        self.remplace_ch[source.id] = cible.id
        self.a_supprimer['chapitres'].append(source.id)
        return {k: v for k, v in bilan.items() if v}

    def fusion_theoreme(self, source, cible, doublon=False):
        if source.pk == cible.pk:
            return []
        contenus = [cid for cid in self.ct.proprietaires(source.id) if self.ct.remplacer(cid, source.id, cible.id)]
        if doublon:
            for ch in self.thc.cibles(source.id):
                self.thc.ajouter(cible.id, ch)
            for lv in self.thl.cibles(source.id):
                self.thl.ajouter(cible.id, lv)
        self.remplace_th[source.id] = cible.id
        self.a_supprimer['theoremes'].append(source.id)
        return contenus

    # ── opérations sur les chapitres
    def operation(self, **entree):
        self.r.setdefault('operations', []).append({k: v for k, v in entree.items() if v not in (None, [], {})})

    def scission(self, op):
        X, B = self.chapitre(op['de']), self.niveau(op['niveau'])
        if X is None or B is None:
            self.operation(op='scission', de=op['de'], vers=op['vers'], ignoree='chapitre ou niveau absent')
            return
        Xp = self.creer_chapitre(op['vers'], op['domaine'])
        K = self.chl.cibles(X.id) - {B.id}
        self.chl.ajouter(Xp.id, B.id)
        self.chl.retirer(X.id, B.id)
        bilan = defaultdict(list)
        ids = self.cc.proprietaires(X.id)
        niveaux = self.niveaux_contenus(ids)
        for cid in ids:
            L = niveaux.get(cid, set())
            if B.id not in L:
                continue
            if not L & K:
                if self.remplacer_chapitre(cid, X, Xp):
                    bilan['contenus_remplaces'].append(cid)
            elif self.ajouter_chapitre(cid, Xp):
                bilan['contenus_ajoutes'].append(cid)
        for tid in self.thc.proprietaires(X.id):
            L = self.thl.cibles(tid)
            if not L:
                bilan['theoremes_sans_niveau'].append(tid)
            elif B.id in L:
                if not L & K:
                    if self.thc.remplacer(tid, X.id, Xp.id):
                        bilan['theoremes_deplaces'].append(tid)
                elif self.thc.ajouter(tid, Xp.id):
                    bilan['theoremes_ajoutes'].append(tid)
        bilan.update(self.lignes_par_niveau(X, Xp, {B.id}, K))
        if self.tip is not None:
            for oid in self.tip.proprietaires(X.id):
                if self.tip.ajouter(oid, Xp.id):
                    bilan['astuces_concours'].append(oid)
        if self.NotebookSection is not None:
            for sec in self.NotebookSection.objects.filter(chapter_id=X.id, notebook__class_level_id=B.id).order_by('id'):
                bilan['sections_cahier_' + self.replier_section(sec, Xp, X.name)].append(sec.id)
        if self.PathChapter is not None:
            for pc in self.PathChapter.objects.filter(chapter_id=X.id).order_by('id'):
                if self.lpl.cibles(pc.learning_path_id) != {B.id}:
                    continue
                if self.PathChapter.objects.filter(learning_path_id=pc.learning_path_id, chapter_id=Xp.id).exists():
                    bilan['parcours_en_conflit'].append(pc.id)
                else:
                    self.PathChapter.objects.filter(pk=pc.pk).update(chapter_id=Xp.id)
                    self.n += 1
                    bilan['parcours_repointes'].append(pc.id)
        laisses = self.quiz_laisses(X)
        laisses.pop('parcours_laisses', None)
        self.operation(op='scission', de=X.name, vers=Xp.name, niveau=B.name, **bilan, **laisses)

    def fusion_programme(self, op):
        S = self.chapitre(op['de'])
        if S is None:
            return
        T = self.chapitre(op['vers'])
        if T is None:
            T = self.creer_chapitre(op['vers'], op['domaine'], self.chl.cibles(S.id))
        self.operation(op='fusion', de=S.name, vers=T.name, **self.fusion_chapitre(S, T))

    def detachement(self, op):
        X, D = self.chapitre(op['chapitre']), self.niveau(op['niveau'])
        if X is None or D is None:
            return
        T = self.chapitre(op['vers']) or self.creer_chapitre(op['vers'], op['domaine'], [D.id])
        self.chl.retirer(X.id, D.id)
        K = self.chl.cibles(X.id)
        bilan = defaultdict(list)
        ids = self.cc.proprietaires(X.id)
        niveaux = self.niveaux_contenus(ids)
        for cid in ids:
            L = niveaux.get(cid, set())
            if D.id not in L:
                continue
            if not L & K:
                if self.remplacer_chapitre(cid, X, T):
                    bilan['contenus_remplaces'].append(cid)
            elif self.ajouter_chapitre(cid, T):
                bilan['contenus_ajoutes'].append(cid)
        bilan.update(self.lignes_par_niveau(X, T, {D.id}, K))
        if self.NotebookSection is not None:
            for sec in self.NotebookSection.objects.filter(chapter_id=X.id, notebook__class_level_id=D.id).order_by('id'):
                bilan['sections_cahier_' + self.replier_section(sec, T, X.name)].append(sec.id)
        self.operation(op='detachement', chapitre=X.name, niveau=D.name, vers=T.name, **bilan, **self.quiz_laisses(X))

    def notions(self, structure):
        """(notions non transversales de chaque question, entièrement étiqueté ?)"""
        transversales = set(self.d['transversales'])
        par_question = [set(q) - transversales for q in _questions(structure)]
        return par_question, all(par_question)

    def ancien_ln_exp(self):
        op = self.d['ancien_ln_exp']
        S = self.chapitre(op['chapitre'])
        if S is None:
            return
        niveaux_s = self.chl.cibles(S.id)
        log, exp = (self.chapitre(op['log']) or self.creer_chapitre(op['log'], op['domaine'], niveaux_s),
                    self.chapitre(op['exp']) or self.creer_chapitre(op['exp'], op['domaine'], niveaux_s))
        bilan = defaultdict(list)
        ids = self.cc.proprietaires(S.id)
        self.niveaux_contenus(ids)
        structures = dict(self.Content.objects.filter(pk__in=ids).values_list('id', 'json_content'))
        for cid in ids:
            par_question, _entier = self.notions(structures.get(cid))
            toutes = set().union(*par_question) if par_question else set()
            if toutes and toutes <= set(op['notions_log']):
                cibles, quoi = [log], 'vers_logarithmes'
            elif toutes and toutes <= set(op['notions_exp']):
                cibles, quoi = [exp], 'vers_exponentielles'
            else:
                cibles, quoi = [log, exp], 'vers_les_deux'
            for c in cibles:
                self.ajouter_chapitre(cid, c)
            self.cc.retirer(cid, S.id)
            bilan[quoi].append(cid)
        bilan.update(self.fusion_chapitre(S, log, contenus=False, garder_quiz=True))
        for lv in list(self.chl.cibles(S.id)):
            self.chl.retirer(S.id, lv)
        self.operation(op='ancien_chapitre', de=S.name, vers=[log.name, exp.name], **bilan)

    def rattachements(self):
        for op in self.d['rattachements']:
            lv = self.niveau(op['niveau'])
            if lv is None:
                continue
            ch = self.creer_chapitre(op['chapitre'], op['domaine'])
            if self.chl.ajouter(ch.id, lv.id):
                self.operation(op='rattachement', chapitre=ch.name, niveau=lv.name)
        self.regle_primitives()
        self.regle_produit_vectoriel()

    def regle_primitives(self):
        op = self.d['primitives']
        CI, FP = self.chapitre(op['source']), self.chapitre(op['cible'])
        niveaux = {lv.id for lv in self.ClassLevel.objects.filter(name__in=op['niveaux'])}
        if CI is None or FP is None or not niveaux:
            return
        signes_th = set(self.Theorem.objects.filter(name__in=op['theoremes'], subject=self.maths)
                        .values_list('id', flat=True))
        ids = self.cc.proprietaires(CI.id)
        L = self.niveaux_contenus(ids)
        structures = dict(self.Content.objects.filter(pk__in=ids).values_list('id', 'json_content'))
        theoremes = self.ct.par_proprietaire(ids)
        bilan = defaultdict(list)
        for cid in ids:
            if not L.get(cid, set()) & niveaux:
                continue
            par_question, entier = self.notions(structures.get(cid))
            toutes = set().union(*par_question) if par_question else set()
            prim = toutes & set(op['notions'])
            if entier and prim and not toutes & set(op['notions_integrale']):
                if self.remplacer_chapitre(cid, CI, FP):
                    bilan['contenus_remplaces'].append(cid)
            elif prim or theoremes.get(cid, set()) & signes_th:
                if self.ajouter_chapitre(cid, FP):
                    bilan['contenus_ajoutes'].append(cid)
        if bilan:
            self.operation(op='primitives', de=CI.name, vers=FP.name, **bilan)

    def regle_produit_vectoriel(self):
        op = self.d['produit_vectoriel']
        PV, B = self.chapitre(op['cible']), self.niveau(op['niveau'])
        if PV is None or B is None:
            return
        signes_th = set(self.Theorem.objects.filter(name__in=op['theoremes'], subject=self.maths)
                        .values_list('id', flat=True))
        espace = {c.id: c for c in self.Chapter.objects.filter(name__in=op['chapitres_espace'], subject=self.maths)}
        niveaux_espace = {cid: self.chl.cibles(cid) for cid in espace}
        ids = sorted(set(self.cl.qs(b=B.id).values_list(self.cl.a, flat=True)))
        L = self.niveaux_contenus(ids)
        structures = dict(self.Content.objects.filter(pk__in=ids).values_list('id', 'json_content'))
        theoremes, chapitres = self.ct.par_proprietaire(ids), self.cc.par_proprietaire(ids)
        bilan = defaultdict(list)
        for cid in ids:
            par_question, entier = self.notions(structures.get(cid))
            toutes = set().union(*par_question) if par_question else set()
            if not (toutes & set(op['notions']) or theoremes.get(cid, set()) & signes_th):
                continue
            if self.ajouter_chapitre(cid, PV):
                bilan['contenus_ajoutes'].append(cid)
            if entier and toutes and toutes <= set(op['notions']):
                autres = L.get(cid, set()) - {B.id}
                for gid in chapitres.get(cid, set()) & set(espace):
                    if not niveaux_espace[gid] & autres and self.cc.retirer(cid, gid):
                        bilan['chapitre_espace_retire'].append(cid)
        if bilan:
            self.operation(op='produit_vectoriel', vers=PV.name, **bilan)

    # ── théorèmes
    def theoremes(self):
        op = self.d['theoremes']
        out = self.r.setdefault('theoremes', [])
        for de, vers in op['fusions']:
            S = self.theoreme(de)
            if S is not None:
                T = self.creer_theoreme(vers)
                out.append({'op': 'fusion', 'de': de, 'vers': vers, 'contenus': self.fusion_theoreme(S, T)})
        de, vers = op['scission_ancienne']
        S = self.theoreme(de)
        if S is not None:
            cibles = [self.creer_theoreme(v) for v in vers]
            contenus = self.ct.proprietaires(S.id)
            for cid in contenus:
                for c in cibles:
                    self.ct.ajouter(cid, c.id)
                self.ct.retirer(cid, S.id)
            self.remplace_th[S.id] = cibles[0].id
            self.a_supprimer['theoremes'].append(S.id)
            out.append({'op': 'ancien_theoreme', 'de': de, 'vers': vers, 'contenus': contenus})
        for nom, vers in op['suppressions']:
            S = self.theoreme(nom)
            if S is None:
                continue
            if vers:
                contenus = self.fusion_theoreme(S, self.creer_theoreme(vers))
            else:
                contenus = [cid for cid in self.ct.proprietaires(S.id) if self.ct.retirer(cid, S.id)]
                self.remplace_th[S.id] = None
                self.a_supprimer['theoremes'].append(S.id)
            out.append({'op': 'suppression', 'nom': nom, 'vers': vers, 'contenus': contenus})
        for de, vers in op['renommages']:
            S, N = self.theoreme(de), self.theoreme(vers)
            if S is not None and N is not None:
                out.append({'op': 'renommage (fusion)', 'de': de, 'vers': vers, 'contenus': self.fusion_theoreme(S, N)})
            elif S is not None:
                self.Theorem.objects.filter(pk=S.pk).update(
                    name=vers, subject=self.maths, subfield=self.domaine(self.d['domaine_theoreme'][vers]))
                self.n += 1
                out.append({'op': 'renommage', 'de': de, 'vers': vers, 'id': S.pk})
        for r in op['rattachements']:
            retirer = [c for c in (self.chapitre(n) for n in r.get('retirer', [])) if c]
            ajouter = [c for c in (self.chapitre(n) for n in r.get('ajouter', [])) if c]
            niveaux = [lv for lv in (self.niveau(n) for n in r.get('niveaux', [])) if lv]
            for nom in r['noms']:
                th = self.theoreme(nom)
                if th is None:
                    continue
                avant = self.n
                for c in ajouter:
                    self.thc.ajouter(th.id, c.id)
                for c in retirer:
                    self.thc.retirer(th.id, c.id)
                for lv in niveaux:
                    self.thl.ajouter(th.id, lv.id)
                if self.n != avant:
                    out.append({'op': 'rattachement', 'nom': nom})
        for c in op['creations']:
            avant = self.n
            th = self.creer_theoreme(c['nom'])
            for ch in (self.chapitre(n) for n in c['chapitres']):
                if ch:
                    self.thc.ajouter(th.id, ch.id)
            for lv in (self.niveau(n) for n in c['niveaux']):
                if lv:
                    self.thl.ajouter(th.id, lv.id)
            if self.n != avant:
                out.append({'op': 'creation', 'nom': c['nom']})

    # ── TaxonomyTimeSpent : donnée dérivée, reconstruite pour les taxonomies touchées
    def temps(self):
        CT, TTS, STT = self.ContentType, self.TaxonomyTimeSpent, self.StudyTimeTracker
        touches = {k: v for k, v in self.touches.items() if v}
        if not touches or CT is None or TTS is None or STT is None:
            return
        cts = {k: CT.objects.filter(app_label='caracteristics', model=k).first() for k in ('chapter', 'theorem', 'subfield')}
        ct_contenu = CT.objects.filter(app_label='things', model='content').first()
        if ct_contenu is None or not all(cts[k] for k in touches):
            self.r['temps'] = 'sauté (types de contenu absents)'
            return
        modeles = {'chapter': self.Chapter, 'theorem': self.Theorem, 'subfield': self.Subfield}
        liens = {'chapter': self.cc, 'theorem': self.ct, 'subfield': self.cs}
        supprimees, recreees = 0, []
        par_contenu = defaultdict(list)  # contenu → [(type, objet)]
        for kind, ids in touches.items():
            supprimees += TTS.objects.filter(taxonomy_type=kind, content_type=cts[kind], object_id__in=ids).delete()[0]
            existants = set(modeles[kind].objects.filter(pk__in=ids).values_list('id', flat=True))
            for cid, oid in liens[kind].t.objects.filter(**{liens[kind].b + '__in': existants}).values_list(
                    liens[kind].a, liens[kind].b):
                par_contenu[cid].append((kind, oid))
        types = dict(self.Content.objects.filter(pk__in=list(par_contenu)).values_list('id', 'type'))
        cumul = defaultdict(lambda: [0, 0, 0, 0])
        for user_id, cid, secondes in STT.objects.filter(
                content_type=ct_contenu, object_id__in=list(par_contenu), time_spent_seconds__gt=0).values_list(
                'user_id', 'object_id', 'time_spent_seconds'):
            for kind, oid in par_contenu[cid]:
                c = cumul[(user_id, kind, oid)]
                c[0] += secondes
                rang = {'exercise': 1, 'lesson': 2, 'exam': 3}.get(types.get(cid))
                if rang:
                    c[rang] += secondes
        for (user_id, kind, oid), (total, ex, le, exm) in cumul.items():
            recreees.append(TTS(user_id=user_id, taxonomy_type=kind, content_type=cts[kind], object_id=oid,
                                total_time=timedelta(seconds=total), exercise_time=timedelta(seconds=ex),
                                lesson_time=timedelta(seconds=le), exam_time=timedelta(seconds=exm)))
        TTS.objects.bulk_create(recreees, batch_size=500)
        self.r['temps'] = {'lignes_supprimees': supprimees, 'lignes_recreees': len(recreees),
                           'taxonomies': {k: sorted(v) for k, v in touches.items()}}

    # ── identifiants rangés ailleurs : UsageDaily « filtre », QCM de concours
    def _cible(self, table, oid):
        vus = set()
        while oid in table and oid not in vus:
            vus.add(oid)
            if table[oid] is None:
                return None
            oid = table[oid]
        return oid

    def identifiants(self):
        bilan = defaultdict(int)
        if self.UsageDaily is not None and (self.remplace_ch or self.remplace_th):
            U = self.UsageDaily
            lignes = U.objects.filter(Q(name__contains=':chapitre:') | Q(name__contains=':theoreme:'), kind='filtre')
            for row in lignes.order_by('id'):
                m = FILTRE.match(row.name)
                if not m:
                    continue
                table = self.remplace_ch if m['quoi'] == 'chapitre' else self.remplace_th
                oid = int(m['id'])
                if oid not in table:
                    continue
                cible = self._cible(table, oid)
                if cible is None:
                    U.objects.filter(pk=row.pk).delete()
                    bilan['usage_supprimees'] += 1
                else:
                    nom = f"{m['liste']}:{m['quoi']}:{cible}"
                    autre = U.objects.filter(date=row.date, kind='filtre', name=nom).first()
                    if autre is None:
                        U.objects.filter(pk=row.pk).update(name=nom)
                        bilan['usage_renommees'] += 1
                    else:
                        U.objects.filter(pk=autre.pk).update(
                            count=autre.count + row.count, anon_count=autre.anon_count + row.anon_count,
                            visitors=max(autre.visitors, row.visitors),
                            anon_visitors=max(autre.anon_visitors, row.anon_visitors))
                        U.objects.filter(pk=row.pk).delete()
                        bilan['usage_additionnees'] += 1
                self.n += 1
        table = {str(s): self._cible(self.remplace_ch, s) for s in self.remplace_ch}
        if table:
            def remplacer(questions):
                change = False
                for q in _qcm(questions):
                    if q.get('chapter_id') is not None and str(q['chapter_id']) in table:
                        q['chapter_id'] = table[str(q['chapter_id'])]
                        change = True
                return change
            if self.ConcoursExam is not None:
                for pk, jc in self.ConcoursExam.objects.values_list('id', 'json_content'):
                    if isinstance(jc, dict) and remplacer(jc.get('questions')):
                        self.ConcoursExam.objects.filter(pk=pk).update(json_content=jc)
                        bilan['concours_sujets'] += 1
                        self.n += 1
            if self.SimulationSession is not None:
                for pk, snap in self.SimulationSession.objects.values_list('id', 'questions_snapshot'):
                    if remplacer(snap):
                        self.SimulationSession.objects.filter(pk=pk).update(questions_snapshot=snap)
                        bilan['concours_sessions'] += 1
                        self.n += 1
            if self.SimulationAnswer is not None:
                for s, t in table.items():
                    n = self.SimulationAnswer.objects.filter(chapter_id=int(s)).update(chapter_id=t)
                    bilan['concours_reponses'] += n
                    self.n += n
        if bilan:
            self.r['identifiants'] = dict(bilan)

    # ── cahiers : section de chaque chapitre du programme du niveau, sections dans l'ordre du programme
    def cahiers(self):
        if self.Notebook is None or self.NotebookSection is None:
            return
        S = self.NotebookSection
        ids = {}
        bilan = defaultdict(int)
        for nb in self.Notebook.objects.filter(subject=self.maths).select_related('class_level').order_by('id'):
            noms = [nom for nom, _dom in self.d['programme'].get(nb.class_level.name, [])]
            if not noms:
                continue
            for nom in noms:
                if nom not in ids:
                    ch = self.chapitre(nom)
                    ids[nom] = ch.id if ch else None
            programme = [ids[n] for n in noms if ids[n]]
            sections = list(S.objects.filter(notebook_id=nb.pk).order_by('order', 'id').values('id', 'chapter_id', 'order'))
            presents = {s['chapter_id'] for s in sections}
            for cid in programme:
                if cid not in presents:
                    s = S.objects.create(notebook_id=nb.pk, chapter_id=cid, order=0)
                    sections.append({'id': s.pk, 'chapter_id': cid, 'order': None})
                    bilan['sections_creees'] += 1
                    self.n += 1
            rangs = {cid: i for i, cid in enumerate(programme)}
            hors = [s for s in sections if s['chapter_id'] not in rangs]
            for s in sections:
                voulu = rangs[s['chapter_id']] if s['chapter_id'] in rangs else len(rangs) + hors.index(s)
                if s['order'] != voulu:
                    S.objects.filter(pk=s['id']).update(order=voulu)
                    if s['order'] is not None:
                        bilan['sections_reordonnees'] += 1
                    self.n += 1
        if bilan:
            self.r['cahiers'] = dict(bilan)

    # ── fiches IA non publiées : anciens noms traduits (même règle de niveaux que l'import)
    def traduire(self, fiche):
        niveaux_fiche = {_cle(n) for n in fiche.get('niveaux') or [] if isinstance(n, str)}
        au_programme = defaultdict(set)
        for niveau, chapitres in self.d['programme'].items():
            for nom, _dom in chapitres:
                au_programme[nom].add(_cle(niveau))
        alias_ch = defaultdict(dict)
        for ancien, niveau, nouveaux in self.d['alias_chapitres']:
            alias_ch[_cle(ancien)][niveau] = (ancien, nouveaux)
        alias_th = {_cle(a): n for a, n in self.d['alias_theoremes']}
        chapitres = []
        for nom in fiche.get('chapitres') or []:
            regles = alias_ch.get(_cle(nom)) if isinstance(nom, str) else None
            if not regles:
                chapitres.append(nom)
            elif None in regles:
                chapitres += regles[None][1]
            else:
                for niveau, (ancien, nouveaux) in regles.items():
                    if _cle(niveau) in niveaux_fiche:
                        garde = bool(niveaux_fiche & (au_programme[ancien] - {_cle(niveau)}))
                        chapitres += ([nom] if garde else []) + list(nouveaux)
                        break
                else:
                    chapitres.append(nom)
        theoremes = []
        for nom in fiche.get('theoremes') or []:
            nouveaux = alias_th.get(_cle(nom)) if isinstance(nom, str) else None
            theoremes += [nom] if nouveaux is None else list(nouveaux)

        def unique(noms):
            vus, out = set(), []
            for n in noms:
                k = _cle(n) if isinstance(n, str) else n
                if k not in vus:
                    vus.add(k)
                    out.append(n)
            return out
        return unique(chapitres), unique(theoremes)

    def fiches_ia(self):
        if self.IAJob is None:
            return
        reecrits = []
        for job in self.IAJob.objects.filter(status__in=STATUTS_IA).order_by('id'):
            result = job.result if isinstance(job.result, dict) else {}
            fiches = result.get('fiches')
            if not isinstance(fiches, list):
                continue
            change = False
            for f in fiches:
                if not isinstance(f, dict):
                    continue
                chapitres, theoremes = self.traduire(f)
                if chapitres != list(f.get('chapitres') or []) or theoremes != list(f.get('theoremes') or []):
                    if 'chapitres' in f or chapitres:
                        f['chapitres'] = chapitres
                    if 'theoremes' in f or theoremes:
                        f['theoremes'] = theoremes
                    change = True
            if change:
                self.IAJob.objects.filter(pk=job.pk).update(result=result)
                self.n += 1
                reecrits.append(job.pk)
        if reecrits:
            self.r['fiches_ia_reecrites'] = reecrits

    # ── suppressions finales
    def references_chapitre(self, cid, concours):
        refs = {'contenus': self.cc.qs(b=cid).count(), 'theoremes': self.thc.qs(b=cid).count()}
        for lien, quoi in ((self.rl, 'listes'), (self.ut, 'devoirs'), (self.tip, 'astuces_concours')):
            if lien is not None:
                refs[quoi] = lien.qs(b=cid).count()
        for modele, quoi in ((self.SkillQuestion, 'questions_quiz'), (self.SkillAssessment, 'resultats_quiz'),
                             (self.NotebookSection, 'sections_cahier'), (self.PathChapter, 'parcours')):
            if modele is not None:
                refs[quoi] = modele.objects.filter(chapter_id=cid).count()
        refs['concours'] = concours.get(str(cid), 0)
        if self.SimulationAnswer is not None:
            refs['concours'] += self.SimulationAnswer.objects.filter(chapter_id=cid).count()
        return {k: v for k, v in refs.items() if v}

    def concours_par_chapitre(self):
        compte = defaultdict(int)
        sources = []
        if self.ConcoursExam is not None:
            sources += [(jc or {}).get('questions') if isinstance(jc, dict) else None
                        for jc in self.ConcoursExam.objects.values_list('json_content', flat=True)]
        if self.SimulationSession is not None:
            sources += list(self.SimulationSession.objects.values_list('questions_snapshot', flat=True))
        for questions in sources:
            for q in _qcm(questions):
                if q.get('chapter_id') is not None:
                    compte[str(q['chapter_id'])] += 1
        return compte

    def renommer_ancien(self, modele, obj):
        suffixe = f' (ancien #{obj.pk})'
        modele.objects.filter(pk=obj.pk).update(name=obj.name.strip()[:100 - len(suffixe)] + suffixe)
        self.n += 1

    def oublier_temps(self, kind, oid):
        if self.ContentType is not None and self.TaxonomyTimeSpent is not None:
            ct = self.ContentType.objects.filter(app_label='caracteristics', model=kind).first()
            if ct is not None:
                self.n += self.TaxonomyTimeSpent.objects.filter(taxonomy_type=kind, content_type=ct, object_id=oid).delete()[0]

    def suppressions(self):
        bilan = {'chapitres_supprimes': [], 'chapitres_gardes': [], 'theoremes_supprimes': [], 'theoremes_gardes': []}
        concours = self.concours_par_chapitre()
        for cid in dict.fromkeys(self.a_supprimer['chapitres']):
            ch = self.Chapter.objects.filter(pk=cid).first()
            if ch is None:
                continue
            refs = self.references_chapitre(cid, concours)
            if refs:
                for lv in list(self.chl.cibles(cid)):
                    self.chl.retirer(cid, lv)
                self.renommer_ancien(self.Chapter, ch)
                bilan['chapitres_gardes'].append({'id': cid, 'nom': ch.name, 'references': refs})
            else:
                self.Chapter.objects.filter(pk=cid).delete()
                self.oublier_temps('chapter', cid)
                self.n += 1
                bilan['chapitres_supprimes'].append(ch.name)
        for tid in dict.fromkeys(self.a_supprimer['theoremes']):
            th = self.Theorem.objects.filter(pk=tid).first()
            if th is None:
                continue
            n = self.ct.qs(b=tid).count()
            if n:
                for lv in list(self.thl.cibles(tid)):
                    self.thl.retirer(tid, lv)
                for c in list(self.thc.cibles(tid)):
                    self.thc.retirer(tid, c)
                self.renommer_ancien(self.Theorem, th)
                bilan['theoremes_gardes'].append({'id': tid, 'nom': th.name, 'references': {'contenus': n}})
            else:
                self.Theorem.objects.filter(pk=tid).delete()
                self.oublier_temps('theorem', tid)
                self.n += 1
                bilan['theoremes_supprimes'].append(th.name)
        self.r['suppressions'] = {k: v for k, v in bilan.items() if v}


def rendre(r):
    """Rapport lisible (imprimé par la migration et par la répétition à blanc)."""
    lignes = [f"Programme officiel (caracteristics 0003){' — À BLANC, rien n’est gardé' if r.get('a_blanc') else ''}"]
    hors = r.get('hors_maths') or []
    lignes.append(f'Matières hors Mathématiques rattachées aux niveaux : {len(hors)} chapitre(s)')
    lignes += [f"  - {h['matiere']} › {h['chapitre']} (#{h['id']}) : {', '.join(h['niveaux'])} ; "
               f"{h['contenus']} contenu(s)" for h in hors]
    adm = r.get('administrateurs') or {}
    for quoi in ('chapitres', 'theoremes'):
        if adm.get(quoi):
            lignes.append(f'{"Chapitres" if quoi == "chapitres" else "Théorèmes"} d’administrateurs (non touchés) : '
                          + ' ; '.join(f"#{x['id']} {x['nom']}" for x in adm[quoi]))
    d = r.get('doublons') or {}
    for x in d.get('cles_corrigees', []) + d.get('fusionnes', []):
        lignes.append(f'  doublon/clé : {x}')
    for k in ('crees',):
        if r.get(k):
            lignes.append(f"Créés : chapitres {r[k]['chapitres']} ; théorèmes {r[k]['theoremes']}")
    for op in r.get('operations') or []:
        details = ', '.join(f'{k}={v}' for k, v in op.items() if k not in ('op', 'de', 'vers', 'chapitre', 'niveau'))
        titre = op.get('de') or op.get('chapitre') or ''
        niveau = f" ({op['niveau']})" if op.get('niveau') else ''
        lignes.append(f"[{op['op']}] {titre} → {op.get('vers', '')}{niveau}" + (f' : {details}' if details else ''))
    for t in r.get('theoremes') or []:
        lignes.append('[théorème] ' + ', '.join(f'{k}={v}' for k, v in t.items()))
    for k in ('temps', 'identifiants', 'cahiers', 'fiches_ia_reecrites', 'suppressions', 'contenus_sans_niveau'):
        if r.get(k):
            lignes.append(f'{k} : {r[k]}')
    lignes.append(f"Écritures : {r.get('changements', 0)}" + ('' if r.get('changements') else ' (rien à changer)'))
    return '\n'.join(lignes)


def appliquer(apps, donnees, a_blanc=False, log=print):
    """Applique le passage au programme officiel avec ces données figées ; renvoie le rapport (None si rien à faire)."""
    return _Migration(apps, donnees, a_blanc, log).executer()
