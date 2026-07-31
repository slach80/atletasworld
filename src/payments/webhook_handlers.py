"""
Private webhook handler functions for Stripe events.

All handlers are called from payments.views.payments_webhook and share
no HTTP state — they receive only the Stripe event data object.
"""
import logging

from django.conf import settings
from django.utils import timezone

from clients.models import Client, Package, ClientPackage
from payments.models import Payment
from payments.stripe_utils import get_stripe as _stripe

logger = logging.getLogger(__name__)


def _handle_payment_succeeded(intent):
    """PaymentIntent succeeded → activate package or mark rental paid."""
    try:
        payment = Payment.objects.get(stripe_payment_intent_id=intent['id'])
        payment.status = 'succeeded'
        payment.stripe_charge_id = intent.get('latest_charge', '')
        payment.save()
    except Payment.DoesNotExist:
        # May be a booking drop-in payment — handled via metadata below
        logger.info('payment_intent.succeeded: no Payment record for %s (may be booking payment)', intent['id'])

    metadata     = intent.get('metadata', {})
    payment_type = metadata.get('type')

    if payment_type == 'package_purchase':
        _activate_package(
            client_id=metadata.get('client_id'),
            package_id=metadata.get('package_id'),
            payment_intent_id=intent['id'],
            metadata=metadata,
            subscription_id=metadata.get('subscription_id', ''),
        )

    elif payment_type == 'batch_package_purchase':
        _activate_batch_packages(
            client_id=metadata.get('client_id'),
            package_id=metadata.get('package_id'),
            players_json=metadata.get('players', '[]'),
            payment_intent_id=intent['id'],
            metadata=metadata,
        )

    elif payment_type == 'multi_package_purchase':
        _activate_multi_packages(
            client_id=metadata.get('client_id'),
            items_json=metadata.get('items', '[]'),
            payment_intent_id=intent['id'],
            metadata=metadata,
        )

    elif payment_type == 'facility_rental':
        _mark_rental_paid(
            slot_id=metadata.get('slot_id'),
            payment_intent_id=intent['id'],
        )

    elif metadata.get('type') == 'drop_in_booking':
        _create_paid_bookings(
            client_id=metadata.get('client_id'),
            items_json=metadata.get('items', '[]'),
            payment_intent_id=intent['id'],
            metadata=metadata,
        )

    elif metadata.get('booking_ids'):
        ids = metadata['booking_ids'].split(',')
        per_booking_amount = intent.get('amount', 0) // len(ids) if ids else 0
        for bid in ids:
            _confirm_booking_paid(
                booking_id=bid.strip(),
                payment_intent_id=intent['id'],
                amount=per_booking_amount,
            )

    elif metadata.get('booking_id'):
        _confirm_booking_paid(
            booking_id=metadata.get('booking_id'),
            payment_intent_id=intent['id'],
            amount=intent.get('amount', 0),
        )

    # Send payment receipt for all successful payments
    _send_payment_receipt(intent, metadata)


