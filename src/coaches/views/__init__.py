"""Coaches views package."""
from ._auth import coach_required
from .dashboard import dashboard
from .schedule import (
    schedule,
    add_schedule_block,
    add_bulk_schedule,
    delete_schedule_block,
    bulk_delete_blocks,
    bulk_edit_blocks,
)
from .attendance import session_attendance, update_attendance, todays_sessions
from .assessments import assessments_list, create_assessment, quick_assess_session
from .players import my_players, player_detail
from .notifications import notify_parents, send_notification, notify_ai_assist
from .profile import profile_ai_assist, availability, edit_profile, coach_public_profile
from .referral import referral_page
from .blog import coach_blog_posts, coach_blog_submit
from .select_games import coach_select_games, coach_select_game_detail

__all__ = [
    'coach_required',
    'dashboard',
    'schedule',
    'add_schedule_block',
    'add_bulk_schedule',
    'delete_schedule_block',
    'bulk_delete_blocks',
    'bulk_edit_blocks',
    'session_attendance',
    'update_attendance',
    'todays_sessions',
    'assessments_list',
    'create_assessment',
    'quick_assess_session',
    'my_players',
    'player_detail',
    'notify_parents',
    'send_notification',
    'notify_ai_assist',
    'profile_ai_assist',
    'availability',
    'edit_profile',
    'coach_public_profile',
    'referral_page',
    'coach_blog_posts',
    'coach_blog_submit',
    'coach_select_games',
    'coach_select_game_detail',
]
