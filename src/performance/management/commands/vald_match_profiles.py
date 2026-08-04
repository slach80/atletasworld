"""
Match VALD athlete profiles to roster Players by name + birth year.

Auto-links confident (unique, exact) matches. Everything else — ambiguous
name collisions, birth-year mismatches, profiles with no roster hit — is
left unlinked and reported for manual review via the Owner Portal match UI.
"""
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from clients.models import Player
from performance.models import ValdProfile
from performance.vald_client import list_profiles, ValdAPIError


def _norm(name: str) -> str:
    return name.strip().lower()


class Command(BaseCommand):
    help = "Match VALD profiles to Players by exact (name, birth year); report the rest for manual review."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Report matches without writing ValdProfile records.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        tenant_id = settings.VALD_TENANT_ID

        try:
            profiles = list_profiles(tenant_id)
        except ValdAPIError as e:
            self.stderr.write(self.style.ERROR(f"Failed to fetch VALD profiles: {e}"))
            return

        self.stdout.write(f"Fetched {len(profiles)} VALD profiles for tenant {tenant_id}\n")

        already_linked_profile_ids = set(
            ValdProfile.objects.filter(is_active=True).values_list('vald_profile_id', flat=True)
        )

        players = Player.objects.filter(is_active=True).exclude(vald_profile__isnull=False)
        by_name_and_dob = {}
        by_name_only = {}
        for player in players:
            key = (_norm(player.first_name), _norm(player.last_name), player.birth_year)
            by_name_and_dob.setdefault(key, []).append(player)
            name_key = (_norm(player.first_name), _norm(player.last_name))
            by_name_only.setdefault(name_key, []).append(player)

        auto_matched, ambiguous, no_match, already_linked, duplicate_profiles = [], [], [], [], []
        # Players claimed within this run — the initial `players` queryset
        # snapshot goes stale mid-loop, so two VALD profiles for the same
        # person (a real Hub data-quality issue, not hypothetical — seen in
        # production) would otherwise both match the same Player and the
        # second create() would crash on the OneToOneField.
        claimed_player_ids = set()

        for profile in profiles:
            profile_id = profile['profileId']
            given = _norm(profile.get('givenName', ''))
            family = _norm(profile.get('familyName', ''))
            dob_year = None
            dob_raw = profile.get('dateOfBirth')
            if dob_raw:
                dob_year = datetime.fromisoformat(dob_raw.replace('Z', '+00:00')).year

            if profile_id in already_linked_profile_ids:
                already_linked.append(profile)
                continue

            all_candidates = by_name_and_dob.get((given, family, dob_year), [])
            candidates = [p for p in all_candidates if p.id not in claimed_player_ids]

            if not candidates and all_candidates:
                # Every name+DOB match was already claimed this run — a
                # second VALD profile for someone we just matched.
                duplicate_profiles.append((profile, all_candidates))
                continue

            if len(candidates) == 1:
                player = candidates[0]
                if not dry_run:
                    ValdProfile.objects.create(
                        player=player,
                        vald_profile_id=profile_id,
                        vald_tenant_id=tenant_id,
                        match_method='auto_name_dob',
                    )
                claimed_player_ids.add(player.id)
                auto_matched.append((profile, player))
                continue

            if len(candidates) > 1:
                ambiguous.append((profile, candidates, 'duplicate roster entries at same name+DOB'))
                continue

            name_candidates = by_name_only.get((given, family), [])
            if len(name_candidates) >= 1:
                ambiguous.append((profile, name_candidates, 'name matches but birth year differs'))
            else:
                no_match.append(profile)

        self.stdout.write(self.style.SUCCESS(f"\nAUTO-MATCHED ({len(auto_matched)}):"))
        for profile, player in auto_matched:
            self.stdout.write(
                f"  {profile.get('givenName', '').strip()} {profile.get('familyName', '').strip()} "
                f"-> Player #{player.id} {player.full_name}"
            )

        self.stdout.write(self.style.WARNING(f"\nAMBIGUOUS - needs manual review ({len(ambiguous)}):"))
        for profile, candidates, reason in ambiguous:
            self.stdout.write(
                f"  {profile.get('givenName', '').strip()} {profile.get('familyName', '').strip()} "
                f"(profile {profile_id_short(profile)}) — {reason}"
            )
            for c in candidates:
                self.stdout.write(f"    - Player #{c.id} {c.full_name} (birth_year={c.birth_year})")

        self.stdout.write(self.style.WARNING(f"\nDUPLICATE VALD PROFILES - same person, two Hub profiles ({len(duplicate_profiles)}):"))
        for profile, candidates in duplicate_profiles:
            self.stdout.write(
                f"  {profile.get('givenName', '').strip()} {profile.get('familyName', '').strip()} "
                f"(profile {profile_id_short(profile)}) already matched to "
                f"Player #{candidates[0].id} {candidates[0].full_name} via another VALD profile — "
                f"merge these profiles in VALD Hub, or match manually if they're different people."
            )

        self.stdout.write(self.style.NOTICE(f"\nNO ROSTER MATCH ({len(no_match)}):"))
        for profile in no_match:
            self.stdout.write(
                f"  {profile.get('givenName', '').strip()} {profile.get('familyName', '').strip()} "
                f"(profile {profile_id_short(profile)})"
            )

        if already_linked:
            self.stdout.write(f"\nAlready linked, skipped: {len(already_linked)}")

        if dry_run:
            self.stdout.write(self.style.NOTICE("\nDry run — no ValdProfile records were created."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nCreated {len(auto_matched)} ValdProfile links."))
        self.stdout.write(
            "Resolve ambiguous / no-match profiles in Owner Portal -> Performance -> Match, "
            "or fix roster name/birth_year and re-run."
        )


def profile_id_short(profile):
    pid = profile.get('profileId', '')
    return pid[:8] if pid else '?'
