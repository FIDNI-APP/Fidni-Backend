from rest_framework import serializers
from .models import ClassLevel, Subject, Chapter, Exercise, Solution, Comment, Vote, Subfield, Theorem, Save,Complete
from users.serializers import UserSerializer
from users.models import ViewHistory
import logging 



logger = logging.getLogger('django')


#----------------------------CLASS LEVELS/ SUBJECT / CHAPTER-------------------------------


class ClassLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassLevel
        fields = ['id', 'name', 'order']

class SubjectSerializer(serializers.ModelSerializer):
    class_levels = ClassLevelSerializer(many=True, read_only=True)

    class Meta:
        model = Subject
        fields = ['id', 'name', 'class_levels']
class SubfieldSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)


    class Meta:
        model = Subfield
        fields = ['id', 'name', 'subject', 'class_levels']


class ChapterSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    subfield = SubfieldSerializer(read_only = True)


    class Meta:
        model = Chapter
        fields = ['id', 'name', 'subject', 'class_levels', 'subfield']

class TheoremSerializer(serializers.ModelSerializer):
    subject = SubjectSerializer(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    chapters = ChapterSerializer(read_only = True)
    subfield = SubfieldSerializer(read_only=  True)


    class Meta:
        model = Theorem
        fields = ['id', 'name', 'subject', 'class_levels','chapters','subfield']
#----------------------------COMMENT-------------------------------


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    vote_count = serializers.IntegerField(read_only=True)
    user_vote = serializers.SerializerMethodField()
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    class Meta:
        model = Comment
        fields = ['id', 'content', 'author', 'created_at', 'replies', 'vote_count', 'user_vote','parent_id']

    def get_replies(self, obj):
        if obj.replies.exists():
            return CommentSerializer(obj.replies.all(), many=True, context=self.context).data
        return []

    def get_user_vote(self, obj):
        user = self.context['request'].user
        if user.is_authenticated:
            vote = obj.votes.filter(user=user).first()
            return vote.value if vote else None
        return None
#----------------------------SOLUTION-------------------------------


class SolutionSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    vote_count = serializers.IntegerField(read_only=True)
    user_vote = serializers.SerializerMethodField()

    class Meta:
        model = Solution
        fields = ['id', 'content', 'author', 'created_at', 'updated_at', 'vote_count', 'user_vote']

    def get_user_vote(self, obj):
        user = self.context['request'].user
        if user.is_authenticated:
            vote = obj.votes.filter(user=user).first()

            return vote.value if vote else None
        return None
    
#----------------------------EXERCISE-------------------------------


class ExerciseSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    chapters = ChapterSerializer(many=True, read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    solution = SolutionSerializer(read_only=True)
    vote_count = serializers.IntegerField(read_only=True)
    user_vote = serializers.SerializerMethodField()
    difficulty = serializers.CharField(source='get_difficulty_display')
    view_count = serializers.IntegerField(read_only=True)
    class_levels = ClassLevelSerializer(many=True, read_only=True)
    subject = SubjectSerializer(read_only=True)
    theorems = TheoremSerializer(many= True, read_only = True)
    subfields= SubfieldSerializer(many= True,read_only = True)
    user_save = serializers.SerializerMethodField()
    user_complete = serializers.SerializerMethodField()


    class Meta:
        model = Exercise
        fields = ['id', 'title', 'content', 'difficulty', 'chapters', 'author', 'created_at', 
                'updated_at', 'view_count', 'comments', 'solution', 'vote_count', 'user_vote', 
                'class_levels', 'subject','subfields','theorems','user_save','user_complete']

    def get_user_vote(self, obj):
        user = self.context['request'].user
        if user.is_authenticated:
            vote = obj.votes.filter(user=user).first()
            return vote.value if vote else None
        return None
    def get_user_save(self, obj):
        user = self.context['request'].user
        if user.is_authenticated:
            saved_exercise = obj.saved.filter(user=user).first()
            return saved_exercise is not None
        return False
    
    def get_user_complete(self, obj):
        user = self.context['request'].user
        if user.is_authenticated:
            completed_exercise = obj.completed.filter(user=user).first()

            return completed_exercise.status if completed_exercise else None
        return False

    def update(self, instance, validated_data):
        solution_content = validated_data.pop('solution_content', None)
        chapters = validated_data.pop('chapters', None)
        class_levels = validated_data.pop('class_levels', None)
        subfields = validated_data.pop('subfields', None)
        theorems = validated_data.pop('theorems', None)

        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        if chapters is not None:
            instance.chapters.set(chapters)
        if class_levels is not None:
            instance.class_levels.set(class_levels)
        if subfields is not None:
            instance.subfields.set(subfields)
        if theorems is not None:
            instance.theorems.set(theorems)
        
        if solution_content is not None:
            solution, created = Solution.objects.get_or_create(
                exercise=instance,
                defaults={'author': instance.author}
            )
            solution.content = solution_content
            solution.save()
        
        instance.save()
        return instance
    

    
class ExerciseCreateSerializer(serializers.ModelSerializer):
    solution_content = serializers.CharField(required=False, allow_blank=True)
    chapters = serializers.PrimaryKeyRelatedField(many=True, queryset=Chapter.objects.all(), required=False)
    class_levels = serializers.PrimaryKeyRelatedField(many=True, queryset=ClassLevel.objects.all(), required=False)
    subfields = serializers.PrimaryKeyRelatedField(many = True, queryset = Subfield.objects.all(), required= False )
    theorems = serializers.PrimaryKeyRelatedField(many = True,queryset = Theorem.objects.all(), required= False )


    class Meta:
        model = Exercise
        fields = [
            'title', 
            'content', 
            'difficulty',
            'chapters',
            'class_levels',
            'solution_content',
            'subject',
            'subfields',
            'theorems'

        ]

    def create(self, validated_data):
        solution_content = validated_data.pop('solution_content', None)
        chapters = validated_data.pop('chapters', [])
        class_levels = validated_data.pop('class_levels', [])
        subfields = validated_data.pop('subfields', [])
        theorems = validated_data.pop('theorems', [])


        logger.info(validated_data)
        
        exercise = Exercise.objects.create(
            author=self.context['request'].user,
            **validated_data
        )

        if chapters:
            exercise.chapters.set(chapters)
        if class_levels:
            exercise.class_levels.set(class_levels)
        if subfields:
            exercise.subfields.set(subfields)
        if theorems:
            exercise.theorems.set(theorems)
        
        if solution_content:
            Solution.objects.create(
                exercise=exercise,
                content=solution_content,
                author=exercise.author
            )
        
        return exercise

    def update(self, instance, validated_data):
        solution_content = validated_data.pop('solution_content', None)
        chapters = validated_data.pop('chapters', None)
        class_levels = validated_data.pop('class_levels', None)
        subfields = validated_data.pop('subfields', None)
        theorems = validated_data.pop('theorems', None)

        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        if chapters is not None:
            instance.chapters.set(chapters)
        if class_levels is not None:
            instance.class_levels.set(class_levels)
        if subfields is not None:
            instance.subfields.set(subfields)
        if theorems is not None:
            instance.theorems.set(theorems)
        
        if solution_content is not None:
            solution, created = Solution.objects.get_or_create(
                exercise=instance,
                defaults={'author': instance.author}
            )
            solution.content = solution_content
            solution.save()
        
        instance.save()
        return instance
class ViewHistorySerializer(serializers.ModelSerializer):
    content = ExerciseSerializer()

    class Meta:
        model = ViewHistory
        fields = ('content', 'viewed_at', 'completed')

class UserHistorySerializer(serializers.Serializer):
    recentlyViewed = ExerciseSerializer(many=True)
    upvoted = ExerciseSerializer(many=True)



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
    
