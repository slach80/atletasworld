"""
Pull VALD's ForceDecks result definitions and upsert into ValdResultDefinition.

Technical metadata (unit/trend/raw_payload) refreshes on every run. name,
description, show_in_client_portal, and display_order are owner-curated —
set once on creation (or forced via FRIENDLY_NAMES/CLIENT_PORTAL_DEFAULTS
below for confirmed KPIs) and never clobbered by VALD's raw terminology on
re-sync.
"""
from django.core.management.base import BaseCommand

from performance.models import ValdResultDefinition
from performance.vald_client import list_result_definitions, ValdAPIError

# Only CMJ has real, verified test data as of Phase 0 (2026-08-03). SLJ and
# the box-drop test are still pending real recordings from Mirko, so nothing
# else gets surfaced to parents yet even though this pulls all 500+ defs.
CLIENT_PORTAL_DEFAULTS = {
    'JUMP_HEIGHT_INCHES': 1,
}

# Parent-facing labels for confirmed KPIs — VALD's raw resultName
# ("Jump Height (Flight Time) in Inches") is too technical for the portal.
FRIENDLY_NAMES = {
    'JUMP_HEIGHT_INCHES': 'Countermovement Jump',
}

TREND_MAP = {
    'Positive': 'increasing',
    'Negative': 'decreasing',
}


class Command(BaseCommand):
    help = "Sync ValdResultDefinition from VALD's /resultdefinitions (ForceDecks)."

    def handle(self, *args, **options):
        try:
            definitions = list_result_definitions(system='forcedecks')
        except ValdAPIError as e:
            self.stderr.write(self.style.ERROR(f"Failed to fetch result definitions: {e}"))
            return

        created, updated = 0, 0
        for d in definitions:
            result_id = d.get('resultIdString')
            if not result_id:
                continue

            obj, was_created = ValdResultDefinition.objects.get_or_create(
                result_id=result_id,
                defaults={
                    'system': 'forcedecks',
                    'name': d.get('resultName', result_id),
                    'unit': d.get('resultUnitName', ''),
                    'trend_direction': TREND_MAP.get(d.get('trendDirection'), ''),
                    'description': d.get('resultDescription', ''),
                    'raw_payload': d,
                },
            )
            if was_created:
                created += 1
                if result_id in CLIENT_PORTAL_DEFAULTS:
                    obj.show_in_client_portal = True
                    obj.display_order = CLIENT_PORTAL_DEFAULTS[result_id]
                    obj.save(update_fields=['show_in_client_portal', 'display_order'])
            else:
                obj.unit = d.get('resultUnitName', '')
                obj.trend_direction = TREND_MAP.get(d.get('trendDirection'), '')
                obj.raw_payload = d
                obj.save(update_fields=['unit', 'trend_direction', 'raw_payload'])
                updated += 1

        # Ensure confirmed KPIs stay visible + friendly-named even after
        # manual curation drift (an owner unchecking one would be a mistake,
        # not an intentional hide, since it's the only metric with real data).
        for result_id, order in CLIENT_PORTAL_DEFAULTS.items():
            ValdResultDefinition.objects.filter(result_id=result_id).update(
                show_in_client_portal=True, display_order=order
            )
        for result_id, name in FRIENDLY_NAMES.items():
            ValdResultDefinition.objects.filter(result_id=result_id).update(name=name)

        self.stdout.write(self.style.SUCCESS(
            f"Synced {len(definitions)} definitions ({created} created, {updated} updated)."
        ))
        visible = ValdResultDefinition.objects.filter(show_in_client_portal=True)
        self.stdout.write(f"Visible in client portal ({visible.count()}): "
                           f"{', '.join(visible.values_list('result_id', flat=True))}")
