from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count

from apps.caracteristics.models import Subject, ClassLevel
from apps.things.models import Content

from .models import (
    Classroom, ClassroomSubject, ClassroomMembership,
    TDList, TDListItem,
)


class _UserMiniSerializer(serializers.ModelSerializer):
    """Élève ou prof en bref. L'e-mail n'est donné qu'au propriétaire de la classe (context
    show_email) : un élève ne voit jamais celui de ses camarades ni celui du prof."""
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'avatar')

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if not self.context.get('show_email'):
            data.pop('email', None)
        return data

    def get_avatar(self, obj):
        prof = getattr(obj, 'profile', None)
        if not prof:
            return None
        if prof.avatar_file:
            req = self.context.get('request')
            url = prof.avatar_file.url
            return req.build_absolute_uri(url) if req else url
        return prof.avatar_url


class ClassroomSubjectSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    teacher_username = serializers.CharField(source='teacher.username', read_only=True)
    teacher = _UserMiniSerializer(read_only=True)

    # Write-only fields used to set the FK on create/update
    subject_id = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), source='subject', write_only=True
    )
    teacher_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='teacher', write_only=True, required=False
    )

    class Meta:
        model = ClassroomSubject
        fields = (
            'id', 'subject_id', 'subject_name',
            'teacher', 'teacher_id', 'teacher_username',
            'created_at',
        )
        read_only_fields = ('id', 'created_at')


class ClassroomMembershipSerializer(serializers.ModelSerializer):
    student = _UserMiniSerializer(read_only=True)

    class Meta:
        model = ClassroomMembership
        fields = ('id', 'student', 'joined_at')
        read_only_fields = fields


class ClassroomSerializer(serializers.ModelSerializer):
    owner = _UserMiniSerializer(read_only=True)
    subjects = ClassroomSubjectSerializer(many=True, read_only=True)
    student_count = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    class_level_name = serializers.CharField(source='class_level.name', read_only=True)

    # Optional class_level on create/update
    class_level_id = serializers.PrimaryKeyRelatedField(
        queryset=ClassLevel.objects.all(), source='class_level',
        write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = Classroom
        fields = (
            'id', 'name', 'description',
            'owner', 'class_level_name', 'class_level_id',
            'join_code', 'subjects',
            'student_count', 'is_owner', 'is_member',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'owner', 'join_code', 'created_at', 'updated_at',
                            'student_count', 'is_owner', 'is_member', 'subjects',
                            'class_level_name')

    def get_student_count(self, obj):
        return obj.memberships.count()

    def _request_user(self):
        req = self.context.get('request')
        return req.user if req and req.user.is_authenticated else None

    def get_is_owner(self, obj):
        u = self._request_user()
        return bool(u and obj.owner_id == u.id)

    def get_is_member(self, obj):
        u = self._request_user()
        return bool(u and obj.memberships.filter(student_id=u.id).exists())

    def to_representation(self, instance):
        # E-mails (propriétaire, profs des matières) : pour le seul propriétaire de cette classe.
        ctx = self.context
        before = ctx.get('show_email')
        ctx['show_email'] = self.get_is_owner(instance)
        try:
            return super().to_representation(instance)
        finally:
            ctx['show_email'] = before


class TDListItemSerializer(serializers.ModelSerializer):
    content_id = serializers.PrimaryKeyRelatedField(
        queryset=Content.objects.all(), source='content', write_only=True
    )
    content_title = serializers.CharField(source='content.title', read_only=True)
    content_display_id = serializers.IntegerField(source='content.display_id', read_only=True)
    content_difficulty = serializers.CharField(source='content.difficulty', read_only=True)
    content_subject = serializers.CharField(source='content.subject.name', read_only=True)

    class Meta:
        model = TDListItem
        fields = (
            'id', 'content_id', 'content_title', 'content_display_id',
            'content_difficulty', 'content_subject', 'position', 'added_at',
        )
        read_only_fields = ('id', 'added_at')


class TDListSerializer(serializers.ModelSerializer):
    items = TDListItemSerializer(many=True, read_only=True)
    item_count = serializers.SerializerMethodField()
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    # Per-student progress (set by view depending on context)
    progress = serializers.SerializerMethodField()
    # Propriétaire : combien d'élèves de la classe ont réussi tout le TD (None pour un élève).
    class_progress = serializers.SerializerMethodField()

    # Write fields
    subject_id = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), source='subject',
        write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = TDList
        fields = (
            'id', 'classroom', 'title', 'description',
            'subject', 'subject_id', 'subject_name',
            'created_by_username',
            'due_date', 'created_at', 'updated_at',
            'items', 'item_count', 'progress', 'class_progress',
        )
        read_only_fields = ('id', 'classroom', 'created_at', 'updated_at',
                            'items', 'item_count', 'progress', 'class_progress',
                            'subject', 'subject_name', 'created_by_username')

    def get_item_count(self, obj):
        return obj.items.count()

    def get_progress(self, obj):
        """Return {'completed': X, 'total': N} for the requesting user."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        from apps.interactions.models import Complete

        items = [it.content_id for it in obj.items.all()]
        if not items:
            return {'completed': 0, 'total': 0}

        ct = ContentType.objects.get_for_model(Content)
        completed = Complete.objects.filter(
            user=request.user,
            content_type=ct,
            object_id__in=[str(i) for i in items],
            status='success',
        ).count()
        return {'completed': completed, 'total': len(items)}

    def get_class_progress(self, obj):
        """{finished, total} : élèves qui ont réussi tous les exercices du TD, sur les élèves de la classe.
        Pour le propriétaire seulement (None pour un élève)."""
        request = self.context.get('request')
        if not request or obj.classroom.owner_id != request.user.id:
            return None
        from apps.interactions.models import Complete
        # Élèves de la classe : lus une fois pour toute la liste des TD (même classe).
        if not hasattr(self, '_students_of'):
            self._students_of = {}
        cache = self._students_of
        if obj.classroom_id not in cache:
            cache[obj.classroom_id] = list(obj.classroom.memberships.values_list('student_id', flat=True))
        students = cache[obj.classroom_id]
        items = [str(it.content_id) for it in obj.items.all()]
        if not students or not items:
            return {'finished': 0, 'total': len(students)}
        finished = (Complete.objects.filter(user_id__in=students, content_type=ContentType.objects.get_for_model(Content),
                                            object_id__in=items, status='success')
                    .values('user_id').annotate(n=Count('id')).filter(n=len(items)).count())
        return {'finished': finished, 'total': len(students)}
