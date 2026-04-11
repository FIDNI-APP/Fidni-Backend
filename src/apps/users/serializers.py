# users/serializers.py - Mise à jour pour inclure les nouveaux champs
from rest_framework import serializers
from django.contrib.auth.models import User
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
        )
        read_only_fields = ('reputation', 'last_activity_date', 'joined_at', 'teacher_code')

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


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=False)
    is_self = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(read_only=True)  # Add this

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'date_joined', 'profile', 'is_self', 'is_superuser'
        )
        read_only_fields = ('date_joined', 'is_self', 'is_superuser')
    
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

            # Extract special fields that need special handling
            subject_grades_data = profile_data.pop('subject_grades', None)
            target_subjects_data = profile_data.pop('target_subjects', None)
            class_level_data = profile_data.pop('class_level', None)

            # Debug logging
            print("=" * 50)
            print(f"Updating profile for {instance.username}")
            print(f"Subject grades data: {subject_grades_data}")
            print(f"Target subjects data: {target_subjects_data}")
            print(f"Class level data: {class_level_data}")
            print("=" * 50)

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
            
            # Process subject grades if provided
            if subject_grades_data:
                print(f"Processing {len(subject_grades_data)} subject grades...")
                # Clear existing grades and create new ones
                deleted_count = profile.subject_grades.all().delete()
                print(f"Deleted {deleted_count} existing grades")

                for i, grade_data in enumerate(subject_grades_data):
                    subject_or_id = grade_data.get('subject')
                    min_grade = grade_data.get('min_grade', 0)
                    max_grade = grade_data.get('max_grade', 20)
                    print(f"Grade {i}: subject={subject_or_id}, min={min_grade}, max={max_grade}")

                    try:
                        # Handle both Subject object and ID
                        if isinstance(subject_or_id, Subject):
                            subject = subject_or_id
                        else:
                            subject = Subject.objects.get(id=subject_or_id)

                        new_grade = SubjectGrade.objects.create(
                            user=profile,
                            subject=subject,
                            min_grade=min_grade,
                            max_grade=max_grade
                        )
                        print(f"✓ Created grade: {new_grade.id} for {subject.name}")
                    except Subject.DoesNotExist:
                        print(f"ERROR: Subject {subject_or_id} does not exist!")
                    except Exception as e:
                        print(f"ERROR creating grade: {e}")

                final_count = profile.subject_grades.count()
                print(f"Final subject_grades count: {final_count}")
            else:
                print("No subject_grades_data provided!")
        
        return instance


# Serializer spécifique pour l'onboarding
class OnboardingSerializer(serializers.Serializer):
    class_level = serializers.PrimaryKeyRelatedField(queryset=ClassLevel.objects.all())
    user_type = serializers.ChoiceField(choices=UserProfile.USER_TYPE_CHOICES)
    bio = serializers.CharField(required=False, allow_blank=True)
    target_subjects = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all())
    )
    subject_grades = serializers.ListField(
        child=SubjectGradeSerializer(),
        required=False
    )
    
    def update(self, instance, validated_data):
        # Extract and process subject_grades
        subject_grades_data = validated_data.pop('subject_grades', None)
        target_subjects = validated_data.pop('target_subjects', [])
        
        # Update profile fields
        profile = instance.profile
        profile.class_level = validated_data.get('class_level')
        profile.user_type = validated_data.get('user_type')
        profile.bio = validated_data.get('bio', profile.bio)

        # Mark onboarding as completed
        profile.onboarding_completed = True

        profile.save()

        # Update target_subjects (ManyToManyField - must be set after save())
        if target_subjects is not None:
            profile.target_subjects.set(target_subjects)
        
        # Process subject grades if provided
        if subject_grades_data:
            # Clear existing grades and create new ones
            profile.subject_grades.all().delete()
            
            for grade_data in subject_grades_data:
                subject = grade_data.get('subject')
                if subject:
                    SubjectGrade.objects.create(
                        user=profile,
                        subject=subject,
                        min_grade=grade_data.get('min_grade', 0),
                        max_grade=grade_data.get('max_grade', 20)
                    )
        
        return instance


class UserSettingsSerializer(serializers.ModelSerializer):
    """Serializer for user settings only"""
    class Meta:
        model = UserProfile
        fields = (
            'display_email', 'display_stats',
            'email_notifications', 'comment_notifications', 'solution_notifications',
        )