def _send_payment_receipt(intent, metadata):
    """Send a payment receipt email after any successful PaymentIntent."""
    import json
    from decimal import Decimal
    from django.template.loader import render_to_string
    from clients.models import Client
    from clients.services import NotificationService

    client_id = metadata.get('client_id')
    if not client_id:
        return

    try:
        client = Client.objects.select_related('user').get(pk=client_id)
    except Client.DoesNotExist:
        return

    amount_cents = intent.get('amount', 0)
    amount = Decimal(amount_cents) / 100
    description = intent.get('description', 'Payment')
    payment_intent_id = intent['id']
    charge_id = intent.get('latest_charge', '')

    # Try to get payment method details from Stripe
    payment_method_str = ''
    try:
        s = _stripe()
        if charge_id:
            charge = s.Charge.retrieve(charge_id)
            pm = charge.get('payment_method_details', {})
            card = pm.get('card', {})
            if card:
                brand = (card.get('brand') or '').capitalize()
                last4 = card.get('last4', '')
                payment_method_str = f'{brand} ending in {last4}' if brand else f'Card ending in {last4}'
    except Exception:
        pass

    # Build line items from metadata
    line_items = []
    discount_total = ''
    credit_applied = ''

    items_json = metadata.get('items') or metadata.get('players')
    if items_json:
        try:
            items_data = json.loads(items_json)
            for item in items_data:
                li = {'amount': f"{Decimal(item.get('price', '0')):.2f}"}
                if 'player_id' in item:
                    from clients.models import Player
                    try:
                        p = Player.objects.get(pk=item['player_id'])
                        li['player'] = f'{p.first_name} {p.last_name}'
                    except Player.DoesNotExist:
                        pass
                if 'package_id' in item:
                    try:
                        pkg = Package.objects.get(pk=item['package_id'])
                        li['name'] = pkg.name
                    except Package.DoesNotExist:
                        li['name'] = description
                else:
                    pkg_id = metadata.get('package_id')
                    if pkg_id:
                        try:
                            li['name'] = Package.objects.get(pk=pkg_id).name
                        except Package.DoesNotExist:
                            li['name'] = description
                    else:
                        li['name'] = description
                line_items.append(li)
        except (json.JSONDecodeError, TypeError):
            pass

    if metadata.get('discount_amount'):
        try:
            da = Decimal(metadata['discount_amount'])
            if da > 0:
                discount_total = f'{da:.2f}'
        except Exception:
            pass

    if metadata.get('credit_applied'):
        try:
            ca = Decimal(metadata['credit_applied'])
            if ca > 0:
                credit_applied = f'{ca:.2f}'
        except Exception:
            pass

    site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
    ctx = {
        'amount_paid': f'{amount:.2f}',
        'description': description,
        'payment_date': timezone.localtime().strftime('%B %-d, %Y at %-I:%M %p'),
        'payment_method': payment_method_str,
        'transaction_id': payment_intent_id,
        'line_items': line_items,
        'discount_total': discount_total,
        'credit_applied': credit_applied,
        'packages_url': f'{site_url}/portal/packages/',
        'client_name': client.user.first_name or client.user.username,
        'site_url': site_url,
        'current_year': timezone.now().year,
    }

    try:
        html_content = render_to_string('emails/payment_receipt.html', ctx)
        text_content = (
            f"Payment Receipt\n\n"
            f"Amount: ${amount:.2f}\n"
            f"Description: {description}\n"
            f"Date: {ctx['payment_date']}\n"
            f"Transaction: {payment_intent_id}\n\n"
            f"View your packages: {site_url}/portal/packages/"
        )
        NotificationService.send_email(
            to_email=client.user.email,
            subject=f'🧾 Payment Receipt — ${amount:.2f}',
            html_content=html_content,
            text_content=text_content,
            context=ctx,
        )
        logger.info('Payment receipt sent to %s for %s', client.user.email, payment_intent_id)
    except Exception:
        logger.exception('Failed to send payment receipt for %s', payment_intent_id)


