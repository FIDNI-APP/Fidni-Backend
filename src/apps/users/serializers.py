# users/serializers.py - Mise à jour pour inclure les nouveaux champs
from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from .models import UserProfile, SubjectGrade
from apps.caracteristics.models import ClassLevel, Subject

class SubjectGradeSerializer(serializers.ModelSerializer):
    subject_name = serializers.SerializerMethodField()
    current_grade = serializers.SerializerMethodField()
    target_grade = serializers.SerializerMethodField()

    class Meta:
        model = SubjectGrade
        fields = ('id', 'subject', 'subject_name', 'min_grade', 'max_grade', 'current_grade', 'target_grade')
        read_only_fields = ('id',)

    def validate(self, attrs):
        for field in ('min_grade', 'max_grade'):
            if field in attrs and not 0 <= attrs[field] <= 20:
                raise serializers.ValidationError({field: 'Les notes vont de 0 à 20.'})
        return attrs

    def get_subject_name(self, obj):
        return obj.subject.name

    def get_current_grade(self, obj):
        """Return min_grade as current grade"""
        return float(obj.min_grade)

    def get_target_grade(self, obj):
        """Return max_grade as target grade"""
        return float(obj.max_grade)


class UserProfileSerializer(serializers.ModelSerializer):
    reputation = serializers.ReadOnlyField()
    contribution_stats = serializers.SerializerMethodField()
    learning_stats = serializers.SerializerMethodField()
    subject_grades = SubjectGradeSerializer(many=True, required=False)
    class_level_name = serializers.SerializerMethodField()
    target_subject_names = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    teaching_subject_names = serializers.SerializerMethodField()
    teaching_class_level_names = serializers.SerializerMethodField()
    students_count = serializers.SerializerMethodField()
    # Modifiés uniquement via /auth/user/update/ et l'onboarding (validation d'identité).
    school = serializers.SerializerMethodField()
    school_name = serializers.CharField(read_only=True)
    gender = serializers.CharField(read_only=True)
    birth_date = serializers.DateField(read_only=True)
    # Faux si le compte n'a pas accepté la version en vigueur des CGU / de la confidentialité.
    terms_up_to_date = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = (
            'bio', 'avatar', 'target_subjects', 'target_subject_names', 'reputation',
            'location', 'last_activity_date', 'joined_at',
            'class_level', 'class_level_name', 'user_type', 'onboarding_completed',
            'display_email', 'display_stats',
            'email_notifications', 'comment_notifications', 'solution_notifications',
            'contribution_stats', 'learning_stats', 'subject_grades',
            # Teacher fields
            'teaching_subjects', 'teaching_subject_names',
            'teaching_class_levels', 'teaching_class_level_names',
            'teacher_code', 'students_count',
            'school', 'school_name', 'gender', 'birth_date', 'terms_up_to_date',
        )
        read_only_fields = ('reputation', 'last_activity_date', 'joined_at', 'teacher_code')

    def get_terms_up_to_date(self, obj):
        from .legal import TERMS_VERSION
        return obj.terms_version == TERMS_VERSION

    def get_school(self, obj):
        s = obj.school
        return {'id': s.id, 'name': s.name, 'city': s.city, 'kind': s.kind} if s else None

    def get_avatar(self, obj):
        """Return full URL for avatar"""
        if obj.avatar_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.avatar_file.url)
            return obj.avatar_file.url
        return obj.avatar_url
    
    def get_contribution_stats(self, obj):
        # Only return stats if public or it's the user's own profile
        if obj.display_stats or self.context.get('is_owner', False):
            return obj.get_contribution_stats()
        return None
    
    def get_learning_stats(self, obj):
        # Only return stats if it's the user's own profile
        if self.context.get('is_owner', False):
            return obj.get_learning_stats()
        return None
    
    def get_class_level_name(self, obj):
        if obj.class_level:
            return obj.class_level.name
        return None

    def get_target_subject_names(self, obj):
        return [s.name for s in obj.target_subjects.all()]

    def get_teaching_subject_names(self, obj):
        return [s.name for s in obj.teaching_subjects.all()]

    def get_teaching_class_level_names(self, obj):
        return [cl.name for cl in obj.teaching_class_levels.all()]

    def get_students_count(self, obj):
        return obj.students.count()


