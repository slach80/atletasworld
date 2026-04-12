"""
Unit tests for the bookings app.

Covers:
  - SessionType: field defaults, drop-in price fallback, event carousel fields
  - AvailabilitySlot: capacity logic, availability flag, pricing, datetime properties
  - Booking: full lifecycle (confirm, complete, cancel, no-show), 24-hour cancellation rule
"""
import pytest
from decimal import Decimal
from datetime import date, time, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from bookings.models import SessionType, AvailabilitySlot, Booking


# ── SessionType ───────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSessionType:
    """Tests for SessionType model defaults, pricing helpers, and event fields."""

    def test_str_representation(self, db):
        """__str__ should include name, duration, and price."""
        st = SessionType.objects.create(
            name='Private Training',
            session_format='private',
            duration_minutes=60,
            price=Decimal('75.00'),
        )
        assert 'Private Training' in str(st)
        assert '60' in str(st)

    def test_drop_in_price_falls_back_to_price(self, db):
        """get_drop_in_price() should return the standard price when drop_in_price is not set."""
        st = SessionType.objects.create(
            name='Group Class',
            session_format='group',
            duration_minutes=60,
            price=Decimal('40.00'),
            drop_in_price=None,
        )
        assert st.get_drop_in_price() == Decimal('40.00')

    def test_drop_in_price_uses_explicit_value(self, db):
        """get_drop_in_price() should return the explicit drop_in_price when set."""
        st = SessionType.objects.create(
            name='Group Class',
            session_format='group',
            duration_minutes=60,
            price=Decimal('40.00'),
            drop_in_price=Decimal('50.00'),
        )
        assert st.get_drop_in_price() == Decimal('50.00')

    def test_show_as_event_default_false(self, db):
        """New session types should not appear in the events carousel by default."""
        st = SessionType.objects.create(
            name='Test Session',
            session_format='private',
            duration_minutes=60,
            price=Decimal('50.00'),
        )
        assert st.show_as_event is False

    def test_event_display_order_default_zero(self, db):
        """event_display_order should default to 0 so new cards appear first unless ordered."""
        st = SessionType.objects.create(
            name='Test Session',
            session_format='private',
            duration_minutes=60,
            price=Decimal('50.00'),
        )
        assert st.event_display_order == 0

    def test_event_cta_fields_blank_by_default(self, db):
        """event_cta_text and event_cta_url should be blank strings by default."""
        st = SessionType.objects.create(
            name='Test Session',
            session_format='private',
            duration_minutes=60,
            price=Decimal('50.00'),
        )
        assert st.event_cta_text == ''
        assert st.event_cta_url == ''


# ── AvailabilitySlot ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestAvailabilitySlot:
    """Tests for AvailabilitySlot capacity, availability flag, pricing, and datetime helpers."""

    def test_str_representation(self, availability_slot):
        """__str__ should contain coach name and date."""
        result = str(availability_slot)
        assert availability_slot.coach.user.last_name in result or str(availability_slot.date) in result

    def test_spots_remaining_decrements_with_bookings(self, availability_slot):
        """spots_remaining should decrease as current_bookings increases."""
        availability_slot.current_bookings = 3
        assert availability_slot.spots_remaining == 2  # 5 max - 3

    def test_spots_remaining_never_negative(self, availability_slot):
        """spots_remaining should clamp at 0, never go negative."""
        availability_slot.current_bookings = 10  # exceeds max_bookings=5
        assert availability_slot.spots_remaining == 0

    def test_is_available_true_when_spots_remain(self, availability_slot):
        """Slot should be available when status is 'available' and spots remain."""
        availability_slot.status = 'available'
        availability_slot.current_bookings = 0
        assert availability_slot.is_available is True

    def test_is_available_false_when_full(self, availability_slot):
        """Slot should not be available when fully booked."""
        availability_slot.status = 'fully_booked'
        availability_slot.current_bookings = 5
        assert availability_slot.is_available is False

    def test_is_available_false_when_cancelled(self, availability_slot):
        """Cancelled slots should not be available regardless of booking count."""
        availability_slot.status = 'cancelled'
        availability_slot.current_bookings = 0
        assert availability_slot.is_available is False

    def test_effective_price_uses_session_type_price(self, availability_slot):
        """effective_price should return session_type.price when no override is set."""
        availability_slot.price_override = None
        # session_type_group price is $40.00
        assert availability_slot.effective_price == Decimal('40.00')

    def test_effective_price_uses_override(self, availability_slot):
        """effective_price should return price_override when one is set."""
        availability_slot.price_override = Decimal('25.00')
        assert availability_slot.effective_price == Decimal('25.00')

    def test_datetime_start_property(self, availability_slot):
        """datetime_start should combine date and start_time into a single datetime."""
        from datetime import datetime
        expected = datetime.combine(availability_slot.date, availability_slot.start_time)
        assert availability_slot.datetime_start == expected

    def test_datetime_end_property(self, availability_slot):
        """datetime_end should combine date and end_time into a single datetime."""
        from datetime import datetime
        expected = datetime.combine(availability_slot.date, availability_slot.end_time)
        assert availability_slot.datetime_end == expected