def _activate_package(client_id, package_id, payment_intent_id, metadata=None, subscription_id=''):
    """Create an active ClientPackage after successful payment."""
    from datetime import timedelta
    from decimal import Decimal
    try:
        client  = Client.objects.get(pk=client_id)
        package = Package.objects.get(pk=package_id)
    except (Client.DoesNotExist, Package.DoesNotExist):
        logger.error('activate_package: client %s or package %s not found', client_id, package_id)
        return

    # Extract subscription_id from metadata if not passed directly
    if not subscription_id and metadata:
        subscription_id = metadata.get('subscription_id', '')

    cp = ClientPackage.objects.create(
        client=client,
        package=package,
        status='active',
        start_date=timezone.localdate(),
        expiry_date=package.event_end_date if package.event_end_date else timezone.localdate() + timedelta(weeks=package.validity_weeks),
        sessions_remaining=package.sessions_included,
        stripe_payment_id=payment_intent_id,
        stripe_subscription_id=subscription_id or '',
    )
    logger.info('ClientPackage #%s activated for %s — %s', cp.pk, client, package.name)
    # Queue package activation email (45-second window)
    try:
        from clients.notification_utils import queue_grouped_notification
        queue_grouped_notification(
            client=client,
            event_type='package_activated',
            context={
                'package_id': cp.id,
                'package_name': package.name,
                'price': float(package.price),
            },
            group_key=f'pkg_{cp.id}',
            window_seconds=45,
        )
    except Exception:
        logger.exception('_activate_package: notification queuing failed for package %s', cp.pk)

    # Finalize pending DiscountCodeUse for this PaymentIntent
    from clients.models import DiscountCodeUse
    DiscountCodeUse.objects.filter(
        stripe_payment_intent_id=payment_intent_id, status='pending'
    ).update(status='applied', applied_to_package=cp)

    # Finalize APC Select credits that were applied during checkout
    if metadata:
        credit_applied_str = metadata.get('credit_applied', '0')
        try:
            remaining = Decimal(credit_applied_str)
        except Exception:
            remaining = Decimal('0')
        if remaining > 0:
            from clients.models import ClientCredit
            for credit in client.credits.filter(status='available').order_by('expires_at'):
                if credit.is_usable and remaining > 0:
                    use_amount = min(credit.amount, remaining)
                    credit.status = 'applied'
                    credit.applied_to = cp
                    credit.applied_at = timezone.now()
                    credit.save(update_fields=['status', 'applied_to', 'applied_at'])
                    remaining -= use_amount

    # APC Select: auto-grant 6×$40 monthly credits (staggered, one per month)
    if package.package_type == 'select':
        from clients.models import ClientCredit
        from datetime import date
        # Only create credits if the client has no unused select_monthly credits already.
        # Prevents stacking on re-subscription or accidental duplicate activations.
        existing = ClientCredit.objects.filter(
            client=client, credit_type='select_monthly', status='available'
        ).count()
        if existing == 0:
            year_end = date(timezone.localdate().year, 12, 31)
            for month in range(1, 7):
                ClientCredit.objects.create(
                    client=client,
                    amount=Decimal('40.00'),
                    credit_type='select_monthly',
                    source_package=cp,
                    expires_at=year_end,
                    notes=f'APC Select — Month {month} training credit ($40 toward any APC Training session or package)',
                )
            logger.info('APC Select: 6 monthly credits created for %s', client)
        else:
            logger.info('APC Select: skipped credit creation for %s — %s unused credits already exist', client, existing)

    # Referral activation: check if this is the referred user's first purchase
    try:
        from clients.services import ReferralService
        ReferralService.check_and_activate(client, package.price)
    except Exception:
        logger.exception('_activate_package: referral activation failed for client %s', client.pk)


def _activate_batch_packages(client_id, package_id, players_json, payment_intent_id, metadata=None):
    """Create multiple ClientPackages (one per player) after successful batch payment."""
    import json
    from datetime import timedelta
    from decimal import Decimal
    from clients.models import Player, DiscountCodeUse

    try:
        client = Client.objects.get(pk=client_id)
        package = Package.objects.get(pk=package_id)
        players_data = json.loads(players_json)
    except (Client.DoesNotExist, Package.DoesNotExist, json.JSONDecodeError) as e:
        logger.error('_activate_batch_packages: invalid data — %s', e)
        return

    expiry = package.event_end_date if package.event_end_date else timezone.localdate() + timedelta(weeks=package.validity_weeks)
    created_packages = []

    for item in players_data:
        try:
            player = Player.objects.get(pk=item['player_id'], client=client)
        except Player.DoesNotExist:
            logger.error('_activate_batch_packages: player %s not found', item.get('player_id'))
            continue

        cp = ClientPackage.objects.create(
            client=client,
            package=package,
            player=player,
            status='active',
            start_date=timezone.localdate(),
            expiry_date=expiry,
            sessions_remaining=package.sessions_included,
            stripe_payment_id=payment_intent_id,
        )
        created_packages.append(cp)
        logger.info('Batch: ClientPackage #%s activated for %s (%s)', cp.pk, player, package.name)

        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=client,
                event_type='package_activated',
                context={
                    'package_id': cp.id,
                    'package_name': package.name,
                    'player_name': f'{player.first_name} {player.last_name}',
                    'price': float(item.get('price', package.price)),
                },
                group_key=f'pkg_{cp.id}',
                window_seconds=45,
            )
        except Exception:
            pass

    # Finalize discount code uses
    if created_packages:
        DiscountCodeUse.objects.filter(
            stripe_payment_intent_id=payment_intent_id, status='pending'
        ).update(status='applied', applied_to_package=created_packages[0])

    # Finalize APC Select credits
    if metadata and created_packages:
        credit_applied_str = metadata.get('credit_applied', '0')
        try:
            remaining = Decimal(credit_applied_str)
        except Exception:
            remaining = Decimal('0')
        if remaining > 0:
            from clients.models import ClientCredit
            for credit in client.credits.filter(status='available').order_by('expires_at'):
                if credit.is_usable and remaining > 0:
                    use_amount = min(credit.amount, remaining)
                    credit.status = 'applied'
                    credit.applied_to = created_packages[0]
                    credit.applied_at = timezone.now()
                    credit.save(update_fields=['status', 'applied_to', 'applied_at'])
                    remaining -= use_amount

    # Referral activation (uses total purchase amount)
    if created_packages:
        total_paid = sum(Decimal(item.get('price', str(package.price))) for item in players_data)
        try:
            from clients.services import ReferralService
            ReferralService.check_and_activate(client, total_paid)
        except Exception:
            logger.exception('_activate_batch_packages: referral activation failed for client %s', client.pk)


