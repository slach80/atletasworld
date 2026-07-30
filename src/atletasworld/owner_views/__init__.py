"""Owner portal views package. Re-exports all view functions."""
from ._auth import is_owner
from .dashboard import owner_dashboard, owner_upcoming_sessions
from .notifications import (
    owner_notifications, owner_send_notification,
    _resolve_recipient_emails, _build_html_email,
)
from .packages import (
    owner_packages, owner_package_add, owner_package_edit,
    owner_package_delete, owner_package_restore, owner_package_hard_delete,
    owner_package_duplicate, owner_package_assign, owner_package_adjust,
)
from .session_types import (
    owner_session_type_hard_delete, owner_session_type_duplicate,
    owner_session_types, owner_session_type_edit,
    owner_session_type_apply_capacities, owner_session_type_roster,
)
from .coaches import (
    owner_coaches, owner_coach_add, owner_coach_edit,
    owner_coach_delete, owner_coach_schedule,
)
from .bookings import owner_bookings, owner_booking_detail
from .clients import (
    owner_clients, owner_client_detail, owner_client_settle_bookings,
    owner_client_approve, owner_client_toggle_select_invite, owner_client_reject,
)
from .players import owner_players, owner_player_detail
from .teams import (
    owner_teams, owner_team_detail, owner_team_players, owner_team_bookings,
)
from .field_rentals import (
    owner_field_slots, owner_field_slot_edit, owner_field_slot_approve,
    owner_field_slot_reject, owner_field_slot_cancel, owner_field_slot_conflict_check,
)
from .services import owner_services, owner_service_edit
from .finances import owner_finances, owner_payments, owner_issue_refund
from .credits import owner_credits
from .discount_codes import owner_discount_codes, owner_discount_code_detail
from .waivers import owner_waivers
from .contacts import owner_contacts, owner_contact_edit
from .referrals import (
    owner_referrals, owner_referral_payouts, owner_payout_approve,
    owner_payout_reject, owner_payout_mark_paid,
)
from .guide import owner_guide
from .blog import (
    owner_blog_list, owner_blog_edit, owner_blog_delete, owner_blog_toggle_publish,
)
from .ai_assist import (
    owner_blog_ai_assist, owner_naming_ai_assist, owner_notification_ai_assist,
)
from .select_games import owner_select_games, owner_select_game_detail
