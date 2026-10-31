# apps/skilliq/models.py
from django.db import models
from django.contrib.auth.models import User

# Deux quiz par chapitre et par niveau (31/10/2026, Natsu) : le quiz du cours (QCM sur le cours, l'existant) et
# l'approfondissement (vrais problèmes en QCM, avec des propositions pièges). Questions, passages et résultats sont
# rangés par type ; la maîtrise (« Ma progression », plan de DS) ne lit que le quiz du cours.
COURS, APPROFONDISSEMENT = 'cours', 'approfondissement'
TYPES = [(COURS, 'Quiz du cours'), (APPROFONDISSEMENT, 'Approfondissement')]
TYPES_VALIDES = {k for k, _ in TYPES}


def type_valide(valeur):
    """Type de quiz lu dans une requête ou un fichier : « approfondissement », sinon le quiz du cours."""
    return APPROFONDISSEMENT if valeur == APPROFONDISSEMENT else COURS


class SkillQuestion(models.Model):
    """Quiz question for skill assessment"""
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]

    chapter = models.ForeignKey(
        'caracteristics.Chapter',
        on_delete=models.CASCADE,
        related_name='skill_questions'
    )
    question = models.TextField()
    options = models.JSONField(help_text="List of answer options")
    correct_answer = models.PositiveSmallIntegerField(help_text="Index of correct answer (0-based)")
    # Plusieurs bonnes réponses (16/10/2026, Natsu : « 2 choix justes sur 5 proposés ») : index des bonnes réponses,
    # 2 au moins ; vide = question à une seule bonne réponse (`correct_answer`). `correct_answer` reste le premier
    # index juste (compatibilité). Juste ssi l'ensemble coché == l'ensemble juste (tout ou rien, comme learningpath).
    correct_answers = models.JSONField(default=list, blank=True,
                                       help_text="Index des bonnes réponses (vide : une seule, correct_answer)")
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='medium')
    explanation = models.TextField(blank=True, help_text="Explanation shown after answering")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    # Questions importées (13/10/2026, commande quiz_importer) : brouillon « à relire », jamais montré aux
    # élèves tant que l'administrateur ne l'a pas validé ; `motif` dit pourquoi elle a été écrite (admin seulement).
    SOURCE_CHOICES = [('', 'Administrateur'), ('claude', 'Rédigée par Claude')]
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, blank=True, default='')
    a_relire = models.BooleanField(default=False)
    motif = models.TextField(blank=True, default='')
    # Théorèmes (ou propriétés) qu'évalue la question (13/10/2026) : bilan « maîtrisé / à revoir » par théorème à
    # la fin du quiz, et tirage qui couvre chaque théorème.
    theorems = models.ManyToManyField('caracteristics.Theorem', blank=True, related_name='skill_questions')
    # Niveau du quiz (13/10/2026) : un quiz = (chapitre, niveau), jamais partagé entre deux niveaux. « Limites et
    # continuité » a un quiz 2ème Bac SM (avec arc tangente) et un quiz 2ème Bac PC/SVT (sans) : des questions
    # distinctes, mises en ligne séparément. Vide : question d'avant ce découpage, jamais servie.
    class_level = models.ForeignKey('caracteristics.ClassLevel', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='skill_questions')
    # Première mise en ligne (13/10/2026) : un quiz de chapitre est « Nouveau » 14 jours (skilliq/annonces.py).
    en_ligne_le = models.DateTimeField(null=True, blank=True)
    # Quiz du cours ou approfondissement (31/10/2026) : deux quiz distincts par (chapitre, niveau).
    type = models.CharField(max_length=20, choices=TYPES, default=COURS, db_index=True)

    class Meta:
        app_label = 'skilliq'
        ordering = ['difficulty', 'id']

    def __str__(self):
        return f"{self.chapter.name}: {self.question[:50]}..."

    def bonnes(self):
        """Index des bonnes réponses, triés : [correct_answer] pour une question à une seule bonne réponse."""
        multiples = self.correct_answers if isinstance(self.correct_answers, list) else []
        multiples = sorted({i for i in multiples if isinstance(i, int) and not isinstance(i, bool)})
        return multiples or [self.correct_answer]

    def est_juste(self, reponse):
        """Réponse de l'élève (index, liste d'index, -1 / None : sans réponse) : juste ssi l'ensemble coché est
        exactement l'ensemble des bonnes réponses (une bonne réponse oubliée ou une fausse cochée : faux)."""
        choix = choix_de(reponse)
        return bool(choix) and choix == self.bonnes()


def choix_de(reponse):
    """Réponse brute → liste triée des index cochés ([] : sans réponse ou illisible)."""
    valeurs = reponse if isinstance(reponse, list) else [reponse]
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in valeurs):
        return []
    return sorted({i for i in valeurs if i >= 0})