def _activate_multi_packages(client_id, items_json, payment_intent_id, metadata=None):
    """Create ClientPackages for a multi-package cart after successful payment."""
    import json
    from datetime import timedelta
    from decimal import Decimal
    from clients.models import Player, DiscountCodeUse

    try:
        client = Client.objects.get(pk=client_id)
        items_data = json.loads(items_json)
    except (Client.DoesNotExist, json.JSONDecodeError) as e:
        logger.error('_activate_multi_packages: invalid data — %s', e)
        return

    created_packages = []
    packages_cache = {}

    for item in items_data:
        pkg_id = item.get('package_id')
        player_id = item.get('player_id')

        if pkg_id not in packages_cache:
            try:
                packages_cache[pkg_id] = Package.objects.get(pk=pkg_id)
            except Package.DoesNotExist:
                logger.error('_activate_multi_packages: package %s not found', pkg_id)
                continue

        package = packages_cache[pkg_id]

        try:
            player = Player.objects.get(pk=player_id, client=client)
        except Player.DoesNotExist:
            logger.error('_activate_multi_packages: player %s not found', player_id)
            continue

        expiry = package.event_end_date if package.event_end_date else timezone.localdate() + timedelta(weeks=package.validity_weeks)

        cp = ClientPackage.objects.create(
            client=client,
            package=package,
            player=player,
            status='active',
            start_date=timezone.localdate(),
            expiry_date=expiry,
            sessions_remaining=package.sessions_included,
            stripe_payment_id=payment_intent_id,
        )
        created_packages.append(cp)
        logger.info('Multi: ClientPackage #%s activated for %s (%s)', cp.pk, player, package.name)

        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=client,
                event_type='package_activated',
                context={
                    'package_id': cp.id,
                    'package_name': package.name,
                    'player_name': f'{player.first_name} {player.last_name}',
                    'price': float(item.get('price', package.price)),
                },
                group_key=f'pkg_{cp.id}',
                window_seconds=45,
            )
        except Exception:
            pass

    # Finalize discount code uses
    if created_packages:
        DiscountCodeUse.objects.filter(
            stripe_payment_intent_id=payment_intent_id, status='pending'
        ).update(status='applied', applied_to_package=created_packages[0])

    # Finalize APC Select credits
    if metadata and created_packages:
        credit_applied_str = metadata.get('credit_applied', '0')
        try:
            remaining = Decimal(credit_applied_str)
        except Exception:
            remaining = Decimal('0')
        if remaining > 0:
            from clients.models import ClientCredit
            for credit in client.credits.filter(status='available').order_by('expires_at'):
                if credit.is_usable and remaining > 0:
                    use_amount = min(credit.amount, remaining)
                    credit.status = 'applied'
                    credit.applied_to = created_packages[0]
                    credit.applied_at = timezone.now()
                    credit.save(update_fields=['status', 'applied_to', 'applied_at'])
                    remaining -= use_amount

    # Referral activation
    if created_packages:
        total_paid = sum(Decimal(item.get('price', '0')) for item in items_data)
        try:
            from clients.services import ReferralService
            ReferralService.check_and_activate(client, total_paid)
        except Exception:
            logger.exception('_activate_multi_packages: referral activation failed for client %s', client.pk)


