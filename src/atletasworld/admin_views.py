"""
Backwards-compatibility shim.
All owner portal views now live in atletasworld/owner_views/.
This module re-exports every public name so existing imports in urls.py and
clients/tasks.py continue to work without changes.
"""
from .owner_views import (
    is_owner,
    owner_dashboard, owner_upcoming_sessions,
    owner_notifications, owner_send_notification,
    _resolve_recipient_emails, _build_html_email,
    owner_packages, owner_package_add, owner_package_edit,
    owner_package_delete, owner_package_restore, owner_package_hard_delete,
    owner_package_duplicate, owner_package_assign, owner_package_adjust,
    owner_session_type_hard_delete, owner_session_type_duplicate,
    owner_session_types, owner_session_type_edit,
    owner_session_type_apply_capacities, owner_session_type_roster,
    owner_coaches, owner_coach_add, owner_coach_edit,
    owner_coach_delete, owner_coach_schedule,
    owner_bookings, owner_booking_detail,
    owner_clients, owner_client_detail, owner_client_settle_bookings,
    owner_client_approve, owner_client_toggle_select_invite, owner_client_reject,
    owner_players, owner_player_detail, owner_add_manual_test_result,
    owner_teams, owner_team_detail, owner_team_players, owner_team_bookings,
    owner_field_slots, owner_field_slot_edit, owner_field_slot_approve,
    owner_field_slot_reject, owner_field_slot_cancel, owner_field_slot_conflict_check,
    owner_services, owner_service_edit,
    owner_finances, owner_payments, owner_issue_refund,
    owner_credits,
    owner_discount_codes, owner_discount_code_detail,
    owner_waivers,
    owner_contacts, owner_contact_edit,
    owner_referrals, owner_referral_payouts, owner_payout_approve,
    owner_payout_reject, owner_payout_mark_paid,
    owner_guide,
    owner_blog_list, owner_blog_edit, owner_blog_delete, owner_blog_toggle_publish,
    owner_blog_ai_assist, owner_naming_ai_assist, owner_notification_ai_assist,
    owner_select_games, owner_select_game_detail,
)
