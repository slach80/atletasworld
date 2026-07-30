import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from coaches.models import Coach, ScheduleBlock
from bookings.models import Booking, SessionType
from django.conf import settings
from ._auth import is_owner

logger = logging.getLogger(__name__)


@login_required
@user_passes_test(is_owner)
def owner_coaches(request):
    """List all coaches with management options."""
    from django.contrib.auth.models import Group
    from clients.models import ReferralCode

    today = timezone.localdate()
    active_client_q = Q(bookings__client__approval_status__in=['approved', 'not_required'])
    coaches_qs = Coach.objects.annotate(
        today_sessions=Count('bookings', filter=active_client_q & Q(
            bookings__scheduled_date=today,
            bookings__status__in=['pending', 'confirmed'],
        )),
        upcoming_sessions=Count('bookings', filter=active_client_q & Q(
            bookings__scheduled_date__gt=today,
            bookings__status__in=['pending', 'confirmed'],
        )),
        total_bookings=Count('bookings'),
        total_players=Count('bookings__player', distinct=True)
    ).select_related('user').order_by('-is_active', 'user__first_name')

    # Get referral codes for all coaches and attach to coach objects
    coaches = list(coaches_qs)
    coach_user_ids = [c.user_id for c in coaches]

    # Get or create referral codes for all coaches
    from clients.services import ReferralService
    coach_codes = {}
    for coach in coaches:
        code_obj = ReferralService.get_or_create_code(coach.user)
        coach_codes[coach.user_id] = code_obj.code if code_obj else None

    # Attach referral code to each coach object for easy template access
    for coach in coaches:
        coach.referral_code = coach_codes.get(coach.user_id, None)

    context = {
        'coaches': coaches,
    }
    return render(request, 'owner/coaches.html', context)


@login_required
@user_passes_test(is_owner)
def owner_coach_add(request):
    """Add a new coach."""
    from django.contrib.auth.models import Group
    from django.utils.text import slugify
    from types import SimpleNamespace

    if request.method == 'POST':
        username   = request.POST.get('username', '').strip()
        email      = request.POST.get('email', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        password   = request.POST.get('password', '')

        # Auto-generate slug from name if left blank; never use raw username/email
        slug_input = request.POST.get('slug', '').strip() or slugify(f'{first_name}-{last_name}')

        def _form_coach():
            """Build a SimpleNamespace that mirrors Coach/User fields for re-rendering."""
            return SimpleNamespace(
                user=SimpleNamespace(first_name=first_name, last_name=last_name, email=email),
                slug=slug_input,
                hourly_rate=request.POST.get('hourly_rate', 0),
                is_active=False, profile_enabled=False, photo=None,
                tagline=request.POST.get('tagline', ''),
                bio=request.POST.get('bio', ''),
                full_bio=request.POST.get('full_bio', ''),
                specializations=request.POST.get('specializations', ''),
                certifications=request.POST.get('certifications', ''),
                experience_years=request.POST.get('experience_years', 0),
                coaching_philosophy=request.POST.get('coaching_philosophy', ''),
                achievements=request.POST.get('achievements', ''),
                instagram_url=request.POST.get('instagram_url', ''),
                facebook_url=request.POST.get('facebook_url', ''),
                twitter_url=request.POST.get('twitter_url', ''),
                linkedin_url=request.POST.get('linkedin_url', ''),
                youtube_url=request.POST.get('youtube_url', ''),
                personal_website=request.POST.get('personal_website', ''),
                gallery_image_1=None, gallery_image_2=None, gallery_image_3=None,
            )

        try:
            if User.objects.filter(username__iexact=username).exists():
                messages.error(request, f'Username "{username}" already exists.')
                return render(request, 'owner/coach_form.html', {'editing': False, 'coach': _form_coach()})
            if User.objects.filter(email__iexact=email).exists():
                messages.error(request, f'A user with email "{email}" already exists.')
                return render(request, 'owner/coach_form.html', {'editing': False, 'coach': _form_coach()})

            # Ensure slug is unique — append -2, -3, … if needed
            slug = slug_input
            counter = 2
            while Coach.objects.filter(slug=slug).exists():
                slug = f'{slug_input}-{counter}'
                counter += 1

            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
            )
            coach_group, _ = Group.objects.get_or_create(name='Coach')
            user.groups.add(coach_group)
            coach = Coach.objects.create(
                user=user,
                slug=slug,
                tagline=request.POST.get('tagline', '')[:200],
                bio=request.POST.get('bio', ''),
                full_bio=request.POST.get('full_bio', ''),
                specializations=request.POST.get('specializations', ''),
                certifications=request.POST.get('certifications', ''),
                experience_years=int(request.POST.get('experience_years', 0) or 0),
                coaching_philosophy=request.POST.get('coaching_philosophy', ''),
                achievements=request.POST.get('achievements', ''),
                instagram_url=request.POST.get('instagram_url', ''),
                facebook_url=request.POST.get('facebook_url', ''),
                twitter_url=request.POST.get('twitter_url', ''),
                linkedin_url=request.POST.get('linkedin_url', ''),
                hourly_rate=request.POST.get('hourly_rate', 0),
                is_active=request.POST.get('is_active') == 'on',
                profile_enabled=request.POST.get('profile_enabled') == 'on',
            )
            if 'photo' in request.FILES:
                coach.photo = request.FILES['photo']
                coach.save(update_fields=['photo'])

            messages.success(request, f'Coach "{first_name} {last_name}" created successfully!')
            return redirect('owner_coaches')
        except Exception as e:
            messages.error(request, f'Error creating coach: {str(e)}')
            return render(request, 'owner/coach_form.html', {'editing': False, 'coach': _form_coach()})

    return render(request, 'owner/coach_form.html', {'editing': False})