def _mark_rental_paid(slot_id, payment_intent_id):
    """Mark a FieldRentalSlot as paid after successful payment."""
    try:
        from clients.models import FieldRentalSlot
        slot = FieldRentalSlot.objects.get(pk=slot_id)
        slot.status = 'booked'
        slot.save(update_fields=['status'])
        logger.info('FieldRentalSlot #%s marked paid', slot_id)
    except Exception:
        logger.exception('mark_rental_paid failed for slot %s', slot_id)


def _handle_payment_failed(intent):
    """PaymentIntent failed → update Payment record."""
    try:
        payment = Payment.objects.get(stripe_payment_intent_id=intent['id'])
        payment.status = 'failed'
        payment.save(update_fields=['status'])
    except Payment.DoesNotExist:
        pass


_BILLING_TIER_WEEKS = {
    'monthly': 4,
    'thirds':  16,
    'half':    12,
    'full':    52,
}


def _handle_subscription_renewed(invoice):
    """Subscription billing cycle succeeded → extend ClientPackage expiry and notify member."""
    from datetime import timedelta
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        logger.warning('_handle_subscription_renewed: no subscription in invoice %s', invoice.get('id'))
        return
    cp = ClientPackage.objects.filter(
        stripe_subscription_id=subscription_id, status='active'
    ).select_related('package', 'client').first()
    if not cp:
        # First invoice (billing_reason='subscription_create') fires invoice.payment_succeeded
        # before any ClientPackage exists. Activate it now using the subscription metadata.
        if invoice.get('billing_reason') == 'subscription_create':
            s = _stripe()
            try:
                sub = s.Subscription.retrieve(subscription_id)
                logger.info('_handle_subscription_renewed: retrieved subscription %s for first invoice', subscription_id)
            except Exception as e:
                logger.exception('_handle_subscription_renewed: could not retrieve sub %s: %s', subscription_id, e)
                return
            meta = sub.get('metadata', {})
            client_id  = meta.get('client_id')
            package_id = meta.get('package_id')
            logger.info('_handle_subscription_renewed: first invoice for %s — client_id=%s, package_id=%s', subscription_id, client_id, package_id)
            if client_id and package_id:
                payment_intent_id = invoice.get('payment_intent') or f'invoice_{invoice.get("id", "")}'
                _activate_package(
                    client_id=client_id,
                    package_id=package_id,
                    payment_intent_id=payment_intent_id,
                    subscription_id=subscription_id,
                )
                logger.info('_handle_subscription_renewed: activated new subscription %s for client %s', subscription_id, client_id)
            else:
                logger.warning('_handle_subscription_renewed: no client_id/package_id in sub %s metadata', subscription_id)
        else:
            logger.warning('_handle_subscription_renewed: no cp found for %s and billing_reason=%s (not subscription_create)', subscription_id, invoice.get('billing_reason'))
        return

    tier = cp.package.billing_tier or 'monthly'
    weeks = _BILLING_TIER_WEEKS.get(tier, 4)
    if tier not in _BILLING_TIER_WEEKS:
        logger.warning('Subscription renewed: unknown billing_tier %r on package %s — defaulting to 4 weeks', tier, cp.package_id)
    if cp.package.event_end_date:
        cp.expiry_date = cp.package.event_end_date
    else:
        cp.expiry_date = timezone.localdate() + timedelta(weeks=weeks)
    if cp.package.sessions_included > 0:
        cp.sessions_remaining = cp.package.sessions_included
    cp.save(update_fields=['expiry_date', 'sessions_remaining'])
    logger.info('Subscription renewed: ClientPackage #%s extended to %s (%s weeks, tier=%s, sessions_remaining=%s)', cp.pk, cp.expiry_date, weeks, tier, cp.sessions_remaining)

    # Notify the member — in-app + email
    msg = (f'Your APC Select membership has been renewed. '
           f'Access continues through {cp.expiry_date.strftime("%B %-d, %Y")}.')
    try:
        from clients.models import Notification
        Notification.objects.create(
            client=cp.client, notification_type='promotional',
            title='APC Select Membership Renewed', message=msg, method='in_app',
        )
    except Exception:
        logger.exception('_handle_subscription_renewed: in-app notification failed for cp %s', cp.pk)
    try:
        from clients.services import NotificationService
        amount_cents = invoice.get('amount_paid', 0)
        amount = amount_cents / 100
        html = (f'<h2>APC Select Membership Renewed</h2>'
                f'<p>Your APC Select membership has been successfully renewed.</p>'
                f'<div class="highlight-box"><div class="label">Amount Charged</div>'
                f'<div class="value"><strong>${amount:.2f}</strong></div></div>'
                f'<div class="highlight-box"><div class="label">Access Through</div>'
                f'<div class="value"><strong>{cp.expiry_date.strftime("%B %-d, %Y")}</strong></div></div>'
                f'<p style="text-align:center;margin-top:20px;">'
                f'<a href="https://atletasperformancecenter.com/portal/packages/" class="btn">View My Membership</a></p>')
        NotificationService.send_email(
            cp.client.user.email,
            'APC Select Membership Renewed',
            html, msg,
            context={'subject': 'APC Select Membership Renewed'},
        )
    except Exception:
        logger.exception('_handle_subscription_renewed: email failed for cp %s', cp.pk)