class AuthorSerializer(serializers.ModelSerializer):
    """Auteur affiché sur un contenu, une solution ou un commentaire : juste de quoi l'afficher.

    Le UserSerializer complet recalculait les statistiques de contribution de l'auteur
    (plusieurs COUNT) pour chaque carte d'une liste. Le front ne lit que id, username, avatar.
    """
    avatar = serializers.SerializerMethodField()
    # Contribution d'un compte supprimé : le front l'affiche sans lien de profil.
    is_deleted = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'avatar', 'is_deleted')

    def get_is_deleted(self, obj):
        from .account_deletion import is_deleted_account
        return is_deleted_account(obj)

    def get_avatar(self, obj):
        from .account_deletion import is_deleted_account
        if is_deleted_account(obj):
            return None
        profile = getattr(obj, 'profile', None)
        if profile is None:
            return None
        if profile.avatar_file:
            request = self.context.get('request')
            return request.build_absolute_uri(profile.avatar_file.url) if request else profile.avatar_file.url
        return profile.avatar_url


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=False)
    is_self = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(read_only=True)  # Add this

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'date_joined', 'profile', 'is_self', 'is_superuser'
        )
        # L'e-mail se change par /api/auth/user/update/ (contrôle d'unicité), pas ici.
        read_only_fields = ('email', 'first_name', 'last_name', 'date_joined', 'is_self', 'is_superuser')

    # Réservés au propriétaire du compte : ce sérialiseur sert aussi pour l'auteur de
    # chaque contenu et commentaire, visibles de tous.
    PRIVATE_PROFILE_FIELDS = (
        'teacher_code', 'email_notifications', 'comment_notifications', 'solution_notifications',
        'subject_grades', 'onboarding_completed',
        # Élèves souvent mineurs : l'établissement ne se montre pas aux autres.
        'school', 'school_name', 'gender', 'birth_date', 'terms_up_to_date',
    )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        viewer = getattr(request, 'user', None) if request else None
        is_self = bool(viewer and getattr(viewer, 'is_authenticated', False) and viewer.id == instance.id)
        # Réponse de connexion (mot de passe, Google, lien de confirmation) : la requête est encore
        # anonyme, mais la vue sait que c'est le compte de celui qui vient de se connecter.
        if self.parent is None and self.context.get('is_owner') is True:
            is_self = True
        if is_self and self.parent is None:
            # Réglages du compte : « Définir un mot de passe », « Connecté avec Google », « Adresse à
            # confirmer ». Pas pour l'auteur imbriqué dans une liste (une requête de plus par ligne, inutile).
            data['has_password'] = instance.has_usable_password()
            data['google_linked'] = instance.google_accounts.exists()
            own_profile = getattr(instance, 'profile', None)
            data['email_verified'] = bool(own_profile is None or own_profile.email_verified)
        if is_self or (viewer and getattr(viewer, 'is_staff', False)):
            return data
        profile = getattr(instance, 'profile', None)
        if not (profile and profile.display_email):
            data.pop('email', None)
        data.pop('first_name', None)
        data.pop('last_name', None)
        if isinstance(data.get('profile'), dict):
            for field in self.PRIVATE_PROFILE_FIELDS:
                data['profile'].pop(field, None)
        return data

    def get_is_self(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
            return obj.id == request.user.id
        return False
    
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        
        # Update user data
        instance.username = validated_data.get('username', instance.username)
        instance.email = validated_data.get('email', instance.email)
        instance.save()
        
        # Update profile data
        if profile_data:
            profile = instance.profile

            # Première fin de l'onboarding : datée pour l'entonnoir du Pilotage.
            if profile_data.get('onboarding_completed') is True and not profile.onboarding_completed_at:
                profile.onboarding_completed_at = timezone.now()

            # Extract special fields that need special handling
            subject_grades_data = profile_data.pop('subject_grades', None)
            target_subjects_data = profile_data.pop('target_subjects', None)
            class_level_data = profile_data.pop('class_level', None)

            # Update simple profile fields
            for attr, value in profile_data.items():
                setattr(profile, attr, value)

            # Handle class_level FK relationship
            if class_level_data:
                try:
                    if isinstance(class_level_data, str):
                        class_level = ClassLevel.objects.get(id=class_level_data)
                    else:
                        class_level = class_level_data
                    profile.class_level = class_level
                except ClassLevel.DoesNotExist:
                    pass

            profile.save()

            # Handle target_subjects ManyToManyField (must be done after save)
            if target_subjects_data is not None:
                if isinstance(target_subjects_data, list):
                    # If it's a list of IDs (strings), convert to Subject objects
                    if all(isinstance(item, str) for item in target_subjects_data):
                        subjects = Subject.objects.filter(id__in=target_subjects_data)
                        profile.target_subjects.set(subjects)
                    else:
                        # Already Subject objects
                        profile.target_subjects.set(target_subjects_data)
                else:
                    profile.target_subjects.clear()

            # Objectifs de notes : la liste envoyée remplace l'ancienne (liste vide = tout retirer).
            if subject_grades_data is not None:
                profile.subject_grades.all().delete()
                for grade_data in subject_grades_data:
                    subject_or_id = grade_data.get('subject')
                    if isinstance(subject_or_id, Subject):
                        subject = subject_or_id
                    else:
                        subject = Subject.objects.filter(id=subject_or_id).first()
                    if subject is None:
                        continue
                    SubjectGrade.objects.create(
                        user=profile, subject=subject,
                        # current/target font foi : SubjectGrade.save() les recopie dans min/max.
                        current_grade=grade_data.get('min_grade', 10), target_grade=grade_data.get('max_grade', 15),
                    )

        return instance


class UserSettingsSerializer(serializers.ModelSerializer):
    """Serializer for user settings only"""
    class Meta:
        model = UserProfile
        fields = (
            'display_email', 'display_stats',
            'email_notifications', 'comment_notifications', 'solution_notifications',
            # Objectif d'étude quotidien : réglable depuis « Ma progression » (avant : seulement à l'inscription).
            'daily_goal_minutes',
        )

    def validate_daily_goal_minutes(self, value):
        if not 5 <= value <= 240:
            raise serializers.ValidationError('Entre 5 et 240 minutes.')
        return value


