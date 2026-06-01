from rest_framework import serializers
from django.contrib.auth.models import User

from apps.caracteristics.models import Subject, ClassLevel
from apps.things.models import Content

from .models import (
    Classroom, ClassroomSubject, ClassroomMembership,
    TDList, TDListItem,
)


class _UserMiniSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'avatar')

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

    # Write fields
    subject_id = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), source='subject',
        write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = TDList
        fields = (
            'id', 'classroom', 'title', 'description',
            'subject_id', 'subject_name',
            'created_by_username',
            'due_date', 'created_at', 'updated_at',
            'items', 'item_count', 'progress',
        )
        read_only_fields = ('id', 'classroom', 'created_at', 'updated_at',
                            'items', 'item_count', 'progress',
                            'subject_name', 'created_by_username')

    def get_item_count(self, obj):
        return obj.items.count()

    def get_progress(self, obj):
        """Return {'completed': X, 'total': N} for the requesting user."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        from django.contrib.contenttypes.models import ContentType
        from apps.interactions.models import Complete

        items = list(obj.items.values_list('content_id', flat=True))
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