def _handle_subscription_payment_failed(invoice):
    """Subscription payment failed → notify member to update their card."""
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return
    # Only notify on the first failure attempt (attempt_count == 1) to avoid spam
    if invoice.get('attempt_count', 1) != 1:
        return
    cp = ClientPackage.objects.filter(
        stripe_subscription_id=subscription_id, status='active'
    ).select_related('client').first()
    if not cp:
        return
    site_url = 'https://atletasperformancecenter.com'
    msg = (f'Your APC Select membership payment could not be processed. '
           f'Please update your payment method at {site_url}/portal/packages/ '
           f'to keep your membership active. Stripe will retry automatically.')
    try:
        from clients.models import Notification
        Notification.objects.create(
            client=cp.client, notification_type='promotional',
            title='APC Select — Payment Failed', message=msg, method='in_app',
        )
    except Exception:
        logger.exception('_handle_subscription_payment_failed: in-app notification failed for cp %s', cp.pk)
    try:
        from clients.services import NotificationService
        html = (f'<h2>APC Select — Payment Failed</h2>'
                f'<p>We were unable to process your APC Select membership payment.</p>'
                f'<p>Please update your payment method to keep your membership active. '
                f'Stripe will automatically retry the charge.</p>'
                f'<p style="text-align:center;margin-top:20px;">'
                f'<a href="{site_url}/portal/packages/" class="btn">Update Payment Method</a></p>')
        NotificationService.send_email(
            cp.client.user.email,
            'APC Select — Payment Failed',
            html, msg,
            context={'subject': 'APC Select — Payment Failed'},
        )
    except Exception:
        logger.exception('_handle_subscription_payment_failed: email failed for cp %s', cp.pk)


def _handle_invoice_upcoming(invoice):
    """Upcoming invoice (7 days before renewal) → remind member of upcoming charge."""
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return
    cp = ClientPackage.objects.filter(
        stripe_subscription_id=subscription_id, status='active'
    ).select_related('package', 'client').first()
    if not cp:
        return
    from decimal import Decimal
    amount_cents = invoice.get('amount_due', 0)
    amount = Decimal(amount_cents) / 100
    period_end_ts = invoice.get('period_end')
    if period_end_ts:
        import datetime
        renewal_date = datetime.datetime.utcfromtimestamp(period_end_ts).strftime('%B %-d, %Y')
    else:
        renewal_date = 'soon'
    msg = (f'Your APC Select membership will automatically renew on {renewal_date} '
           f'for ${amount:.2f}. No action needed — your card on file will be charged.')
    try:
        from clients.models import Notification
        Notification.objects.create(
            client=cp.client, notification_type='promotional',
            title='APC Select Renewing Soon', message=msg, method='in_app',
        )
    except Exception:
        logger.exception('_handle_invoice_upcoming: in-app notification failed for cp %s', cp.pk)
    try:
        from clients.services import NotificationService
        site_url = 'https://atletasperformancecenter.com'
        html = (f'<h2>APC Select Membership Renewing Soon</h2>'
                f'<p>Your APC Select membership will automatically renew on <strong>{renewal_date}</strong>.</p>'
                f'<div class="highlight-box"><div class="label">Amount</div>'
                f'<div class="value"><strong>${amount:.2f}</strong></div></div>'
                f'<p>No action needed — your card on file will be charged automatically.</p>'
                f'<p style="text-align:center;margin-top:20px;">'
                f'<a href="{site_url}/portal/packages/" class="btn">Manage Membership</a></p>')
        NotificationService.send_email(
            cp.client.user.email,
            'APC Select Membership Renewing Soon',
            html, msg,
            context={'subject': 'APC Select Membership Renewing Soon'},
        )
    except Exception:
        logger.exception('_handle_invoice_upcoming: email failed for cp %s', cp.pk)


