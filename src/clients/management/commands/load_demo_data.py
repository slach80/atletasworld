"""
Management command to load demo data for the Atletas Performance Center application.
Usage: python manage.py load_demo_data
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model
import os


class Command(BaseCommand):
    help = 'Load demo data for Atletas Performance Center application'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force reload even if data exists',
        )

    def handle(self, *args, **options):
        User = get_user_model()

        # Check if demo data already exists
        if not options['force'] and User.objects.filter(username='mirko').exists():
            self.stdout.write(self.style.WARNING('Demo data already loaded. Use --force to reload.'))
            return

        fixture_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            'fixtures',
            'demo_data.json'
        )

        if not os.path.exists(fixture_path):
            self.stdout.write(self.style.ERROR(f'Fixture file not found: {fixture_path}'))
            return

        self.stdout.write('Loading demo data...')

        try:
            call_command('loaddata', fixture_path, verbosity=0)
            self.stdout.write(self.style.SUCCESS('Demo data loaded successfully!'))

            # Print summary
            from clients.models import Client, Player
            from coaches.models import Coach

            self.stdout.write(f'  - Users: {User.objects.count()}')
            self.stdout.write(f'  - Coaches: {Coach.objects.count()}')
            self.stdout.write(f'  - Clients: {Client.objects.count()}')
            self.stdout.write(f'  - Players: {Player.objects.count()}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error loading demo data: {e}'))