def reponse_valide(reponse, nb_options):
    """Réponse envoyée par le navigateur → réponse propre (index, ou liste triée d'index), ou None si invalide :
    index hors des choix, doublon, liste vide, autre chose qu'un entier."""
    if isinstance(reponse, bool):
        return None
    if isinstance(reponse, int):
        return reponse if 0 <= reponse < nb_options else None
    if isinstance(reponse, list) and reponse:
        if (any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < nb_options for i in reponse)
                or len(set(reponse)) != len(reponse)):
            return None
        return sorted(reponse)
    return None


class SkillAssessment(models.Model):
    """User's skill assessment result for a chapter"""
    LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='skill_assessments')
    chapter = models.ForeignKey(
        'caracteristics.Chapter',
        on_delete=models.CASCADE,
        related_name='assessments'
    )

    score = models.PositiveSmallIntegerField(default=0)
    max_score = models.PositiveSmallIntegerField(default=0)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='beginner')

    # Detailed results
    answers = models.JSONField(default=dict, help_text="Question ID -> user's answer index")
    time_spent = models.PositiveIntegerField(default=0, help_text="Time spent in seconds")

    # Score de la tentative précédente (10/10/2026) : « 40 % → 80 % » après un nouveau passage.
    previous_score = models.PositiveSmallIntegerField(null=True, blank=True)
    previous_max = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=1)
    # Bilan du dernier passage par théorème (13/10/2026) : [{id, name, justes, total, pct}], du moins maîtrisé
    # au mieux maîtrisé ; « non_evalues » à part. Vide pour les passages plus anciens.
    par_theoreme = models.JSONField(default=dict, blank=True)
    # Niveau du quiz passé (13/10/2026) : un résultat par (élève, chapitre, niveau). Vide : passage d'avant le
    # découpage par niveau, repris au prochain passage du quiz de son niveau.
    class_level = models.ForeignKey('caracteristics.ClassLevel', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')

    # Correction figée du dernier passage (14/10/2026), remplacée au passage suivant (un seul gardé, pour ne pas
    # charger la base) : [{id, question, options, correct_answer, correct_answers, your_answer, is_correct, explanation,
    # theoremes}]
    # dans l'ordre servi. Une question modifiée ou supprimée ensuite ne change rien à ce que l'élève revoit.
    derniere_correction = models.JSONField(default=list, blank=True)
    # Quiz du cours ou approfondissement (31/10/2026) : un résultat par (élève, chapitre, niveau, type).
    type = models.CharField(max_length=20, choices=TYPES, default=COURS, db_index=True)

    completed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'skilliq'
        unique_together = ('user', 'chapter', 'class_level', 'type')
        ordering = ['-completed_at']

    def __str__(self):
        return f"{self.user.username} - {self.chapter.name}: {self.level}"

    def calculate_level(self):
        """Calculate skill level based on score percentage"""
        if self.max_score == 0:
            return 'beginner'

        percentage = (self.score / self.max_score) * 100

        if percentage >= 90:
            return 'expert'
        elif percentage >= 70:
            return 'advanced'
        elif percentage >= 50:
            return 'intermediate'
        else:
            return 'beginner'

    def save(self, *args, **kwargs):
        self.level = self.calculate_level()
        super().save(*args, **kwargs)


class QuizEnCours(models.Model):
    """Passage commencé d'un quiz (chapitre, niveau) (14/10/2026), en base : le cache n'est pas partagé entre les
    workers. Un seul par (élève, chapitre, niveau), remplacé par un nouveau tirage, supprimé à l'envoi.

    - `questions` : ids servis, dans l'ordre ; l'envoi note TOUTES ces questions (sans réponse = fausse).
    - `reponses` : {id: index, ou liste d'index (plusieurs bonnes réponses)} verrouillées à la correction de chaque
      question (POST verifier/) : une réponse corrigée ne change plus, et seule une question de son passage peut être
      corrigée.
    - `temps` : secondes déjà passées hors corrections (statistiques ; plus de minuteur affiché depuis le 31/10/2026).
    Repris (mêmes questions, corrections déjà vues) pendant REPRISE_HEURES, puis oublié."""
    REPRISE_HEURES = 24

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quiz_en_cours')
    chapter = models.ForeignKey('caracteristics.Chapter', on_delete=models.CASCADE, related_name='+')
    class_level = models.ForeignKey('caracteristics.ClassLevel', on_delete=models.CASCADE, related_name='+')
    questions = models.JSONField(default=list)
    reponses = models.JSONField(default=dict, blank=True)
    temps = models.PositiveIntegerField(default=0)
    duree_secondes = models.PositiveIntegerField(default=0)
    debut = models.DateTimeField(auto_now_add=True)
    maj = models.DateTimeField(auto_now=True)
    # Quiz du cours ou approfondissement (31/10/2026) : un passage par (élève, chapitre, niveau, type).
    type = models.CharField(max_length=20, choices=TYPES, default=COURS, db_index=True)

    class Meta:
        app_label = 'skilliq'
        unique_together = ('user', 'chapter', 'class_level', 'type')
