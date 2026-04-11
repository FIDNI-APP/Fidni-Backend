"""
Logging models for tracking errors and system events
"""
from django.db import models
from django.contrib.auth import get_user_model
import json

User = get_user_model()


class ErrorLog(models.Model):
    """Track application errors and exceptions"""

    SEVERITY_CHOICES = [
        ('debug', 'Debug'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    STATUS_CHOICES = [
        ('new', 'New'),
        ('investigating', 'Investigating'),
        ('resolved', 'Resolved'),
        ('ignored', 'Ignored'),
    ]

    # Core fields
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='error', db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', db_index=True)
    message = models.TextField()
    exception_type = models.CharField(max_length=200, blank=True, null=True)
    traceback = models.TextField(blank=True, null=True)

    # Request context
    endpoint = models.CharField(max_length=500, blank=True, null=True, db_index=True)
    method = models.CharField(max_length=10, blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)

    # Additional context
    request_data = models.JSONField(blank=True, null=True)  # GET/POST params
    extra_context = models.JSONField(blank=True, null=True)  # Custom metadata

    # Metadata
    count = models.IntegerField(default=1)  # For grouping duplicate errors
    first_seen = models.DateTimeField(auto_now_add=True, db_index=True)
    last_seen = models.DateTimeField(auto_now=True, db_index=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_errors')
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-last_seen']
        indexes = [
            models.Index(fields=['-last_seen', 'severity']),
            models.Index(fields=['status', '-last_seen']),
        ]

    def __str__(self):
        return f"[{self.severity.upper()}] {self.message[:100]}"

    def increment_count(self):
        """Increment count for duplicate errors"""
        self.count += 1
        self.save(update_fields=['count', 'last_seen'])


class APILog(models.Model):
    """Track API requests for monitoring and debugging"""

    # Request info
    method = models.CharField(max_length=10)
    endpoint = models.CharField(max_length=500, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    # Response info
    status_code = models.IntegerField(db_index=True)
    response_time_ms = models.IntegerField()  # Response time in milliseconds

    # Data
    request_body = models.TextField(blank=True, null=True)
    response_body = models.TextField(blank=True, null=True)
    query_params = models.JSONField(blank=True, null=True)

    # Metadata
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'status_code']),
            models.Index(fields=['endpoint', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.method} {self.endpoint} - {self.status_code}"


class SystemEvent(models.Model):
    """Track important system events"""

    EVENT_TYPES = [
        ('startup', 'System Startup'),
        ('shutdown', 'System Shutdown'),
        ('migration', 'Database Migration'),
        ('deployment', 'Deployment'),
        ('config_change', 'Configuration Change'),
        ('user_action', 'User Action'),
        ('other', 'Other'),
    ]

    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    metadata = models.JSONField(blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.event_type}] {self.title}"


class PageView(models.Model):
    """Track page views for analytics"""

    # Page info
    path = models.CharField(max_length=500, db_index=True)
    page_title = models.CharField(max_length=200, blank=True, null=True)
    referrer = models.CharField(max_length=500, blank=True, null=True)

    # User info
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    session_id = models.CharField(max_length=100, db_index=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)

    # Device/browser info
    device_type = models.CharField(max_length=50, blank=True, null=True)
    browser = models.CharField(max_length=50, blank=True, null=True)
    os = models.CharField(max_length=50, blank=True, null=True)

    # Timing
    time_on_page = models.IntegerField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'path']),
            models.Index(fields=['session_id', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.path} - {self.timestamp}"


class UserInteraction(models.Model):
    """Track user interactions for A/B testing"""

    INTERACTION_TYPES = [
        ('click', 'Click'),
        ('hover', 'Hover'),
        ('scroll', 'Scroll'),
        ('form_submit', 'Form Submit'),
        ('search', 'Search'),
        ('filter', 'Filter'),
        ('sort', 'Sort'),
        ('video_play', 'Video Play'),
        ('video_pause', 'Video Pause'),
        ('tab_switch', 'Tab Switch'),
        ('modal_open', 'Modal Open'),
        ('modal_close', 'Modal Close'),
        ('other', 'Other'),
    ]

    interaction_type = models.CharField(max_length=50, choices=INTERACTION_TYPES, db_index=True)
    element_id = models.CharField(max_length=200, blank=True, null=True)
    element_class = models.CharField(max_length=200, blank=True, null=True)
    element_text = models.CharField(max_length=500, blank=True, null=True)
    element_position = models.JSONField(blank=True, null=True)

    page_path = models.CharField(max_length=500, db_index=True)
    variant = models.CharField(max_length=100, blank=True, null=True)

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    session_id = models.CharField(max_length=100, db_index=True)

    metadata = models.JSONField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'interaction_type']),
            models.Index(fields=['page_path', 'element_id']),
            models.Index(fields=['variant', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.interaction_type} - {self.element_id or self.element_text}"


class UserSession(models.Model):
    """Track user sessions"""

    session_id = models.CharField(max_length=100, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    device_type = models.CharField(max_length=50, blank=True, null=True)
    browser = models.CharField(max_length=50, blank=True, null=True)
    os = models.CharField(max_length=50, blank=True, null=True)

    country = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)

    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_activity = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True)

    pages_viewed = models.IntegerField(default=0)
    interactions_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Session {self.session_id[:8]} - {self.started_at}"


class ABTestVariant(models.Model):
    """Define A/B test variants"""

    test_name = models.CharField(max_length=200, db_index=True)
    variant_name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    traffic_percentage = models.IntegerField(default=50)

    impressions = models.IntegerField(default=0)
    conversions = models.IntegerField(default=0)
    conversion_rate = models.FloatField(default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['test_name', 'variant_name']
        ordering = ['test_name', 'variant_name']

    def __str__(self):
        return f"{self.test_name} - {self.variant_name}"

    def calculate_conversion_rate(self):
        if self.impressions > 0:
            self.conversion_rate = (self.conversions / self.impressions) * 100
        else:
            self.conversion_rate = 0.0
        self.save(update_fields=['conversion_rate'])
