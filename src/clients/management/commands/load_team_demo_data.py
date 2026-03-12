"""
Management command to load team demo data for Atletas World.
Creates team-coach clients, teams, and assigns existing players and coaches.
Usage: python manage.py load_team_demo_data
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.text import slugify

User = get_user_model()


class Command(BaseCommand):
    help = 'Load team demo data (team coaches, teams, player assignments)'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-create even if teams already exist')

    def handle(self, *args, **options):
        from clients.models import Client, Player, Team
        from coaches.models import Coach

        if not options['force'] and Team.objects.exists():
            self.stdout.write(self.style.WARNING('Teams already exist. Use --force to reload.'))
            return

        # Clean up if force
        if options['force']:
            Team.objects.all().delete()
            self.stdout.write('Cleared existing teams.')

        client_group, _ = Group.objects.get_or_create(name='Client')

        # ── 1. Create team-coach users (managers) ──────────────────────────
        managers = self._create_managers(client_group)

        # ── 2. Get coaches to assign ───────────────────────────────────────
        coaches = list(Coach.objects.filter(is_active=True)[:3])
        if not coaches:
            self.stdout.write(self.style.WARNING('No coaches found — teams will have no assigned coaches.'))

        # ── 3. Create teams ────────────────────────────────────────────────
        teams_data = [
            {
                'name': 'FC Atletas U10 Boys',
                'age_group': 'U10',
                'skill_level': 'beginner',
                'club_name': 'FC Atletas',
                'description': 'Recreational U10 boys team focused on fundamentals and fun.',
                'max_players': 14,
                'manager_key': 'coach_carlos',
            },
            {
                'name': 'Atletas Elite U12 Girls',
                'age_group': 'U12',
                'skill_level': 'intermediate',
                'club_name': 'Atletas World',
                'description': 'Competitive U12 girls squad training twice weekly with an emphasis on technical development.',
                'max_players': 16,
                'manager_key': 'coach_diana',
            },
            {
                'name': 'Atletas Advanced U14',
                'age_group': 'U14',
                'skill_level': 'advanced',
                'club_name': 'Atletas World',
                'description': 'Advanced U14 mixed team preparing for regional tournaments.',
                'max_players': 18,
                'manager_key': 'coach_carlos',
            },
        ]

        created_teams = {}
        for td in teams_data:
            slug = slugify(td['name'])
            # Ensure unique slug
            if Team.objects.filter(slug=slug).exists():
                slug = f"{slug}-2"
            manager = managers[td['manager_key']]
            team = Team.objects.create(
                name=td['name'],
                slug=slug,
                age_group=td['age_group'],
                skill_level=td['skill_level'],
                club_name=td['club_name'],
                description=td['description'],
                max_players=td['max_players'],
                manager=manager,
                is_active=True,
            )
            # Assign coaches (round-robin)
            if coaches:
                team.coaches.set(coaches[:2])  # up to 2 coaches per team
            created_teams[td['age_group']] = team
            self.stdout.write(f'  Created team: {team.name}')

        # ── 4. Assign existing players to teams by birth_year ─────────────
        birth_year_map = [
            (range(2015, 2017), created_teams.get('U10')),   # U10: born 2015-2016
            (range(2013, 2015), created_teams.get('U12')),   # U12: born 2013-2014
            (range(2011, 2013), created_teams.get('U14')),   # U14: born 2011-2012
        ]
        assigned = 0
        for player in Player.objects.filter(is_active=True, team__isnull=True, birth_year__isnull=False):
            for yr_range, team in birth_year_map:
                if team and player.birth_year in yr_range:
                    player.team = team
                    player.save(update_fields=['team'])
                    assigned += 1
                    break

        # ── 5. Add extra demo players for fuller rosters ───────────────────
        extra_players = self._create_extra_players(created_teams, managers)

        # ── Summary ────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\nTeam demo data loaded!'))
        self.stdout.write(f'  Teams created:   {Team.objects.count()}')
        self.stdout.write(f'  Players assigned from existing: {assigned}')
        self.stdout.write(f'  Extra players added: {extra_players}')
        for team in Team.objects.all():
            self.stdout.write(f'    {team.name}: {team.players.count()} players, {team.coaches.count()} coaches')

    def _create_managers(self, client_group):
        from clients.models import Client
        managers = {}

        manager_specs = [
            {
                'key': 'coach_carlos',
                'username': 'coach_carlos',
                'first_name': 'Carlos',
                'last_name': 'Rivera',
                'email': 'carlos.rivera@atletasworld.com',
            },
            {
                'key': 'coach_diana',
                'username': 'coach_diana',
                'first_name': 'Diana',
                'last_name': 'Morales',
                'email': 'diana.morales@atletasworld.com',
            },
        ]

        for spec in manager_specs:
            user, created = User.objects.get_or_create(
                username=spec['username'],
                defaults={
                    'first_name': spec['first_name'],
                    'last_name': spec['last_name'],
                    'email': spec['email'],
                }
            )
            if created:
                user.set_password('demo1234')
                user.save()
                user.groups.add(client_group)

            client, _ = Client.objects.get_or_create(
                user=user,
                defaults={'client_type': 'coach', 'phone': '555-010-0001'}
            )
            # Ensure type is coach even if client existed
            if client.client_type != 'coach':
                client.client_type = 'coach'
                client.save(update_fields=['client_type'])

            managers[spec['key']] = client
            action = 'Created' if created else 'Found'
            self.stdout.write(f'  {action} manager: {user.get_full_name()} ({user.username})')

        return managers

    def _create_extra_players(self, created_teams, managers):
        from clients.models import Player

        # (first, last, team_name, birth_year, skill_level, manager_key, team_age_key)
        extra = [
            # U10  (born ~2016)
            ('Mateo', 'Rivera',  'U10 Boys',  2016, 'beginner',     'coach_carlos', 'U10'),
            ('Liam',  'Garcia',  'U10 Boys',  2015, 'beginner',     'coach_carlos', 'U10'),
            ('Owen',  'Torres',  'U10 Boys',  2016, 'beginner',     'coach_carlos', 'U10'),
            # U12  (born ~2014)
            ('Mia',   'Chen',    'U12 Girls', 2014, 'intermediate', 'coach_diana',  'U12'),
            ('Ava',   'Patel',   'U12 Girls', 2013, 'beginner',     'coach_diana',  'U12'),
            ('Zoe',   'Kim',     'U12 Girls', 2014, 'intermediate', 'coach_diana',  'U12'),
            # U14  (born ~2012)
            ('James', 'Nguyen',  'U14 Mixed', 2012, 'advanced',     'coach_carlos', 'U14'),
            ('Aria',  'Santos',  'U14 Mixed', 2011, 'intermediate', 'coach_carlos', 'U14'),
            ('Kai',   'Lopez',   'U14 Mixed', 2012, 'advanced',     'coach_carlos', 'U14'),
        ]

        count = 0
        for first, last, team_name, birth_year, skill, manager_key, team_key in extra:
            team = created_teams.get(team_key)
            manager = managers[manager_key]
            player, created = Player.objects.get_or_create(
                first_name=first,
                last_name=last,
                client=manager,
                defaults={
                    'team_name': team_name,
                    'birth_year': birth_year,
                    'skill_level': skill,
                    'team': team,
                    'is_active': True,
                }
            )
            if not created and team:
                player.team = team
                player.save(update_fields=['team'])
            if created:
                count += 1
        return count
