"""
Owner dashboard views for Atletas World.
Provides overview across all coaches, clients, and players.
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q
from datetime import timedelta

from coaches.models import Coach, ScheduleBlock, PlayerAssessment
from bookings.models import Booking, SessionType
from clients.models import Client, Player
from reviews.models import Review
from django.contrib.auth.models import User
from django.core.mail import send_mass_mail, send_mail, EmailMessage
from email.mime.image import MIMEImage
from django.conf import settings
from django.views.decorators.http import require_POST


def is_owner(user):
    """Check if user is staff/superuser or in Owner group."""
    return user.is_staff or user.is_superuser or user.groups.filter(name='Owner').exists()


@login_required
@user_passes_test(is_owner)
def owner_dashboard(request):
    """Owner dashboard with overview across all entities."""
    today = timezone.now().date()

    # Coach stats
    total_coaches = Coach.objects.filter(is_active=True).count()
    coaches_with_sessions_today = Coach.objects.filter(
        schedule_blocks__date=today
    ).distinct().count()

    # Client/Player stats
    total_clients = Client.objects.count()
    total_players = Player.objects.filter(is_active=True).count()
    new_clients_this_month = Client.objects.filter(
        user__date_joined__month=today.month,
        user__date_joined__year=today.year
    ).count()

    # Booking stats
    total_bookings = Booking.objects.count()
    todays_bookings = Booking.objects.filter(scheduled_date=today).count()
    completed_bookings = Booking.objects.filter(status='completed').count()
    pending_bookings = Booking.objects.filter(status__in=['pending', 'confirmed']).count()

    # Session stats
    total_sessions_today = ScheduleBlock.objects.filter(date=today).count()
    sessions_this_week = ScheduleBlock.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(days=7)
    ).count()

    # Revenue (this month)
    revenue_this_month = Booking.objects.filter(
        scheduled_date__month=today.month,
        scheduled_date__year=today.year,
        payment_status='paid'
    ).aggregate(total=Sum('amount_paid'))['total'] or 0

    # Assessment stats
    total_assessments = PlayerAssessment.objects.count()
    assessments_this_week = PlayerAssessment.objects.filter(
        assessment_date__gte=today - timedelta(days=7)
    ).count()

    # Review stats
    total_reviews = Review.objects.filter(is_approved=True).count()
    avg_rating = Review.objects.filter(is_approved=True).aggregate(
        avg=Avg('rating')
    )['avg'] or 0

    # Coaches list with their stats
    coaches = Coach.objects.filter(is_active=True).annotate(
        sessions_today=Count(
            'schedule_blocks',
            filter=Q(schedule_blocks__date=today)
        ),
        total_bookings=Count('bookings'),
        total_players=Count('bookings__player', distinct=True)
    ).order_by('-sessions_today')[:10]

    # Today's schedule across all coaches
    todays_schedule = ScheduleBlock.objects.filter(
        date=today
    ).select_related('coach__user').order_by('start_time')[:20]

    # Recent bookings
    recent_bookings = Booking.objects.select_related(
        'client__user', 'player', 'coach__user', 'session_type'
    ).order_by('-created_at')[:10]

    # Upcoming bookings by coach
    upcoming_by_coach = []
    for coach in Coach.objects.filter(is_active=True)[:5]:
        upcoming = Booking.objects.filter(
            coach=coach,
            scheduled_date__gte=today,
            status__in=['pending', 'confirmed']
        ).count()
        upcoming_by_coach.append({
            'coach': coach,
            'upcoming': upcoming
        })

    # Players needing assessment
    players_pending_assessment = Booking.objects.filter(
        status='completed',
        scheduled_date__gte=today - timedelta(days=7)
    ).exclude(
        assessments__isnull=False
    ).select_related('player', 'coach__user')[:10]

    context = {
        'today': today,
        # Main stats
        'total_coaches': total_coaches,
        'coaches_with_sessions_today': coaches_with_sessions_today,
        'total_clients': total_clients,
        'total_players': total_players,
        'new_clients_this_month': new_clients_this_month,
        'total_bookings': total_bookings,
        'todays_bookings': todays_bookings,
        'completed_bookings': completed_bookings,
        'pending_bookings': pending_bookings,
        'total_sessions_today': total_sessions_today,
        'sessions_this_week': sessions_this_week,
        'revenue_this_month': revenue_this_month,
        'total_assessments': total_assessments,
        'assessments_this_week': assessments_this_week,
        'total_reviews': total_reviews,
        'avg_rating': avg_rating,
        # Lists
        'coaches': coaches,
        'todays_schedule': todays_schedule,
        'recent_bookings': recent_bookings,
        'upcoming_by_coach': upcoming_by_coach,
        'players_pending_assessment': players_pending_assessment,
    }
    return render(request, 'owner/dashboard.html', context)


@login_required
@user_passes_test(is_owner)
def owner_notifications(request):
    """Owner notification center - send emails to different groups."""
    # Get counts for each recipient group
    all_clients = Client.objects.select_related('user').filter(user__email__isnull=False).exclude(user__email='')
    all_coaches = Coach.objects.select_related('user').filter(is_active=True, user__email__isnull=False).exclude(user__email='')
    all_users = User.objects.filter(is_active=True, email__isnull=False).exclude(email='')

    # Get clients with upcoming bookings (active clients)
    today = timezone.now().date()
    active_client_ids = Booking.objects.filter(
        scheduled_date__gte=today - timedelta(days=30)
    ).values_list('client_id', flat=True).distinct()
    active_clients = Client.objects.filter(id__in=active_client_ids).select_related('user')

    # Get clients with bookings this week
    weekly_client_ids = Booking.objects.filter(
        scheduled_date__gte=today,
        scheduled_date__lte=today + timedelta(days=7)
    ).values_list('client_id', flat=True).distinct()
    clients_with_bookings_this_week = Client.objects.filter(id__in=weekly_client_ids).select_related('user')

    context = {
        'all_clients_count': all_clients.count(),
        'all_coaches_count': all_coaches.count(),
        'all_users_count': all_users.count(),
        'active_clients_count': active_clients.count(),
        'clients_with_bookings_this_week_count': clients_with_bookings_this_week.count(),
        'all_clients': all_clients,
        'all_coaches': all_coaches,
    }
    return render(request, 'owner/notifications.html', context)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_send_notification(request):
    """Send notifications to selected recipients with optional attachments and images."""
    recipient_group = request.POST.get('recipient_group', '')
    subject = request.POST.get('subject', '').strip()
    message = request.POST.get('message', '').strip()
    individual_emails = request.POST.getlist('individual_emails')
    send_as_html = request.POST.get('send_as_html') == 'on'

    # Handle file uploads
    attachments = request.FILES.getlist('attachments')
    inline_image = request.FILES.get('inline_image')

    if not subject or not message:
        messages.error(request, 'Please provide both subject and message.')
        return redirect('owner_notifications')

    # Collect recipient emails based on group
    recipients = set()
    today = timezone.now().date()

    if recipient_group == 'all_clients':
        emails = Client.objects.filter(
            user__email__isnull=False
        ).exclude(user__email='').values_list('user__email', flat=True)
        recipients.update(emails)

    elif recipient_group == 'all_coaches':
        emails = Coach.objects.filter(
            is_active=True,
            user__email__isnull=False
        ).exclude(user__email='').values_list('user__email', flat=True)
        recipients.update(emails)

    elif recipient_group == 'everyone':
        emails = User.objects.filter(
            is_active=True,
            email__isnull=False
        ).exclude(email='').values_list('email', flat=True)
        recipients.update(emails)

    elif recipient_group == 'active_clients':
        active_client_ids = Booking.objects.filter(
            scheduled_date__gte=today - timedelta(days=30)
        ).values_list('client_id', flat=True).distinct()
        emails = Client.objects.filter(
            id__in=active_client_ids,
            user__email__isnull=False
        ).exclude(user__email='').values_list('user__email', flat=True)
        recipients.update(emails)

    elif recipient_group == 'clients_this_week':
        weekly_client_ids = Booking.objects.filter(
            scheduled_date__gte=today,
            scheduled_date__lte=today + timedelta(days=7)
        ).values_list('client_id', flat=True).distinct()
        emails = Client.objects.filter(
            id__in=weekly_client_ids,
            user__email__isnull=False
        ).exclude(user__email='').values_list('user__email', flat=True)
        recipients.update(emails)

    elif recipient_group == 'individual':
        recipients.update(individual_emails)

    if not recipients:
        messages.error(request, 'No recipients found for the selected group.')
        return redirect('owner_notifications')

    # Send emails
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@atletasworld.com')
        sent_count = 0
        failed_count = 0

        # Read inline image data if provided
        inline_image_data = None
        inline_image_cid = None
        if inline_image:
            inline_image_data = inline_image.read()
            inline_image_cid = 'inline_image'
            inline_image.seek(0)  # Reset for potential reuse

        for email_addr in recipients:
            try:
                if send_as_html or inline_image:
                    # Convert message to HTML (preserve line breaks)
                    html_message = message.replace('\n', '<br>')

                    # Add inline image placeholder if image provided
                    if inline_image_data:
                        html_message = f'<img src="cid:{inline_image_cid}" style="max-width: 100%; height: auto; margin: 20px 0;"><br><br>' + html_message

                    # Wrap in basic HTML template
                    html_content = f'''
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            {html_message}
                        </div>
                    </body>
                    </html>
                    '''

                    # Create email with HTML
                    email_msg = EmailMessage(
                        subject=subject,
                        body=html_content,
                        from_email=from_email,
                        to=[email_addr],
                    )
                    email_msg.content_subtype = 'html'

                    # Add inline image
                    if inline_image_data:
                        mime_image = MIMEImage(inline_image_data)
                        mime_image.add_header('Content-ID', f'<{inline_image_cid}>')
                        mime_image.add_header('Content-Disposition', 'inline', filename=inline_image.name)
                        email_msg.attach(mime_image)

                    # Add attachments
                    for attachment in attachments:
                        attachment.seek(0)  # Reset file pointer
                        email_msg.attach(attachment.name, attachment.read(), attachment.content_type)

                    email_msg.send(fail_silently=False)
                else:
                    # Plain text email with attachments
                    email_msg = EmailMessage(
                        subject=subject,
                        body=message,
                        from_email=from_email,
                        to=[email_addr],
                    )

                    # Add attachments
                    for attachment in attachments:
                        attachment.seek(0)  # Reset file pointer
                        email_msg.attach(attachment.name, attachment.read(), attachment.content_type)

                    email_msg.send(fail_silently=False)

                sent_count += 1
            except Exception as e:
                failed_count += 1

        if failed_count > 0:
            messages.warning(request, f'Sent {sent_count} emails. {failed_count} failed.')
        else:
            messages.success(request, f'Successfully sent {sent_count} emails!')

    except Exception as e:
        messages.error(request, f'Error sending emails: {str(e)}')

    return redirect('owner_notifications')


# ============================================================================
# PACKAGE MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_owner)
def owner_packages(request):
    """List all packages with management options."""
    from clients.models import Package, ClientPackage
    from django.db.models import Count

    packages = Package.objects.annotate(
        active_purchases=Count('clientpackage', filter=Q(clientpackage__status='active')),
        total_purchases=Count('clientpackage')
    ).order_by('-is_active', 'price')

    context = {
        'packages': packages,
    }
    return render(request, 'owner/packages.html', context)


@login_required
@user_passes_test(is_owner)
def owner_package_add(request):
    """Add a new package."""
    from clients.models import Package

    if request.method == 'POST':
        try:
            package = Package.objects.create(
                name=request.POST.get('name'),
                package_type=request.POST.get('package_type'),
                description=request.POST.get('description', ''),
                price=request.POST.get('price'),
                sessions_included=request.POST.get('sessions_included', 0),
                validity_weeks=request.POST.get('validity_weeks', 4),
                is_active=request.POST.get('is_active') == 'on',
                is_special=request.POST.get('is_special') == 'on',
                max_participants=request.POST.get('max_participants', 0),
                age_group=request.POST.get('age_group', ''),
                event_start_date=request.POST.get('event_start_date') or None,
                event_end_date=request.POST.get('event_end_date') or None,
                event_location=request.POST.get('event_location', ''),
            )
            messages.success(request, f'Package "{package.name}" created successfully!')
            return redirect('owner_packages')
        except Exception as e:
            messages.error(request, f'Error creating package: {str(e)}')

    context = {
        'package_types': Package.PACKAGE_TYPE_CHOICES,
    }
    return render(request, 'owner/package_form.html', context)


@login_required
@user_passes_test(is_owner)
def owner_package_edit(request, pk):
    """Edit an existing package."""
    from clients.models import Package
    from django.shortcuts import get_object_or_404

    package = get_object_or_404(Package, pk=pk)

    if request.method == 'POST':
        try:
            package.name = request.POST.get('name')
            package.package_type = request.POST.get('package_type')
            package.description = request.POST.get('description', '')
            package.price = request.POST.get('price')
            package.sessions_included = request.POST.get('sessions_included', 0)
            package.validity_weeks = request.POST.get('validity_weeks', 4)
            package.is_active = request.POST.get('is_active') == 'on'
            package.is_special = request.POST.get('is_special') == 'on'
            package.max_participants = request.POST.get('max_participants', 0)
            package.age_group = request.POST.get('age_group', '')
            package.event_start_date = request.POST.get('event_start_date') or None
            package.event_end_date = request.POST.get('event_end_date') or None
            package.event_location = request.POST.get('event_location', '')
            package.save()
            messages.success(request, f'Package "{package.name}" updated successfully!')
            return redirect('owner_packages')
        except Exception as e:
            messages.error(request, f'Error updating package: {str(e)}')

    context = {
        'package': package,
        'package_types': Package.PACKAGE_TYPE_CHOICES,
        'editing': True,
    }
    return render(request, 'owner/package_form.html', context)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_package_delete(request, pk):
    """Delete a package (soft delete by deactivating)."""
    from clients.models import Package
    from django.shortcuts import get_object_or_404

    package = get_object_or_404(Package, pk=pk)
    package.is_active = False
    package.save()
    messages.success(request, f'Package "{package.name}" has been deactivated.')
    return redirect('owner_packages')


# ============================================================================
# COACH MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_owner)
def owner_coaches(request):
    """List all coaches with management options."""
    from django.contrib.auth.models import Group

    coaches = Coach.objects.annotate(
        total_sessions=Count('schedule_blocks'),
        upcoming_sessions=Count('schedule_blocks', filter=Q(schedule_blocks__date__gte=timezone.now().date())),
        total_bookings=Count('bookings'),
        total_players=Count('bookings__player', distinct=True)
    ).order_by('-is_active', 'user__first_name')

    context = {
        'coaches': coaches,
    }
    return render(request, 'owner/coaches.html', context)


@login_required
@user_passes_test(is_owner)
def owner_coach_add(request):
    """Add a new coach."""
    from django.contrib.auth.models import Group

    if request.method == 'POST':
        try:
            # Create user
            username = request.POST.get('username')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            password = request.POST.get('password')

            # Check if user exists
            if User.objects.filter(username=username).exists():
                messages.error(request, f'Username "{username}" already exists.')
                return redirect('owner_coach_add')
            if User.objects.filter(email=email).exists():
                messages.error(request, f'Email "{email}" already exists.')
                return redirect('owner_coach_add')

            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password
            )

            # Add to Coach group
            coach_group, _ = Group.objects.get_or_create(name='Coach')
            user.groups.add(coach_group)

            # Create coach profile
            coach = Coach.objects.create(
                user=user,
                slug=request.POST.get('slug', username),
                bio=request.POST.get('bio', ''),
                specializations=request.POST.get('specializations', ''),
                hourly_rate=request.POST.get('hourly_rate', 0),
                is_active=request.POST.get('is_active') == 'on',
                profile_enabled=request.POST.get('profile_enabled') == 'on',
            )

            messages.success(request, f'Coach "{first_name} {last_name}" created successfully!')
            return redirect('owner_coaches')
        except Exception as e:
            messages.error(request, f'Error creating coach: {str(e)}')

    return render(request, 'owner/coach_form.html', {'editing': False})


@login_required
@user_passes_test(is_owner)
def owner_coach_edit(request, pk):
    """Edit an existing coach."""
    from django.shortcuts import get_object_or_404

    coach = get_object_or_404(Coach, pk=pk)
    today = timezone.now().date()

    # Check for outstanding activities
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

    pending_assessments = Booking.objects.filter(
        coach=coach,
        status='completed',
        scheduled_date__gte=today - timedelta(days=7)
    ).exclude(assessments__isnull=False).count()

    has_outstanding = upcoming_bookings > 0 or upcoming_sessions > 0 or pending_assessments > 0

    if request.method == 'POST':
        try:
            # Update user info
            coach.user.first_name = request.POST.get('first_name')
            coach.user.last_name = request.POST.get('last_name')
            coach.user.email = request.POST.get('email')
            coach.user.save()

            # Update coach profile
            coach.slug = request.POST.get('slug', coach.user.username)
            coach.bio = request.POST.get('bio', '')
            coach.specializations = request.POST.get('specializations', '')
            coach.hourly_rate = request.POST.get('hourly_rate', 0)
            coach.is_active = request.POST.get('is_active') == 'on'
            coach.profile_enabled = request.POST.get('profile_enabled') == 'on'
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
    today = timezone.now().date()
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
    today = timezone.now().date()

    # Get upcoming schedule blocks
    schedule_blocks = ScheduleBlock.objects.filter(
        coach=coach,
        date__gte=today
    ).order_by('date', 'start_time')[:30]

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_block':
            try:
                ScheduleBlock.objects.create(
                    coach=coach,
                    date=request.POST.get('date'),
                    start_time=request.POST.get('start_time'),
                    end_time=request.POST.get('end_time'),
                    session_type=request.POST.get('session_type', 'private'),
                    max_participants=request.POST.get('max_participants', 1),
                    notes=request.POST.get('notes', ''),
                )
                messages.success(request, 'Schedule block added successfully!')
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

        return redirect('owner_coach_schedule', pk=pk)

    context = {
        'coach': coach,
        'schedule_blocks': schedule_blocks,
        'session_types': ScheduleBlock.SESSION_TYPE_CHOICES,
    }
    return render(request, 'owner/coach_schedule.html', context)


# ============================================================================
# BOOKING/SESSION MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_owner)
def owner_bookings(request):
    """List all bookings with filters."""
    from clients.models import Player

    today = timezone.now().date()
    status_filter = request.GET.get('status', '')
    coach_filter = request.GET.get('coach', '')
    date_filter = request.GET.get('date', '')

    bookings = Booking.objects.select_related(
        'client__user', 'player', 'coach__user', 'session_type'
    ).order_by('-scheduled_date', '-scheduled_time')

    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if coach_filter:
        bookings = bookings.filter(coach_id=coach_filter)
    if date_filter:
        bookings = bookings.filter(scheduled_date=date_filter)

    # Limit to 100 recent bookings
    bookings = bookings[:100]

    context = {
        'bookings': bookings,
        'coaches': Coach.objects.filter(is_active=True),
        'status_choices': Booking.STATUS_CHOICES,
        'status_filter': status_filter,
        'coach_filter': coach_filter,
        'date_filter': date_filter,
    }
    return render(request, 'owner/bookings.html', context)


@login_required
@user_passes_test(is_owner)
def owner_booking_detail(request, pk):
    """View and manage a specific booking."""
    from django.shortcuts import get_object_or_404

    booking = get_object_or_404(
        Booking.objects.select_related('client__user', 'player', 'coach__user', 'session_type', 'client_package'),
        pk=pk
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'confirm':
            try:
                booking.confirm()
                messages.success(request, 'Booking confirmed!')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')

        elif action == 'cancel':
            reason = request.POST.get('reason', 'other')
            notes = request.POST.get('notes', '')
            try:
                booking.status = 'cancelled'
                booking.cancellation_reason = reason
                booking.cancellation_notes = notes
                booking.cancelled_at = timezone.now()
                booking.save()
                messages.success(request, 'Booking cancelled.')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')

        elif action == 'complete':
            try:
                booking.status = 'completed'
                booking.completed_at = timezone.now()
                booking.save()
                messages.success(request, 'Booking marked as completed.')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')

        elif action == 'no_show':
            booking.status = 'no_show'
            booking.save()
            messages.success(request, 'Booking marked as no-show.')

        return redirect('owner_booking_detail', pk=pk)

    context = {
        'booking': booking,
        'cancellation_reasons': Booking.CANCELLATION_REASON_CHOICES,
    }
    return render(request, 'owner/booking_detail.html', context)


# ============================================================================
# CLIENT/PLAYER MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_owner)
def owner_clients(request):
    """List all clients with their players - only users in Client group."""
    from clients.models import ClientPackage
    from django.contrib.auth.models import Group

    # Only show clients who are in the Client group (not coaches with client profiles)
    client_group = Group.objects.filter(name='Client').first()
    if client_group:
        client_user_ids = client_group.user_set.values_list('id', flat=True)
        clients = Client.objects.filter(user_id__in=client_user_ids).select_related('user').annotate(
            player_count=Count('players'),
            active_packages=Count('packages', filter=Q(packages__status='active')),
            total_bookings=Count('bookings')
        ).order_by('-created_at')[:100]
    else:
        clients = Client.objects.none()

    context = {
        'clients': clients,
    }
    return render(request, 'owner/clients.html', context)


@login_required
@user_passes_test(is_owner)
def owner_client_detail(request, pk):
    """View a client's details including players and bookings."""
    from django.shortcuts import get_object_or_404
    from clients.models import ClientPackage

    client = get_object_or_404(Client.objects.select_related('user'), pk=pk)
    players = Player.objects.filter(client=client, is_active=True)
    packages = ClientPackage.objects.filter(client=client).select_related('package')
    recent_bookings = Booking.objects.filter(client=client).select_related('player', 'coach__user')[:20]

    context = {
        'client': client,
        'players': players,
        'packages': packages,
        'recent_bookings': recent_bookings,
    }
    return render(request, 'owner/client_detail.html', context)


