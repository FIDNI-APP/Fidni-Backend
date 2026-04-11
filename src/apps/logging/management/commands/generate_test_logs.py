"""
Management command to generate test error logs
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.logging.models import ErrorLog, APILog, SystemEvent
from datetime import timedelta
import random


class Command(BaseCommand):
    help = 'Generate test error logs for testing the logging system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=20,
            help='Number of test errors to generate (default: 20)'
        )

    def handle(self, *args, **options):
        count = options['count']

        self.stdout.write(self.style.WARNING(f'Generating {count} test error logs...'))

        severities = ['debug', 'info', 'warning', 'error', 'critical']
        statuses = ['new', 'investigating', 'resolved', 'ignored']
        methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
        endpoints = [
            '/api/exercises/',
            '/api/lessons/',
            '/api/exams/',
            '/api/users/profile/',
            '/api/auth/login/',
            '/api/notebooks/',
            '/api/learning-paths/',
        ]
        exception_types = [
            'ValueError',
            'TypeError',
            'KeyError',
            'AttributeError',
            'ZeroDivisionError',
            'IndexError',
            'PermissionError',
        ]
        messages = [
            'Failed to process request',
            'Invalid data format',
            'Missing required field',
            'Database connection error',
            'Authentication failed',
            'Resource not found',
            'Permission denied',
            'Timeout exceeded',
        ]

        # Generate ErrorLogs
        for i in range(count):
            days_ago = random.randint(0, 7)
            timestamp = timezone.now() - timedelta(days=days_ago)

            ErrorLog.objects.create(
                severity=random.choice(severities),
                status=random.choice(statuses),
                message=random.choice(messages),
                exception_type=random.choice(exception_types),
                traceback=f"Traceback (most recent call last):\n  File test.py, line {random.randint(1,100)}\n    Test error",
                endpoint=random.choice(endpoints),
                method=random.choice(methods),
                ip_address=f"192.168.1.{random.randint(1,255)}",
                user_agent="Mozilla/5.0 (Test Browser)",
                request_data={'test': 'data', 'param': random.randint(1, 100)},
                count=random.randint(1, 20),
                first_seen=timestamp,
                last_seen=timestamp,
            )

        self.stdout.write(self.style.SUCCESS(f'✓ Created {count} test error logs'))

        # Generate APILogs
        api_count = count * 2
        self.stdout.write(self.style.WARNING(f'Generating {api_count} test API logs...'))

        status_codes = [200, 201, 400, 401, 403, 404, 422, 500, 503]

        for i in range(api_count):
            days_ago = random.randint(0, 7)
            timestamp = timezone.now() - timedelta(days=days_ago)

            APILog.objects.create(
                method=random.choice(methods),
                endpoint=random.choice(endpoints),
                ip_address=f"192.168.1.{random.randint(1,255)}",
                status_code=random.choice(status_codes),
                response_time_ms=random.randint(10, 5000),
                request_body='{"test": "data"}' if random.random() > 0.5 else None,
                query_params={'page': random.randint(1, 10)} if random.random() > 0.5 else None,
                timestamp=timestamp,
            )

        self.stdout.write(self.style.SUCCESS(f'✓ Created {api_count} test API logs'))

        # Generate SystemEvents
        event_count = 5
        self.stdout.write(self.style.WARNING(f'Generating {event_count} test system events...'))

        event_types = ['startup', 'shutdown', 'migration', 'deployment', 'config_change']
        event_titles = [
            'System started successfully',
            'Server shutdown initiated',
            'Database migration completed',
            'New deployment v1.2.3',
            'Configuration updated',
        ]

        for i in range(event_count):
            days_ago = random.randint(0, 7)
            timestamp = timezone.now() - timedelta(days=days_ago)

            SystemEvent.objects.create(
                event_type=event_types[i],
                title=event_titles[i],
                description=f'Test event description for {event_titles[i]}',
                metadata={'version': '1.0.0', 'test': True},
                timestamp=timestamp,
            )

        self.stdout.write(self.style.SUCCESS(f'✓ Created {event_count} test system events'))

        # Print summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(self.style.SUCCESS('TEST DATA GENERATION COMPLETE'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(f'Total ErrorLogs: {ErrorLog.objects.count()}')
        self.stdout.write(f'Total APILogs: {APILog.objects.count()}')
        self.stdout.write(f'Total SystemEvents: {SystemEvent.objects.count()}')
        self.stdout.write('')
        self.stdout.write('View in Django Admin:')
        self.stdout.write('  http://localhost:8000/admin/logging/')
        self.stdout.write('')
        self.stdout.write('View in Logs Console:')
        self.stdout.write('  http://localhost:5173/admin/logs')
        self.stdout.write('')
