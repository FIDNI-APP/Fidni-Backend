"""Parcours de démonstration (14/11/2026) : 2ème Bac SM, mathématiques, pour montrer la page Parcours à quelqu'un.

Parcours n'est pas publié (PARCOURS_PUBLIC) : la démonstration n'est visible que de l'équipe. Toutes les leçons lisent
la même vidéo (choix de Natsu : la pub « Ne révise plus au hasard », 30 s), les chapitres sont ceux du programme et
les quiz sont de vraies questions corrigées. Avec --pour, ce compte a déjà fini le 1er chapitre et commencé le 2e,
pour que la carte montre les états terminé / en cours / verrouillé.

    python manage.py parcours_demo --fichier /chemin/pub.mp4 --pour <identifiant>   # crée (ou recrée) la démo
    python manage.py parcours_demo --video-url https://… --duree 30                # vidéo déjà en ligne
    python manage.py parcours_demo                                                 # recrée avec la même vidéo
    python manage.py parcours_demo --supprimer                                     # efface la démo et sa vidéo
"""
import mimetypes
import struct
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.caracteristics.models import Chapter, ClassLevel, Subject
from apps.learningpath.models import (
    ChapterQuiz, LearningPath, PathChapter, QuizQuestion, UserChapterProgress, UserLearningPathProgress,
    UserVideoProgress, Video,
)
from apps.uploads.models import FileAttachment

TITRE = 'Mathématiques, 2ème Bac SM'
DESCRIPTION = ('Parcours de démonstration : les chapitres de 2ème Bac SM dans l’ordre du programme, une courte vidéo '
               'par notion et un quiz pour valider chaque chapitre.')
NIVEAU, MATIERE = '2ème Bac SM', 'Mathématiques'
FICHIER_DEMO = 'parcours-demo.mp4'  # nom de la pièce jointe : la retrouver pour la supprimer ou la réutiliser
QUIZ_MINUTES = 5

