"""Client portal views package."""
from .dashboard import dashboard, profile, sign_waiver
from .players import players_list, player_add, player_edit, player_delete
from .packages import (package_payment_intent, batch_package_payment_intent,
                       select_setup_intent, package_subscribe, select_update_payment_method,
                       select_cancel_subscription, package_assign, packages_list)
from .bookings import (bookings_list, booking_cancel, booking_reschedule, booking_page,
                       booking_page_v2, reserve_session, cancel_reservation,
                       confirm_booking, create_booking_direct)
from .notifications import (notification_settings, notification_history,
                             register_push_subscription, unregister_push_subscription,
                             get_unread_count)
from .assessments import assessments_view, player_assessments, player_assessment_chart_data
from .teams import (team_list, team_create, team_detail, team_edit,
                    team_player_add, team_player_remove, team_booking_page,
                    team_reserve_session, team_confirm_booking, team_bookings_list)
from .field_rental import (field_rental_list, field_rental_request,
                            field_rental_cancel, field_rental_available_json)
from .misc import (discount_validate, unsubscribe_landing, unsubscribe_oneclick,
                   referral_page, add_referral_code, select_game_rsvp)
