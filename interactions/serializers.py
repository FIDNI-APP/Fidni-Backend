from rest_framework import serializers
from .models import Vote,Save,Complete, TimeSpent
from things.models import Exercise
from users.serializers import UserSerializer
from users.models import ViewHistory
from caracteristics.serializers import ChapterSerializer, ClassLevelSerializer, SubjectSerializer, TheoremSerializer
from things.serializers import CommentSerializer, SolutionSerializer, ExerciseSerializer
import logging 



logger = logging.getLogger('django')


#----------------------------COMMENT-------------------------------


class VoteSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    exercise = ExerciseSerializer(read_only=True)
    comment = CommentSerializer(read_only=True)
    solution = SolutionSerializer(read_only=True)

    class Meta:
        model = Vote
        fields = ['id', 'value', 'created_at', 'updated_at','user','exercise','comment','solution']


class SaveSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    exercise = ExerciseSerializer(read_only=True)

    class Meta:
        model = Save
        fields = ['id','created_at','updated_at','user', 'exercise']
        
class CompleteSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    exercise = ExerciseSerializer(read_only=True)

    class Meta:
        model = Complete
        fields = ['id','created_at','updated_at','user', 'exercise']

class TimeSpentSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    exercise = ExerciseSerializer(read_only=True)

    class Meta:
        model = TimeSpent
        fields = ['id','created_at','updated_at','user', 'exercise']

class LessonSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    chapters = ChapterSerializer(many=True, read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    solution = SolutionSerializer(read_only=True)
    vote_count = serializers.IntegerField(read_only=True)
    user_vote = serializers.SerializerMethodField()
    view_count = serializers.IntegerField(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    subject = SubjectSerializer(read_only=True)
    theorems = TheoremSerializer(many = True)

    class Meta:
        model = Exercise
        fields = ['id', 'title', 'content', 'chapters', 'author', 'created_at', 'updated_at', 'view_count', 'comments', 'solution', 'vote_count', 'user_vote', 'class_levels', 'subject']

    def get_user_vote(self, obj):
        user = self.context['request'].user
        if user.is_authenticated:
            vote = obj.votes.filter(user=user).first()
            return vote.value if vote else None
        return None

    def update(self, instance, validated_data):
        chapters = validated_data.pop('chapters', None)
        class_levels = validated_data.pop('class_levels', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if chapters is not None:
            instance.chapters.set(chapters)
        if class_levels is not None:
            instance.class_levels.set(class_levels)
        instance.save()
        return instance
    
class ViewHistorySerializer(serializers.ModelSerializer):
    """Serializer for the ViewHistory model"""

    content_type = serializers.ReadOnlyField(source='content.content_type')
    content = ExerciseSerializer('content', read_only=True)
    viewed_at = serializers.ReadOnlyField()
    time_spent = serializers.ReadOnlyField(source='time_spent_in_seconds')
    
    class Meta:
        model = ViewHistory  
        fields = ('content', 'viewed_at', 'time_spent','content_type', 'content')
        read_only_fields = ('viewed_at', 'time_spent', 'content_type')