# (chapitre du programme, titre affiché, description, [(vidéo, type)], [(question, bonne réponse, autres, explication)])
# Types : lesson = Cours, tips = Méthodes et astuces, demo = Exercice corrigé (front : progression.ts VIDEO_TYPES).
CHAPITRES = [
    ('Limites et continuité', 'Limites et continuité',
     'Limites usuelles, formes indéterminées et théorème des valeurs intermédiaires.',
     [('Limites : les règles à connaître', 'lesson'),
      ('Méthode : lever une forme indéterminée', 'tips'),
      ('Le théorème des valeurs intermédiaires', 'lesson')],
     [('Que vaut la limite de (sin x)/x quand x tend vers 0 ?', '1', ['0', '+∞', 'Elle n’existe pas'],
       'C’est une limite usuelle : (sin x)/x tend vers 1 quand x tend vers 0.'),
      ('f est continue sur [a ; b] et f(a)·f(b) < 0. Que peut-on affirmer ?',
       'f s’annule au moins une fois sur ]a ; b[',
       ['f est strictement monotone sur [a ; b]', 'f ne s’annule pas sur [a ; b]', 'f(a) = f(b)'],
       'f(a) et f(b) sont de signes contraires et f est continue : le théorème des valeurs intermédiaires donne '
       'un c de ]a ; b[ tel que f(c) = 0.'),
      ('Que vaut la limite de (x² + 1)/(2x² − 3) quand x tend vers +∞ ?', '1/2', ['0', '−1/3', '+∞'],
       'En +∞, une fonction rationnelle a la limite du quotient de ses termes de plus haut degré : x²/(2x²) = 1/2.')]),
    ('Dérivation et étude des fonctions', 'Dérivation et étude des fonctions',
     'Dérivée d’une composée, variations et étude complète d’une fonction.',
     [('Dérivée d’une fonction composée', 'lesson'),
      ('Méthode : étudier les variations', 'tips'),
      ('Exercice corrigé : une étude complète', 'demo')],
     [('Quelle est la dérivée de f(x) = x³ − 3x ?', '3x² − 3', ['3x² − 3x', 'x² − 3', '3x − 3'],
       '(x³)′ = 3x² et (3x)′ = 3, donc f′(x) = 3x² − 3.'),
      ('Si f′(x) > 0 pour tout x d’un intervalle I, alors f est :', 'strictement croissante sur I',
       ['strictement décroissante sur I', 'constante sur I', 'positive sur I'],
       'Une dérivée strictement positive sur un intervalle donne une fonction strictement croissante. Elle ne dit '
       'rien du signe de f.'),
      ('Quelle est la dérivée de x ↦ √(x² + 1) ?', 'x/√(x² + 1)',
       ['1/(2√(x² + 1))', '2x/√(x² + 1)', '2x·√(x² + 1)'],
       '(√u)′ = u′/(2√u) avec u = x² + 1 et u′ = 2x : on obtient 2x/(2√(x² + 1)) = x/√(x² + 1).')]),
    ('Suites numériques', 'Suites numériques',
     'Suites arithmétiques et géométriques, récurrence et convergence.',
     [('Suites arithmétiques et géométriques', 'lesson'),
      ('Méthode : raisonner par récurrence', 'tips'),
      ('Suites monotones et convergence', 'lesson')],
     [('(uₙ) est géométrique de raison 1/2 et u₀ = 8. Que vaut u₃ ?', '1', ['2', '4', '4/3'],
       'u₃ = u₀ × (1/2)³ = 8 × 1/8 = 1.'),
      ('Une suite croissante et majorée est :', 'convergente', ['divergente vers +∞', 'constante', 'périodique'],
       'Toute suite croissante et majorée converge.'),
      ('Que vaut la limite de (2/3)ⁿ quand n tend vers +∞ ?', '0', ['1', '2/3', '+∞'],
       'Pour −1 < q < 1, qⁿ tend vers 0 ; ici q = 2/3.')]),
    ('Fonctions logarithmiques', 'Fonctions logarithmiques',
     'La fonction ln, ses propriétés algébriques et ses limites usuelles.',
     [('La fonction ln et ses propriétés', 'lesson'),
      ('Méthode : résoudre une équation avec ln', 'tips'),
      ('Limites usuelles du logarithme', 'lesson')],
     [('Comment s’écrit ln 8 en fonction de ln 2 ?', '3 ln 2', ['4 ln 2', '8 ln 2', 'ln 2 + 3'],
       '8 = 2³ et ln(aⁿ) = n ln a, donc ln 8 = 3 ln 2.'),
      ('Que vaut la limite de (ln x)/x quand x tend vers +∞ ?', '0', ['1', '+∞', '−∞'],
       'Croissances comparées : x l’emporte sur ln x en +∞.'),
      ('Quel est le domaine de définition de f(x) = ln(x − 1) ?', ']1 ; +∞[', ['[1 ; +∞[', ']0 ; +∞[', 'ℝ'],
       'ln(x − 1) existe si et seulement si x − 1 > 0, c’est-à-dire x > 1.')]),
    ('Fonctions exponentielles', 'Fonctions exponentielles',
     'La fonction exponentielle, dérivée de eᵘ et croissances comparées.',
     [('La fonction exponentielle', 'lesson'),
      ('Méthode : dériver et étudier eᵘ', 'tips'),
      ('Exercice corrigé : croissances comparées', 'demo')],
     [('Quelle est la dérivée de x ↦ e²ˣ ?', '2e²ˣ', ['e²ˣ', '2x·e²ˣ', 'e²ˣ/2'],
       '(eᵘ)′ = u′eᵘ avec u = 2x et u′ = 2.'),
      ('Que vaut la limite de eˣ/x quand x tend vers +∞ ?', '+∞', ['0', '1', 'e'],
       'Croissances comparées : eˣ l’emporte sur x en +∞.'),
      ('Quelle est la solution de l’équation eˣ = 5 ?', 'x = ln 5', ['x = 5/e', 'x = e⁵', 'x = √5'],
       'ln est la réciproque de exp : eˣ = 5 équivaut à x = ln 5.')]),
    ('Nombres complexes', 'Nombres complexes',
     'Forme algébrique, module et argument, forme exponentielle, géométrie.',
     [('Forme algébrique, module et argument', 'lesson'),
      ('Forme exponentielle et formules d’Euler', 'lesson'),
      ('Méthode : interpréter géométriquement', 'tips')],
     [('Quel est le module de z = 3 + 4i ?', '5', ['7', '25', '√7'],
       '|z| = √(3² + 4²) = √25 = 5.'),
      ('Quelle est la forme exponentielle de z = 1 + i ?', '√2·e^(iπ/4)', ['2·e^(iπ/4)', '√2·e^(iπ/2)', 'e^(iπ/4)'],
       '|1 + i| = √2 et un argument est π/4 (cos θ = sin θ = √2/2).'),
      ('Que vaut i²⁰²⁶ ?', '−1', ['1', 'i', '−i'],
       'i⁴ = 1 et 2026 = 4 × 506 + 2, donc i²⁰²⁶ = i² = −1.')]),
]


