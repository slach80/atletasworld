"""
Management command to load Select-program demo data for UI/feature validation.

Creates:
  - 3 Select teams (2014, 2015, 2016)
  - 8 players per team with varied Select membership statuses
  - Active subscriptions, paid one-time, expiring, expired, unassigned
  - Contacts (unregistered) for dashboard sub-line
  - Unsigned waivers
  - Package breakdown across Select + Summer/Camp types

Usage: python manage.py load_select_demo_data [--reset]
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


class Command(BaseCommand):
    help = 'Load Select-program demo data for UI validation'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete existing Select demo data first')

    def handle(self, *args, **options):
        from clients.models import (
            Client, Player, Package, ClientPackage, Team,
            ClientWaiver, UnsubscribeToken,
        )
        from bookings.models import SessionType
        from coaches.models import Coach

        today = timezone.localdate()

        if options['reset']:
            Team.objects.filter(name__startswith='Demo Select').delete()
            User.objects.filter(email__endswith='@selectdemo.test').delete()
            self.stdout.write('Existing Select demo data cleared.')

        # ── Packages ─────────────────────────────────────────────────────────
        select_pkg, _ = Package.objects.get_or_create(
            name='APC Select Membership',
            defaults=dict(
                package_type='select', price=100, sessions_included=0,
                validity_weeks=4, is_active=True, is_purchasable=True,
                stripe_price_id='price_demo_select',
            )
        )
        summer_pkg, _ = Package.objects.get_or_create(
            name='Elite 24 Summer',
            defaults=dict(
                package_type='special', price=900, sessions_included=24,
                validity_weeks=12, is_active=True, is_purchasable=True, is_special=True,
            )
        )
        basic_pkg, _ = Package.objects.get_or_create(
            name='Basic 4 Summer',
            defaults=dict(
                package_type='special', price=200, sessions_included=4,
                validity_weeks=4, is_active=True, is_purchasable=True, is_special=True,
            )
        )

        # ── Coach ─────────────────────────────────────────────────────────────
        coach_user, _ = User.objects.get_or_create(
            email='coach@selectdemo.test',
            defaults=dict(username='demo_coach_select', first_name='Pablo', last_name='Demo',
                          is_active=True)
        )
        coach_user.set_password('demo123')
        coach_user.save()
        coach, _ = Coach.objects.get_or_create(user=coach_user, defaults=dict(is_active=True))

        # ── Teams ─────────────────────────────────────────────────────────────
        teams = {}
        for year in [2014, 2015, 2016]:
            team, _ = Team.objects.get_or_create(
                name=f'Demo Select {year}',
                defaults=dict(is_select=True, is_active=True, age_group=f'U{2026-year}',
                              max_players=18)
            )
            teams[year] = team

        # ── Owner ─────────────────────────────────────────────────────────────
        owner_user, _ = User.objects.get_or_create(
            email='owner@selectdemo.test',
            defaults=dict(username='demo_owner_select', first_name='Demo', last_name='Owner',
                          is_staff=True, is_superuser=True)
        )
        owner_user.set_password('demo123')
        owner_user.save()

        # ── Clients + Players + Packages ──────────────────────────────────────
        scenarios = [
            # (first, last, birth_year, team_year, select_status, expiry_offset_days, has_sub_id)
            ('Alice',   'Active',    2015, 2015, 'active',   27,  True),   # active subscription
            ('Bob',     'Billing',   2015, 2015, 'active',   10,  True),   # expiring soon (≤14d)
            ('Carol',   'Cancelled', 2015, 2015, 'expired',  -5,  False),  # truly expired
            ('Dan',     'Paid',      2015, 2015, 'expired',  120, False),  # paid, no renewal
            ('Eve',     'Unassigned',2015, 2015, 'active',   27,  True),   # active, no player assigned
            ('Frank',   'Sibling',   2015, 2015, 'active',   27,  True),   # sibling — second sub
            ('Grace',   'Paid2',     2016, 2016, 'expired',  90,  False),  # paid, team 2016
            ('Harry',   'Active2',   2016, 2016, 'active',   27,  True),   # active, team 2016
            ('Iris',    'Paid3',     2014, 2014, 'expired',  150, False),  # paid, team 2014
            ('Jack',    'Active3',   2014, 2014, 'active',   27,  True),   # active, team 2014
        ]

        created = 0
        for i, (first, last, birth_year, team_year, sel_status, exp_offset, has_sub) in enumerate(scenarios):
            email = f'{first.lower()}.{last.lower()}@selectdemo.test'
            u, _ = User.objects.get_or_create(
                email=email,
                defaults=dict(username=f'demo_{first.lower()}_{i}', first_name=first, last_name=last)
            )
            u.set_password('demo123')
            u.save()

            from django.contrib.auth.models import Group
            client_group, _ = Group.objects.get_or_create(name='Client')
            u.groups.add(client_group)

            client, _ = Client.objects.get_or_create(user=u, defaults=dict(select_invited=True))
            client.select_invited = True
            client.save()

            team = teams[team_year]
            player, _ = Player.objects.get_or_create(
                client=client,
                first_name=first,
                defaults=dict(last_name=last, birth_year=birth_year,
                              team=team if last != 'Unassigned' else None, is_active=True)
            )
            if last != 'Unassigned':
                player.team = team
                player.save()

            # Select package
            expiry = today + timedelta(days=exp_offset)
            sub_id = f'sub_demo_{first.lower()}_{i:03d}' if has_sub else ''
            pay_id = sub_id if sub_id else f'pi_demo_{first.lower()}_{i:03d}'
            cp, _ = ClientPackage.objects.get_or_create(
                client=client, package=select_pkg,
                stripe_payment_id=pay_id,
                defaults=dict(
                    status=sel_status,
                    start_date=today - timedelta(weeks=4),
                    expiry_date=expiry,
                    sessions_remaining=0,
                    stripe_subscription_id=sub_id,
                    player=player if last != 'Unassigned' else None,
                )
            )

            # Add a Summer package for a few clients
            if i < 5:
                pkg = summer_pkg if i < 3 else basic_pkg
                sessions = pkg.sessions_included
                used = min(i * 3, sessions)
                exp_summer = today + timedelta(days=13) if i < 4 else today + timedelta(days=30)
                ClientPackage.objects.get_or_create(
                    client=client, package=pkg,
                    defaults=dict(
                        status='active' if exp_summer >= today else 'exhausted',
                        start_date=today - timedelta(weeks=8),
                        expiry_date=exp_summer,
                        sessions_remaining=sessions - used,
                        stripe_payment_id=f'pi_summer_{first.lower()}_{i}',
                        player=player,
                    )
                )

            created += 1

        # ── Unsigned waivers (add some clients without waivers) ───────────────
        from clients.models import get_current_waiver
        waiver_version = ClientWaiver.WAIVER_VERSION
        waiver_unsigned = 0
        for client in Client.objects.filter(user__email__endswith='@selectdemo.test')[:4]:
            if not ClientWaiver.objects.filter(client=client, waiver_version=waiver_version).exists():
                waiver_unsigned += 1  # no waiver = unsigned

        # ── Contacts (unregistered — ContactParent with no client linked) ───────
        from clients.models import ContactParent
        contacts_created = 0
        for j in range(15):
            c, created_c = ContactParent.objects.get_or_create(
                email=f'contact{j}@selectdemo.test',
                defaults=dict(first_name=f'Contact{j}', last_name='Demo',
                              phone='555-0000', source='manual')
            )
            if created_c:
                contacts_created += 1

        # ── Summary ──────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\nSelect demo data loaded!'))
        self.stdout.write(f'  Teams:    {len(teams)} (Demo Select 2014/2015/2016)')
        self.stdout.write(f'  Clients:  {created} with varied Select statuses')
        self.stdout.write(f'  Contacts: {contacts_created} unregistered created')
        self.stdout.write(f'\nScenarios covered:')
        self.stdout.write('  ✓ Active subscription (green)')
        self.stdout.write('  ✓ Expiring soon ≤14d (yellow)')
        self.stdout.write('  ✓ Truly expired (red)')
        self.stdout.write('  ✓ Paid no-renewal (blue)')
        self.stdout.write('  ✓ Unassigned package — triggers alert')
        self.stdout.write('  ✓ Sibling subscription')
        self.stdout.write('  ✓ Summer/Camp packages expiring')
        self.stdout.write(f'\nLogin: owner@selectdemo.test / demo123')
        self.stdout.write(f'       coach@selectdemo.test / demo123')
        self.stdout.write(f'       alice.active@selectdemo.test / demo123 (client)')