@login_required
@user_passes_test(is_owner)
def owner_coach_edit(request, pk):
    """Edit an existing coach."""
    from django.shortcuts import get_object_or_404

    coach = get_object_or_404(Coach, pk=pk)
    today = timezone.localdate()

    # Check for outstanding activities — 2 queries instead of 3
    booking_counts = Booking.objects.filter(coach=coach).aggregate(
        upcoming=Count('id', filter=Q(scheduled_date__gte=today, status__in=['pending', 'confirmed'])),
        pending_assess=Count('id', filter=Q(status='completed', scheduled_date__gte=today - timedelta(days=7)) & ~Q(assessments__isnull=False)),
    )
    upcoming_bookings    = booking_counts['upcoming'] or 0
    pending_assessments  = booking_counts['pending_assess'] or 0
    upcoming_sessions    = ScheduleBlock.objects.filter(coach=coach, date__gte=today, status='available').count()

    has_outstanding = upcoming_bookings > 0 or upcoming_sessions > 0 or pending_assessments > 0

    if request.method == 'POST':
        try:
            # Update user info
            coach.user.first_name = request.POST.get('first_name')
            coach.user.last_name = request.POST.get('last_name')
            coach.user.email = request.POST.get('email')
            coach.user.save()

            # Update coach profile — keep in sync with coach portal edit_profile
            coach.slug             = request.POST.get('slug', coach.user.username)
            coach.tagline          = request.POST.get('tagline', '')[:200]
            coach.bio              = request.POST.get('bio', '')
            coach.full_bio         = request.POST.get('full_bio', '')
            coach.specializations  = request.POST.get('specializations', '')
            coach.certifications   = request.POST.get('certifications', '')
            coach.experience_years = int(request.POST.get('experience_years', 0) or 0)
            coach.coaching_philosophy = request.POST.get('coaching_philosophy', '')
            coach.achievements     = request.POST.get('achievements', '')
            coach.hourly_rate      = request.POST.get('hourly_rate', 0)
            coach.instagram_url    = request.POST.get('instagram_url', '')
            coach.facebook_url     = request.POST.get('facebook_url', '')
            coach.twitter_url      = request.POST.get('twitter_url', '')
            coach.linkedin_url     = request.POST.get('linkedin_url', '')
            coach.youtube_url      = request.POST.get('youtube_url', '')
            coach.personal_website = request.POST.get('personal_website', '')
            coach.is_active        = request.POST.get('is_active') == 'on'
            coach.profile_enabled  = request.POST.get('profile_enabled') == 'on'

            # Photo upload
            if 'photo' in request.FILES:
                coach.photo = request.FILES['photo']
            elif request.POST.get('clear_photo'):
                coach.photo = None

            # Gallery images
            for i in (1, 2, 3):
                key = f'gallery_image_{i}'
                if key in request.FILES:
                    setattr(coach, key, request.FILES[key])
                elif request.POST.get(f'clear_gallery_{i}'):
                    setattr(coach, key, None)

            coach.save()

            messages.success(request, f'Coach "{coach.user.first_name}" updated successfully!')
            return redirect('owner_coaches')
        except Exception as e:
            messages.error(request, f'Error updating coach: {str(e)}')

    context = {
        'coach': coach,
        'editing': True,
        'upcoming_bookings': upcoming_bookings,
        'upcoming_sessions': upcoming_sessions,
        'pending_assessments': pending_assessments,
        'has_outstanding': has_outstanding,
    }
    return render(request, 'owner/coach_form.html', context)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_coach_delete(request, pk):
    """Delete or deactivate a coach."""
    from django.shortcuts import get_object_or_404

    coach = get_object_or_404(Coach, pk=pk)
    today = timezone.localdate()
    permanent = request.POST.get('permanent') == 'true'

    if permanent:
        # Check for outstanding activities before permanent deletion
        upcoming_bookings = Booking.objects.filter(
            coach=coach,
            scheduled_date__gte=today,
            status__in=['pending', 'confirmed']
        ).count()

        upcoming_sessions = ScheduleBlock.objects.filter(
            coach=coach,
            date__gte=today,
            status='available'
        ).count()

        if upcoming_bookings > 0 or upcoming_sessions > 0:
            messages.error(request, f'Cannot delete coach with {upcoming_bookings} upcoming bookings and {upcoming_sessions} scheduled sessions. Please resolve these first.')
            return redirect('owner_coach_edit', pk=pk)

        # Permanent deletion
        coach_name = f"{coach.user.first_name} {coach.user.last_name}"
        user = coach.user

        # Remove from Coach group
        from django.contrib.auth.models import Group
        coach_group = Group.objects.filter(name='Coach').first()
        if coach_group:
            user.groups.remove(coach_group)

        # Delete coach profile
        coach.delete()

        # Delete user account
        user.delete()

        messages.success(request, f'Coach "{coach_name}" has been permanently deleted.')
    else:
        # Just deactivate
        coach.is_active = False
        coach.save()
        messages.success(request, f'Coach "{coach.user.first_name}" has been deactivated.')

    return redirect('owner_coaches')


