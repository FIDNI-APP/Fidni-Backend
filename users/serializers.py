from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserProfile



#----------------------------USERPROFILE-------------------------------

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = (
            'bio',
            'avatar',
            'favorite_subjects',
            'reputation',
            'github_username',
            'website',
            'location',
            'total_contributions',
            'total_upvotes_received',
            'total_comments',
            'streak_days',
            'level',
            'level_progress'
        )

#----------------------------USER-------------------------------

class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    
    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'email',
            'password',
            'date_joined',
            'profile',
        )
        read_only_fields = ('date_joined',)



#----------------------------USERSTATS-------------------------------

class UserStatsSerializer(serializers.Serializer):
    exercisesCompleted = serializers.SerializerMethodField()
    exercisesFailed = serializers.SerializerMethodField()
    exercisesUpvoted = serializers.SerializerMethodField()
    streak = serializers.IntegerField(source='profile.streak_days')
    level = serializers.IntegerField(source='profile.level')
    progress = serializers.IntegerField(source='profile.level_progress')

    def get_exercisesCompleted(self, obj):
        user = self.context['request'].user
        exercises_completed = obj.completed.filter(user=user,status='sucess').first()
        return exercises_completed
    def get_exercisesFailed(self,obj):
        user=self.context['request'].user
        exercises_failed = obj.completed.filter(user=user,status='review').first()
        return exercises_failed
        
    def get_exercisesUpvoted(self, obj):
        user = self.context['request'].user
        exercises_upvoted = obj.votes.filter(user=user,vote_value = 1).first()
        return exercises_upvoted
        
#----------------------------UPDATE USERPROFILE (TOCHANGE)-------------------------------

class UpdateUserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = (
            'bio',
            'avatar',
            'favorite_subjects',
            'github_username',
            'website',
            'location'
        )
