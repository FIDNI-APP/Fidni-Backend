from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import UserProfile


#----------------------------TOKEN SERIALIZER-------------------------------

class UserTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        
        # Add custom claims
        token['username'] = user.username
        token['email'] = user.email
        # You can add more user data to the token if needed
        
        return token
    
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # Add user data to response
        data['user'] = UserSerializer(self.user).data
        
        return data


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
            'date_joined',
            'profile',
            'is_active',
            'is_staff'
        )
        read_only_fields = ('date_joined', 'is_active', 'is_staff')


class UserUpdateSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(required=False)
    
    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'profile'
        )
        read_only_fields = ('id', 'email')  # Email can't be changed directly
        
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        
        # Update user fields
        instance = super().update(instance, validated_data)
        
        # Update profile fields
        if profile_data and hasattr(instance, 'profile'):
            profile_serializer = UserProfileSerializer(
                instance.profile, 
                data=profile_data, 
                partial=True
            )
            if profile_serializer.is_valid():
                profile_serializer.save()
        
        return instance


#----------------------------USERSTATS-------------------------------

class UserStatsSerializer(serializers.Serializer):
    exercisesCompleted = serializers.SerializerMethodField()
    lessonsCompleted = serializers.SerializerMethodField()
    totalUpvotes = serializers.SerializerMethodField()
    streak = serializers.IntegerField(source='profile.streak_days')
    level = serializers.IntegerField(source='profile.level')
    progress = serializers.IntegerField(source='profile.level_progress')

    def get_exercisesCompleted(self, obj):
        return self.context.get('stats', {}).get('exercisesCompleted', 0)

    def get_lessonsCompleted(self, obj):
        return self.context.get('stats', {}).get('lessonsCompleted', 0)

    def get_totalUpvotes(self, obj):
        return self.context.get('stats', {}).get('totalUpvotes', 0)


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