def duree_mp4(path):
    """Durée d'un MP4 en secondes, lue dans la boîte « mvhd » (pas besoin de ffprobe sur le serveur)."""
    data = path.read_bytes()
    i = data.find(b'mvhd')
    if i < 0:
        raise CommandError('Durée introuvable dans ce fichier : passe --duree.')
    if data[i + 4] == 1:
        echelle, duree = struct.unpack('>IQ', data[i + 24:i + 36])
    else:
        echelle, duree = struct.unpack('>II', data[i + 16:i + 24])
    return max(1, round(duree / echelle))


def chercher_demo():
    niveau = ClassLevel.objects.filter(name=NIVEAU).first()
    if not niveau:
        return None
    return LearningPath.objects.filter(title=TITRE, class_level=niveau).first()


class Command(BaseCommand):
    help = 'Crée (ou recrée) le parcours de démonstration 2ème Bac SM, ou le supprime.'

    def add_arguments(self, parser):
        parser.add_argument('--fichier', help='Vidéo MP4 à envoyer dans le stockage du site (même vidéo pour toutes les leçons).')
        parser.add_argument('--video-url', help='Ou une vidéo déjà en ligne (YouTube, fichier…).')
        parser.add_argument('--duree', type=int, help='Durée de la vidéo en secondes (lue dans le fichier sinon).')
        parser.add_argument('--pour', help='Identifiant du compte qui a déjà fini le 1er chapitre et commencé le 2e.')
        parser.add_argument('--site', default='https://api.fidni.fr', help='Adresse de l’API (lien de la vidéo envoyée).')
        parser.add_argument('--supprimer', action='store_true', help='Efface la démonstration et sa vidéo.')

    def handle(self, *args, **o):
        if o['supprimer']:
            self.supprimer()
            return
        if o['fichier'] and o['video_url']:
            raise CommandError('--fichier ou --video-url, pas les deux.')
        eleve = None
        if o['pour']:
            eleve = User.objects.filter(username=o['pour']).first()
            if not eleve:
                raise CommandError(f'Compte introuvable : {o["pour"]}')
        niveau = ClassLevel.objects.filter(name=NIVEAU).first()
        matiere = Subject.objects.filter(name=MATIERE).first()
        if not niveau or not matiere:
            raise CommandError(f'Niveau « {NIVEAU} » ou matière « {MATIERE} » introuvable.')
        chapitres = {}
        for nom, *_ in CHAPITRES:
            ch = Chapter.objects.filter(name=nom, subject=matiere, class_levels=niveau).first()
            if not ch:
                raise CommandError(f'Chapitre introuvable pour {NIVEAU} : {nom}')
            chapitres[nom] = ch

        with transaction.atomic():
            url, duree, piece = self.video(o, eleve)
            ancien = chercher_demo()
            if ancien:
                ancien.delete()
            parcours = LearningPath.objects.create(
                subject=matiere, title=TITRE, description=DESCRIPTION, is_active=True,
                estimated_hours=Decimal(round((len(CHAPITRES) * (3 * duree + QUIZ_MINUTES * 60)) / 3600, 1) or '0.1'),
            )
            parcours.class_level.set([niveau])
            premiere = None
            for i, (nom, titre, description, videos, questions) in enumerate(CHAPITRES):
                part = PathChapter.objects.create(learning_path=parcours, chapter=chapitres[nom], title=titre,
                                                  description=description, order=i + 1)
                for j, (titre_video, type_video) in enumerate(videos):
                    v = Video.objects.create(path_chapter=part, title=titre_video, url=url, video_type=type_video,
                                             duration_seconds=duree, order=j + 1)
                    premiere = premiere or v
                quiz = ChapterQuiz.objects.create(
                    path_chapter=part, title=f'Valider : {titre}', passing_score=70, estimated_minutes=QUIZ_MINUTES,
                    description='Trois questions pour vérifier que le chapitre est acquis.',
                )
                for k, (texte, bonne, autres, explication) in enumerate(questions):
                    # La bonne réponse change de place d'une question à l'autre.
                    rang = (i + 2 * k + 1) % (len(autres) + 1)
                    options = autres[:rang] + [bonne] + autres[rang:]
                    QuizQuestion.objects.create(
                        quiz=quiz, question_text=texte, question_type='multiple_choice', options=options,
                        correct_answer_index=rang, explanation=explication, points=1, order=k + 1,
                        difficulty='easy' if k == 0 else 'medium',
                    )
            if piece:
                piece.object_id = premiere.pk
                piece.save(update_fields=['object_id'])
            if eleve:
                self.progression(eleve, parcours)

        self.stdout.write(self.style.SUCCESS(
            f'Parcours de démonstration créé (id {parcours.pk}) : {len(CHAPITRES)} chapitres, '
            f'{3 * len(CHAPITRES)} vidéos de {duree} s, {len(CHAPITRES)} quiz.'
            + (f' Progression de démonstration pour {eleve.username}.' if eleve else '')))
        self.stdout.write(f'Page : https://fidni.fr/parcours?parcours={parcours.pk}')

    def video(self, o, auteur):
        """URL et durée de la vidéo : fichier envoyé, URL donnée, ou celle de la démo précédente."""
        if o['video_url']:
            if not o['duree']:
                raise CommandError('Avec --video-url, donne aussi --duree (en secondes).')
            return o['video_url'], o['duree'], None
        if o['fichier']:
            path = Path(o['fichier'])
            if not path.is_file():
                raise CommandError(f'Fichier introuvable : {path}')
            mime = mimetypes.guess_type(path.name)[0]
            if mime != 'video/mp4':
                raise CommandError('Seul un fichier .mp4 est accepté.')
            duree = o['duree'] or duree_mp4(path)
            self.effacer_pieces()
            uploader = auteur or User.objects.filter(is_superuser=True).order_by('pk').first()
            piece = FileAttachment(uploaded_by=uploader, file_name=FICHIER_DEMO, file_size=path.stat().st_size,
                                   file_type='video', mime_type=mime,
                                   content_type=ContentType.objects.get_for_model(Video))
            with path.open('rb') as source:
                piece.file.name = piece.file.storage.save(f'parcours-videos/{FICHIER_DEMO}', File(source))
            piece.save()
            return f'{o["site"].rstrip("/")}/api/files/{piece.pk}/download/', duree, piece
        ancien = chercher_demo()
        v = Video.objects.filter(path_chapter__learning_path=ancien).first() if ancien else None
        if not v:
            raise CommandError('Pas encore de démonstration : donne --fichier ou --video-url.')
        return v.url, o['duree'] or v.duration_seconds, None

    def progression(self, eleve, parcours):
        """1er chapitre terminé (vidéos vues, quiz réussi), 2e commencé : 1re vidéo vue, 2e à 40 %."""
        maintenant = timezone.now()
        suivi = UserLearningPathProgress.objects.create(user=eleve, learning_path=parcours)
        chapitres = list(parcours.path_chapters.order_by('order')[:2])
        for n, part in enumerate(chapitres):
            cp = UserChapterProgress.objects.create(user=eleve, path_chapter=part, path_progress=suivi)
            videos = list(part.videos.order_by('order'))
            vues = videos if n == 0 else videos[:1]
            for v in vues:
                UserVideoProgress.objects.create(user=eleve, video=v, chapter_progress=cp,
                                                 watched_seconds=v.duration_seconds, is_completed=True,
                                                 completed_at=maintenant)
            if n == 0:
                cp.quiz_passed, cp.quiz_score, cp.quiz_attempts = True, 100, 1
                cp.save(update_fields=['quiz_passed', 'quiz_score', 'quiz_attempts'])
            else:
                v = videos[1]
                UserVideoProgress.objects.create(user=eleve, video=v, chapter_progress=cp,
                                                 watched_seconds=int(v.duration_seconds * 0.4))
            cp.refresh_completion()

    def effacer_pieces(self):
        for piece in FileAttachment.objects.filter(file_name=FICHIER_DEMO,
                                                   content_type=ContentType.objects.get_for_model(Video)):
            piece.delete_file()
            piece.delete()

    def supprimer(self):
        parcours = chercher_demo()
        if parcours:
            parcours.delete()
        self.effacer_pieces()
        self.stdout.write(self.style.SUCCESS('Démonstration supprimée.' if parcours else 'Aucune démonstration à supprimer.'))