def _handle_subscription_cancelled(subscription):
    """Subscription cancelled/deleted → expire ClientPackage only after paid period ends."""
    import datetime as _dt

    cp = ClientPackage.objects.filter(
        stripe_subscription_id=subscription['id']
    ).select_related('client').first()
    if not cp:
        return

    # Stripe fires this webhook at period end when cancel_at_period_end=True.
    # The member already paid through expiry_date — keep the package active until then
    # so they get what they paid for; a background task will expire it naturally.
    # Only immediately expire if the cancel was immediate (canceled_at < current period end).
    today = timezone.localdate()
    if cp.expiry_date and cp.expiry_date > today:
        # Still within paid period — clear subscription ID to stop auto-renewal but keep active
        cp.stripe_subscription_id = ''
        cp.save(update_fields=['stripe_subscription_id'])
        logger.info('Subscription cancelled: ClientPackage #%s retains access until %s', cp.pk, cp.expiry_date)
    else:
        cp.status = 'expired'
        cp.save(update_fields=['status'])
        logger.info('Subscription cancelled: ClientPackage #%s expired immediately', cp.pk)

    # Notify the member — in-app + email
    # Distinguish voluntary cancel (still within paid period) from payment-failure cancel (expired immediately)
    site_url = 'https://atletasperformancecenter.com'
    cancellation_reason = subscription.get('cancellation_details', {}).get('reason', '')
    payment_failed_cancel = (not (cp.expiry_date and cp.expiry_date > today)
                             or cancellation_reason == 'payment_failed')
    if not payment_failed_cancel:
        subject = 'APC Select Auto-Renewal Cancelled'
        msg = (f'Your APC Select auto-renewal has been cancelled. '
               f'Your access continues through {cp.expiry_date.strftime("%B %-d, %Y")} — '
               f'no further charges will be made.')
        html = (f'<h2>APC Select Auto-Renewal Cancelled</h2>'
                f'<p>Your APC Select auto-renewal has been cancelled.</p>'
                f'<div class="highlight-box"><div class="label">Access Through</div>'
                f'<div class="value"><strong>{cp.expiry_date.strftime("%B %-d, %Y")}</strong></div></div>'
                f'<p>No further charges will be made. You can re-subscribe at any time.</p>'
                f'<p style="text-align:center;margin-top:20px;">'
                f'<a href="{site_url}/portal/packages/" class="btn">Manage Membership</a></p>')
    else:
        subject = 'APC Select — Membership Expired'
        msg = (f'Your APC Select membership has expired due to a payment failure. '
               f'Please update your payment method and re-subscribe to regain access.')
        html = (f'<h2>APC Select Membership Expired</h2>'
                f'<p>Your APC Select membership has expired because we were unable to process your payment after multiple attempts.</p>'
                f'<p>To regain access, please update your payment method and re-subscribe.</p>'
                f'<p style="text-align:center;margin-top:20px;">'
                f'<a href="{site_url}/portal/packages/" class="btn">Re-subscribe</a></p>')
    try:
        from clients.models import Notification
        Notification.objects.create(
            client=cp.client, notification_type='promotional',
            title=subject, message=msg, method='in_app',
        )
    except Exception:
        logger.exception('_handle_subscription_cancelled: in-app notification failed')
    try:
        from clients.services import NotificationService
        NotificationService.send_email(
            cp.client.user.email, subject, html, msg,
            context={'subject': subject},
        )
    except Exception:
        logger.exception('_handle_subscription_cancelled: email failed')


def _handle_refund(charge):
    """Charge refunded → mark Payment as refunded."""
    try:
        payment = Payment.objects.get(stripe_charge_id=charge['id'])
        payment.status = 'refunded'
        payment.save(update_fields=['status'])
        logger.info('Payment #%s marked refunded', payment.pk)
    except Payment.DoesNotExist:
        pass


