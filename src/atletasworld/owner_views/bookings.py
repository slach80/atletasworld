from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from coaches.models import Coach
from bookings.models import Booking, SessionType
from clients.models import Client, ClientPackage, Package
from django.views.decorators.http import require_POST
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_bookings(request):
    """List all bookings with filters."""
    from clients.models import Package
    from django.core.paginator import Paginator
    import csv
    from django.http import HttpResponse

    today = timezone.localdate()
    status_filter       = request.GET.get('status', '')
    coach_filter        = request.GET.get('coach', '')
    date_filter         = request.GET.get('date', '')
    date_from_filter    = request.GET.get('date_from', '')
    date_to_filter      = request.GET.get('date_to', '')
    session_type_filter = request.GET.get('session_type', '')
    package_type_filter = request.GET.get('package_type', '')
    search              = request.GET.get('q', '').strip()
    export              = request.GET.get('export', '')

    from django.db.models import Q
    bookings = Booking.objects.select_related(
        'client__user', 'player', 'coach__user', 'session_type',
        'client_package__package',
    ).exclude(
        client__user__is_staff=True
    ).exclude(
        client__user__is_superuser=True
    ).order_by('-scheduled_date', '-scheduled_time')

    if search:
        bookings = bookings.filter(
            Q(player__first_name__icontains=search) |
            Q(player__last_name__icontains=search) |
            Q(client__user__first_name__icontains=search) |
            Q(client__user__last_name__icontains=search) |
            Q(client__user__email__icontains=search)
        )
    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if coach_filter:
        bookings = bookings.filter(coach_id=coach_filter)
    if date_filter:
        bookings = bookings.filter(scheduled_date=date_filter)
    if date_from_filter:
        bookings = bookings.filter(scheduled_date__gte=date_from_filter)
    if date_to_filter:
        bookings = bookings.filter(scheduled_date__lte=date_to_filter)
    if session_type_filter:
        bookings = bookings.filter(session_type_id=session_type_filter)
    if package_type_filter:
        bookings = bookings.filter(client_package__package__package_type=package_type_filter)

    if export == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="bookings.csv"'
        writer = csv.writer(response)
        writer.writerow(['Date', 'Time', 'Player', 'Client', 'Coach', 'Session Type', 'Status', 'Payment', 'Amount'])
        for bk in bookings:
            writer.writerow([
                bk.scheduled_date,
                bk.scheduled_time.strftime('%H:%M'),
                f"{bk.player.first_name} {bk.player.last_name}" if bk.player else '',
                bk.client.user.get_full_name() or bk.client.user.email,
                str(bk.coach) if bk.coach else '',
                bk.session_type.name if bk.session_type else '',
                bk.get_status_display(),
                bk.get_payment_status_display(),
                bk.amount_paid or '',
            ])
        return response

    paginator = Paginator(bookings, 50)
    page = paginator.get_page(request.GET.get('page', 1))

    context = {
        'bookings': page,
        'paginator': paginator,
        'page_obj': page,
        'coaches': Coach.objects.filter(is_active=True),
        'session_types': SessionType.objects.filter(is_active=True).order_by('name'),
        'status_choices': Booking.STATUS_CHOICES,
        'package_type_choices': Package.PACKAGE_TYPE_CHOICES,
        'status_filter': status_filter,
        'coach_filter': coach_filter,
        'date_filter': date_filter,
        'date_from_filter': date_from_filter,
        'date_to_filter': date_to_filter,
        'session_type_filter': session_type_filter,
        'package_type_filter': package_type_filter,
        'search': search,
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
                # Send confirmation email to client
                try:
                    from clients.notification_utils import queue_grouped_notification
                    queue_grouped_notification(
                        client=booking.client,
                        event_type='booking_confirmed',
                        context={'booking_id': booking.id, 'payment_method': booking.payment_status},
                        group_key=f'booking_{booking.id}',
                        window_seconds=30,
                    )
                except Exception:
                    pass
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')

        elif action == 'cancel':
            reason = request.POST.get('reason', 'other')
            notes = request.POST.get('notes', '')
            try:
                # Bypass can_cancel check for owner cancellations
                booking.status = 'cancelled'
                booking.cancellation_reason = reason
                booking.cancellation_notes = notes
                booking.cancelled_at = timezone.now()
                booking.cancelled_by = request.user
                booking.save()

                # Restore schedule block availability
                from coaches.models import ScheduleBlock as CoachBlock
                try:
                    block = CoachBlock.objects.get(
                        coach=booking.coach,
                        date=booking.scheduled_date,
                        start_time=booking.scheduled_time,
                    )
                    if block.current_participants > 0:
                        block.current_participants -= 1
                        if block.status == 'booked':
                            block.status = 'available'
                        block.save()
                except CoachBlock.DoesNotExist:
                    pass

                # Return session to package if applicable
                if booking.client_package and booking.payment_status == 'package':
                    booking.client_package.sessions_remaining += 1
                    booking.client_package.sessions_used -= 1
                    booking.client_package.save()

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

        elif action == 'mark_paid':
            booking.payment_status = 'paid'
            if not booking.amount_paid:
                booking.amount_paid = booking.session_type.price if booking.session_type else 0
            booking.save()
            messages.success(request, 'Booking marked as paid.')
            return redirect('owner_finances')

        elif action == 'settle_via_package':
            from clients.models import ClientPackage
            package_id = request.POST.get('package_id')
            try:
                package = ClientPackage.objects.get(pk=package_id, client=booking.client)
                if package.sessions_remaining <= 0:
                    messages.error(request, f'Package "{package.package.name}" has no sessions remaining.')
                elif not package.is_valid:
                    messages.error(request, f'Package "{package.package.name}" is expired or inactive.')
                else:
                    booking.use_package(package)
                    booking.save()
                    messages.success(request, f'Booking settled via package "{package.package.name}".')
            except ClientPackage.DoesNotExist:
                messages.error(request, 'Package not found.')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')

        return redirect('owner_booking_detail', pk=pk)

    from clients.models import ClientPackage
    eligible_packages = ClientPackage.objects.filter(
        client=booking.client, status='active'
    ).select_related('package').filter(sessions_remaining__gt=0)

    context = {
        'booking': booking,
        'cancellation_reasons': Booking.CANCELLATION_REASON_CHOICES,
        'eligible_packages': eligible_packages,
    }
    return render(request, 'owner/booking_detail.html', context)
