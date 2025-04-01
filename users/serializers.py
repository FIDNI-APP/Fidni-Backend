# users/serializers.py
from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserProfile, ViewHistory
from django.db.models import Count, Sum

class UserProfileSerializer(serializers.ModelSerializer):
    reputation = serializers.ReadOnlyField()
    contribution_stats = serializers.SerializerMethodField()
    learning_stats = serializers.SerializerMethodField()
    
    class Meta:
        model = UserProfile
        fields = (
            'bio', 'avatar', 'favorite_subjects', 'reputation',
            'location', 'last_activity_date',
            'display_email', 'display_stats',
            'email_notifications', 'comment_notifications', 'solution_notifications',
            'contribution_stats', 'learning_stats', 'joined_at'
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
            for attr, value in profile_data.items():
                setattr(instance.profile, attr, value)
            instance.profile.save()
        
        return instance

class ViewHistorySerializer(serializers.ModelSerializer):
    content_title = serializers.ReadOnlyField(source='content.title')
    content_difficulty = serializers.ReadOnlyField(source='content.difficulty')
    
    class Meta:
        model = ViewHistory
        fields = ('content', 'content_title', 'content_difficulty', 'viewed_at', 'completed', 'time_spent')

class UserSettingsSerializer(serializers.ModelSerializer):
    """Serializer for user settings only"""
    class Meta:
        model = UserProfile
        fields = (
            'display_email', 'display_stats',
            'email_notifications', 'comment_notifications', 'solution_notifications',
        )