"""
Notification queuing utilities for Atletas Performance Center.

Provides queue_grouped_notification() — the single entry point for triggering
transactional emails.  Related events that happen close together (e.g. a booking
confirmation and its Stripe payment webhook) are coalesced into one email via a
short time window stored in NotificationOutbox.

Usage:
    from clients.notification_utils import queue_grouped_notification

    queue_grouped_notification(
        client=booking.client,
        event_type='booking_confirmed',
        context={'booking_id': booking.id, 'payment_method': 'package', ...},
        group_key=f'booking_{booking.id}',
        window_seconds=45,
    )
"""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def queue_grouped_notification(client, event_type, context, group_key, window_seconds=45):
    """Add an event to a client's outbox group and schedule a flush task.

    On the first call for a given group_key, creates a NotificationOutbox record
    and schedules flush_notification_group to run after `window_seconds`.

    On subsequent calls (same group_key, task not yet fired), appends the new
    event to the existing record.  The already-scheduled task will pick up all
    accumulated events and send ONE combined email.

    Args:
        client (Client):       The client who should receive the email.
        event_type (str):      One of: 'booking_confirmed', 'booking_reserved',
                               'booking_confirmed_paid', 'package_activated'.
        context (dict):        Event-specific data (booking_id, amount, etc.).
                               booking_id is used by the flush task to load
                               fresh data from the DB.
        group_key (str):       Unique key tying related events together.
                               Format: 'booking_{id}' or 'pkg_{id}'.
        window_seconds (int):  How long to wait before flushing.
                               45 s for package/payment events.
                               120 s for pending-payment bookings.

    Note:
        Errors are silently logged — a notification failure must never block
        a booking or payment from completing.
    """
    try:
        from clients.models import NotificationOutbox

        event = {
            'type': event_type,
            'context': context,
            'ts': timezone.now().isoformat(),
        }

        outbox, created = NotificationOutbox.objects.get_or_create(
            group_key=group_key,
            defaults={
                'client': client,
                'events': [event],
                'send_after': timezone.now() + timedelta(seconds=window_seconds),
            },
        )

        if not created:
            # Append to existing group; the already-scheduled task picks this up
            outbox.events = outbox.events + [event]
            outbox.save(update_fields=['events'])
            logger.debug('Appended %s to outbox group %s', event_type, group_key)
        else:
            # Schedule the flush task
            from clients.tasks import flush_notification_group
            flush_notification_group.apply_async(
                args=[group_key],
                countdown=window_seconds,
            )
            logger.debug('Queued %s for group %s (flush in %ds)', event_type, group_key, window_seconds)

    except Exception:
        # Never let notification queuing break the booking/payment flow
        logger.exception('queue_grouped_notification failed for group %s', group_key)