def _confirm_booking_paid(booking_id, payment_intent_id, amount):
    """Confirm a drop-in booking after successful Stripe payment."""
    from bookings.models import Booking
    from decimal import Decimal
    try:
        booking = Booking.objects.get(pk=booking_id, payment_status='pending')
        booking.payment_status = 'paid'
        booking.amount_paid = Decimal(amount) / 100
        booking.save(update_fields=['payment_status', 'amount_paid'])
        booking.confirm()
        logger.info('Booking #%s confirmed after payment %s', booking_id, payment_intent_id)
        # Finalize any pending discount code use for this booking
        from clients.models import DiscountCodeUse
        DiscountCodeUse.objects.filter(
            applied_to_booking=booking, status='pending'
        ).update(status='applied')
        # Queue confirmation email — appends to the 2-min reservation window if still open,
        # otherwise creates a new group (late payment) → separate "payment received" email
        try:
            from clients.notification_utils import queue_grouped_notification
            queue_grouped_notification(
                client=booking.client,
                event_type='booking_confirmed_paid',
                context={
                    'booking_id': booking.id,
                    'amount': float(booking.amount_paid),
                },
                group_key=f'booking_{booking.id}',
                window_seconds=45,
            )
        except Exception:
            logger.exception('_confirm_booking_paid: notification queuing failed for booking %s', booking_id)
    except Booking.DoesNotExist:
        logger.warning('_confirm_booking_paid: booking %s not found or already paid', booking_id)


def _create_paid_bookings(client_id, items_json, payment_intent_id, metadata=None):
    """Create confirmed bookings after successful drop-in payment (no pending state)."""
    import json
    from decimal import Decimal
    from bookings.models import Booking
    from coaches.models import ScheduleBlock
    from clients.models import Client, Player, DiscountCodeUse

    try:
        items = json.loads(items_json)
        client = Client.objects.get(pk=client_id)
    except (json.JSONDecodeError, Client.DoesNotExist) as e:
        logger.error('_create_paid_bookings: invalid data — %s', e)
        return

    created_bookings = []
    for item in items:
        try:
            block = ScheduleBlock.objects.select_related('coach').prefetch_related('catalog_session_types').get(id=item['block_id'])
            player = Player.objects.get(id=item['player_id'], client=client)
            catalog_types = list(block.catalog_session_types.all())
            session_type = catalog_types[0] if catalog_types else None

            booking = Booking.objects.create(
                client=client,
                player=player,
                coach=block.coach,
                session_type=session_type,
                scheduled_date=block.date,
                scheduled_time=block.start_time,
                client_package=None,
                status='confirmed',
                payment_status='paid',
                amount_paid=Decimal(item.get('amount', '0')),
            )
            created_bookings.append(booking)

            # Update block availability
            block.current_participants += 1
            if block.current_participants >= block.max_participants:
                block.status = 'booked'
            block.save()

            logger.info('Drop-in booking #%s created after payment %s', booking.id, payment_intent_id)

            try:
                from clients.notification_utils import queue_grouped_notification
                queue_grouped_notification(
                    client=client,
                    event_type='booking_confirmed_paid',
                    context={'booking_id': booking.id, 'amount': float(booking.amount_paid)},
                    group_key=f'booking_{booking.id}',
                    window_seconds=45,
                )
            except Exception:
                pass

        except Exception as e:
            logger.exception('_create_paid_bookings: failed to create booking for item %s — %s', item, e)

    # Finalise pending discount code use if one was applied
    try:
        DiscountCodeUse.objects.filter(
            stripe_payment_intent_id=payment_intent_id,
            status='pending',
        ).update(
            status='applied',
            applied_to_booking=created_bookings[0] if created_bookings else None,
        )
    except Exception as e:
        logger.warning('_create_paid_bookings: could not finalise discount use for %s — %s', payment_intent_id, e)

    # Finalise APC Select credits that were applied during checkout
    if metadata:
        credit_applied_str = metadata.get('credit_applied', '0')
        try:
            remaining = Decimal(credit_applied_str)
        except Exception:
            remaining = Decimal('0')
        if remaining > 0:
            from clients.models import ClientCredit
            for credit in client.credits.filter(status='available').order_by('expires_at'):
                if credit.is_usable and remaining > 0:
                    use_amount = min(credit.amount, remaining)
                    credit.status = 'applied'
                    credit.applied_at = timezone.now()
                    credit.save(update_fields=['status', 'applied_at'])
                    remaining -= use_amount