@login_required
@user_passes_test(is_owner)
def owner_coach_schedule(request, pk):
    """Manage a coach's schedule blocks."""
    from django.shortcuts import get_object_or_404

    coach = get_object_or_404(Coach, pk=pk)
    today = timezone.localdate()

    # Get upcoming schedule blocks
    schedule_blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date__gte=today
    ).order_by('date', 'start_time')[:30]

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_block':
            try:
                catalog_ids = request.POST.getlist('catalog_session_types')
                price_override_raw = request.POST.get('price_override', '').strip()
                price_override = float(price_override_raw) if price_override_raw else None

                # Derive session_type string from first catalog type's format
                session_type_str = 'group'
                if catalog_ids:
                    first_st = SessionType.objects.filter(id__in=catalog_ids, is_active=True).first()
                    if first_st and first_st.session_format == 'private':
                        session_type_str = 'private'

                location_override = request.POST.get('location_override', '').strip()

                block, created = ScheduleBlock.objects.get_or_create(
                    coach=coach,
                    date=request.POST.get('date'),
                    start_time=request.POST.get('start_time'),
                    defaults=dict(
                        end_time=request.POST.get('end_time'),
                        session_type=session_type_str,
                        max_participants=request.POST.get('max_participants', 1),
                        price_override=price_override,
                        location_override=location_override,
                        notes=request.POST.get('notes', ''),
                    )
                )
                if not created:
                    # Block already exists at this slot — update it in place
                    block.end_time = request.POST.get('end_time')
                    block.session_type = session_type_str
                    block.max_participants = request.POST.get('max_participants', 1)
                    block.price_override = price_override
                    block.location_override = location_override
                    if request.POST.get('notes'):
                        block.notes = request.POST.get('notes', '')
                    block.save()
                if catalog_ids:
                    block.catalog_session_types.set(
                        SessionType.objects.filter(id__in=catalog_ids, is_active=True)
                    )
                verb = 'updated' if not created else 'added'
                messages.success(request, f'Schedule block {verb} successfully!')
            except Exception as e:
                messages.error(request, f'Error adding block: {str(e)}')

        elif action == 'delete_block':
            block_id = request.POST.get('block_id')
            try:
                block = ScheduleBlock.objects.get(pk=block_id, coach=coach)
                if block.current_participants == 0:
                    block.delete()
                    messages.success(request, 'Schedule block deleted.')
                else:
                    messages.error(request, 'Cannot delete block with existing bookings.')
            except ScheduleBlock.DoesNotExist:
                messages.error(request, 'Block not found.')

        elif action == 'cancel_block':
            block_id = request.POST.get('block_id')
            try:
                import stripe as _stripe
                from clients.services import NotificationService
                from payments.models import Payment
                from django.utils import timezone as _tz

                _stripe.api_key = settings.STRIPE_SECRET_KEY

                block = ScheduleBlock.objects.get(pk=block_id, coach=coach)
                bookings = Booking.objects.filter(
                    coach=coach,
                    scheduled_date=block.date,
                    scheduled_time=block.start_time,
                    status__in=['pending', 'confirmed'],
                ).select_related('client', 'client_package', 'player', 'session_type')

                cancelled_count = 0
                refunded_count = 0
                sessions_restored = 0

                for booking in bookings:
                    booking.status = 'cancelled'
                    booking.cancellation_reason = 'admin_cancelled'
                    booking.cancellation_notes = 'Session block cancelled by owner'
                    booking.cancelled_at = _tz.now()
                    booking.cancelled_by = request.user
                    booking.save(update_fields=[
                        'status', 'cancellation_reason', 'cancellation_notes',
                        'cancelled_at', 'cancelled_by',
                    ])

                    # Restore package session
                    if booking.client_package and booking.payment_status == 'package':
                        booking.client_package.sessions_remaining += 1
                        booking.client_package.sessions_used = max(0, booking.client_package.sessions_used - 1)
                        booking.client_package.save(update_fields=['sessions_remaining', 'sessions_used'])
                        sessions_restored += 1

                    # Stripe refund for drop-in paid bookings
                    if booking.payment_status == 'paid' and booking.amount_paid > 0:
                        payment = Payment.objects.filter(
                            booking=booking, status='succeeded'
                        ).first()
                        if payment and settings.STRIPE_SECRET_KEY:
                            try:
                                _stripe.Refund.create(
                                    payment_intent=payment.stripe_payment_intent_id,
                                )
                                payment.status = 'refunded'
                                payment.save(update_fields=['status'])
                                booking.payment_status = 'refunded'
                                booking.save(update_fields=['payment_status'])
                                refunded_count += 1
                            except _stripe.error.StripeError as e:
                                logger.error(
                                    'cancel_block: Stripe refund failed for booking %s — %s',
                                    booking.pk, e.user_message,
                                )

                    # Send cancellation notification
                    try:
                        NotificationService.send_booking_cancellation(booking)
                    except Exception:
                        pass

                    cancelled_count += 1

                block.delete()

                parts = [f'{cancelled_count} booking(s) cancelled and clients notified']
                if sessions_restored:
                    parts.append(f'{sessions_restored} package session(s) restored')
                if refunded_count:
                    parts.append(f'{refunded_count} Stripe refund(s) issued')
                messages.success(request, 'Session cancelled — ' + ', '.join(parts) + '.')
            except ScheduleBlock.DoesNotExist:
                messages.error(request, 'Block not found.')

        elif action == 'bulk_set_location':
            location_val = request.POST.get('bulk_location', '').strip()
            day_filter = request.POST.get('bulk_day', '')
            time_filter = request.POST.get('bulk_time', '')
            session_type_filter = request.POST.get('bulk_session_type', '')

            blocks_qs = ScheduleBlock.objects.filter(coach=coach, date__gte=today)
            if day_filter:
                from django.db.models.functions import ExtractWeekDay
                django_dow = int(day_filter) + 2
                if django_dow > 7:
                    django_dow = 1
                blocks_qs = blocks_qs.annotate(dow=ExtractWeekDay('date')).filter(dow=django_dow)
            if time_filter == 'morning':
                blocks_qs = blocks_qs.filter(start_time__lt='12:00')
            elif time_filter == 'afternoon':
                blocks_qs = blocks_qs.filter(start_time__gte='12:00', start_time__lt='17:00')
            elif time_filter == 'evening':
                blocks_qs = blocks_qs.filter(start_time__gte='17:00')
            if session_type_filter:
                blocks_qs = blocks_qs.filter(catalog_session_types__id=session_type_filter)

            count = blocks_qs.update(location_override=location_val)
            messages.success(request, f'Location updated on {count} blocks.')

        return redirect('owner_coach_schedule', pk=pk)

    context = {
        'coach': coach,
        'schedule_blocks': schedule_blocks,
        'session_types': ScheduleBlock.SESSION_TYPE_CHOICES,
        'all_session_types': SessionType.objects.filter(is_active=True).order_by('name'),
    }
    return render(request, 'owner/coach_schedule.html', context)