@login_required
@user_passes_test(is_owner)
def owner_players(request):
    """List all players."""
    players = Player.objects.select_related('client__user').annotate(
        total_bookings=Count('bookings'),
        total_assessments=Count('assessments')
    ).order_by('first_name', 'last_name')[:200]

    context = {
        'players': players,
    }
    return render(request, 'owner/players.html', context)


# ============================================================================
# SESSION TYPE MANAGEMENT
# ============================================================================

@login_required
@user_passes_test(is_owner)
def owner_session_types(request):
    """Manage session types."""
    session_types = SessionType.objects.annotate(
        total_bookings=Count('bookings')
    ).order_by('name')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            try:
                st = SessionType.objects.create(
                    name=request.POST.get('name'),
                    description=request.POST.get('description', ''),
                    session_format=request.POST.get('session_format', 'private'),
                    duration_minutes=request.POST.get('duration_minutes', 60),
                    price=request.POST.get('price'),
                    max_participants=request.POST.get('max_participants', 1),
                    color=request.POST.get('color', '#2ecc71'),
                    is_active=request.POST.get('is_active') == 'on',
                    # Clinic/Camp fields
                    start_date=request.POST.get('start_date') or None,
                    end_date=request.POST.get('end_date') or None,
                    min_age=request.POST.get('min_age') or None,
                    max_age=request.POST.get('max_age') or None,
                    location=request.POST.get('location', ''),
                )
                messages.success(request, 'Session type created!')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')

        elif action == 'toggle':
            st_id = request.POST.get('session_type_id')
            try:
                st = SessionType.objects.get(pk=st_id)
                st.is_active = not st.is_active
                st.save()
                messages.success(request, f'Session type {"activated" if st.is_active else "deactivated"}.')
            except SessionType.DoesNotExist:
                messages.error(request, 'Session type not found.')

        return redirect('owner_session_types')

    context = {
        'session_types': session_types,
        'format_choices': SessionType.SESSION_FORMAT_CHOICES,
    }
    return render(request, 'owner/session_types.html', context)