# ── Booking lifecycle ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestBookingLifecycle:
    """
    Tests for Booking status transitions and the 24-hour cancellation rule.

    Status flow:
        pending → confirmed → completed
                           → no_show
        pending/confirmed → cancelled  (only if > 24 h before session)
    """

    def test_pending_booking_created_correctly(self, pending_booking):
        """A freshly created booking should have 'pending' status."""
        assert pending_booking.status == 'pending'

    def test_confirm_moves_to_confirmed_status(self, pending_booking):
        """Calling confirm() on a pending booking should set status to 'confirmed'."""
        pending_booking.confirm()
        assert pending_booking.status == 'confirmed'

    def test_confirm_sets_confirmed_at_timestamp(self, pending_booking):
        """confirm() should record the confirmation timestamp."""
        assert pending_booking.confirmed_at is None
        pending_booking.confirm()
        assert pending_booking.confirmed_at is not None

    def test_confirm_raises_if_not_pending(self, pending_booking):
        """Confirming an already-confirmed booking should raise ValidationError."""
        pending_booking.confirm()
        with pytest.raises(ValidationError):
            pending_booking.confirm()

    def test_complete_moves_to_completed_status(self, pending_booking):
        """complete() on a confirmed booking should set status to 'completed'."""
        pending_booking.confirm()
        pending_booking.complete()
        assert pending_booking.status == 'completed'

    def test_complete_raises_if_not_confirmed(self, pending_booking):
        """Completing a pending (not yet confirmed) booking should raise ValidationError."""
        with pytest.raises(ValidationError):
            pending_booking.complete()

    def test_cancel_moves_to_cancelled_status(self, pending_booking):
        """cancel() should set status to 'cancelled' when booking is > 24 h out."""
        pending_booking.cancel(reason='client_request')
        assert pending_booking.status == 'cancelled'

    def test_cancel_records_cancellation_reason(self, pending_booking):
        """cancel() should store the provided reason on the booking."""
        pending_booking.cancel(reason='illness', notes='Player is sick')
        assert pending_booking.cancellation_reason == 'illness'
        assert pending_booking.cancellation_notes == 'Player is sick'

    def test_cancel_sets_cancelled_at_timestamp(self, pending_booking):
        """cancel() should record the cancellation timestamp."""
        pending_booking.cancel(reason='client_request')
        assert pending_booking.cancelled_at is not None

    def test_mark_no_show_sets_status(self, pending_booking):
        """mark_no_show() on a confirmed booking should set status to 'no_show'."""
        pending_booking.confirm()
        pending_booking.mark_no_show()
        assert pending_booking.status == 'no_show'

    def test_mark_no_show_raises_if_not_confirmed(self, pending_booking):
        """mark_no_show() on a pending booking should raise ValidationError."""
        with pytest.raises(ValidationError):
            pending_booking.mark_no_show()

    def test_can_cancel_true_more_than_24h_ahead(self, pending_booking):
        """can_cancel should be True when booking is scheduled more than 24 hours out."""
        # pending_booking is 3 days out
        assert pending_booking.can_cancel is True

    def test_can_cancel_false_within_24h(self, near_term_booking):
        """can_cancel should be False when the session is less than 24 hours away."""
        assert near_term_booking.can_cancel is False

    def test_can_cancel_false_when_already_cancelled(self, pending_booking):
        """can_cancel should be False after the booking has been cancelled."""
        pending_booking.cancel(reason='client_request')
        assert pending_booking.can_cancel is False

    def test_can_reschedule_true_when_pending(self, pending_booking):
        """can_reschedule should be True for a pending booking that is > 24 h out."""
        assert pending_booking.can_reschedule is True

    def test_can_reschedule_false_when_completed(self, pending_booking):
        """can_reschedule should be False once the booking is completed."""
        pending_booking.confirm()
        pending_booking.complete()
        assert pending_booking.can_reschedule is False
