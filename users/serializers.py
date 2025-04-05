# users/serializers.py - Mise à jour pour inclure les nouveaux champs
from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserProfile, SubjectGrade
from caracteristics.models import ClassLevel, Subject

class SubjectGradeSerializer(serializers.ModelSerializer):
    subject_name = serializers.SerializerMethodField()
    
    class Meta:
        model = SubjectGrade
        fields = ('id', 'subject', 'subject_name', 'min_grade', 'max_grade')
        read_only_fields = ('id',)
    
    def get_subject_name(self, obj):
        return obj.subject.name


class UserProfileSerializer(serializers.ModelSerializer):
    reputation = serializers.ReadOnlyField()
    contribution_stats = serializers.SerializerMethodField()
    learning_stats = serializers.SerializerMethodField()
    subject_grades = SubjectGradeSerializer(many=True, read_only=True)
    class_level_name = serializers.SerializerMethodField()
    
    class Meta:
        model = UserProfile
        fields = (
            'bio', 'avatar', 'favorite_subjects', 'reputation',
            'location', 'last_activity_date', 'joined_at',
            'class_level', 'class_level_name', 'user_type', 'onboarding_completed',
            'display_email', 'display_stats',
            'email_notifications', 'comment_notifications', 'solution_notifications',
            'contribution_stats', 'learning_stats', 'subject_grades'
        )
        read_only_fields = ('reputation', 'last_activity_date', 'joined_at')
    
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


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=False)
    is_self = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'date_joined', 'profile', 'is_self'
        )
        read_only_fields = ('date_joined', 'is_self')
    
    def get_is_self(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
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
            
            # Extract and process subject_grades if present
            subject_grades_data = profile_data.pop('subject_grades', None)
            
            # Update other profile fields
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            
            # Handle class_level FK relationship
            class_level_id = profile_data.get('class_level')
            if class_level_id:
                try:
                    class_level = ClassLevel.objects.get(id=class_level_id)
                    profile.class_level = class_level
                except ClassLevel.DoesNotExist:
                    pass
            
            profile.save()
            
            # Process subject grades if provided
            if subject_grades_data:
                # Clear existing grades and create new ones
                profile.subject_grades.all().delete()
                
                for grade_data in subject_grades_data:
                    subject_id = grade_data.get('subject')
                    try:
                        subject = Subject.objects.get(id=subject_id)
                        SubjectGrade.objects.create(
                            user_profile=profile,
                            subject=subject,
                            min_grade=grade_data.get('min_grade', 0),
                            max_grade=grade_data.get('max_grade', 20)
                        )
                    except Subject.DoesNotExist:
                        pass
        
        return instance


# Serializer spécifique pour l'onboarding
class OnboardingSerializer(serializers.Serializer):
    class_level = serializers.PrimaryKeyRelatedField(queryset=ClassLevel.objects.all())
    user_type = serializers.ChoiceField(choices=UserProfile.USER_TYPE_CHOICES)
    bio = serializers.CharField(required=False, allow_blank=True)
    favorite_subjects = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all())
    )
    subject_grades = serializers.ListField(
        child=SubjectGradeSerializer(),
        required=False
    )
    
    def update(self, instance, validated_data):
        # Extract and process subject_grades
        subject_grades_data = validated_data.pop('subject_grades', None)
        favorite_subjects = validated_data.pop('favorite_subjects', [])
        
        # Update profile fields
        profile = instance.profile
        profile.class_level = validated_data.get('class_level')
        profile.user_type = validated_data.get('user_type')
        profile.bio = validated_data.get('bio', profile.bio)
        
        # Update favorite_subjects as a list of subject IDs
        profile.favorite_subjects = [str(subject.id) for subject in favorite_subjects]
        
        # Mark onboarding as completed
        profile.onboarding_completed = True
        
        profile.save()
        
        # Process subject grades if provided
        if subject_grades_data:
            # Clear existing grades and create new ones
            profile.subject_grades.all().delete()
            
            for grade_data in subject_grades_data:
                subject = grade_data.get('subject')
                if subject:
                    SubjectGrade.objects.create(
                        user_profile=profile,
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