@login_required
@user_passes_test(is_owner)
def owner_session_type_edit(request, pk):
    """Edit a session type."""
    from django.shortcuts import get_object_or_404

    session_type = get_object_or_404(SessionType, pk=pk)

    if request.method == 'POST':
        try:
            session_type.name = request.POST.get('name')
            session_type.description = request.POST.get('description', '')
            session_type.session_format = request.POST.get('session_format', 'private')
            session_type.duration_minutes = request.POST.get('duration_minutes', 60)
            session_type.price = request.POST.get('price')
            session_type.max_participants = request.POST.get('max_participants', 1)
            session_type.color = request.POST.get('color', '#2ecc71')
            session_type.is_active = request.POST.get('is_active') == 'on'
            # Clinic/Camp fields
            session_type.start_date = request.POST.get('start_date') or None
            session_type.end_date = request.POST.get('end_date') or None
            session_type.min_age = request.POST.get('min_age') or None
            session_type.max_age = request.POST.get('max_age') or None
            session_type.location = request.POST.get('location', '')
            session_type.save()
            messages.success(request, f'Session type "{session_type.name}" updated!')
            return redirect('owner_session_types')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')

    context = {
        'session_type': session_type,
        'format_choices': SessionType.SESSION_FORMAT_CHOICES,
    }
    return render(request, 'owner/session_type_form.html', context)
