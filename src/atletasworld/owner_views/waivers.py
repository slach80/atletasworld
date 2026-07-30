from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from clients.models import Client, ClientWaiver
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_waivers(request):
    """Waiver compliance dashboard — shows signed and unsigned clients."""
    today = timezone.now()
    current_year = today.year

    if request.method == 'POST' and request.POST.get('action') == 'remind_unsigned':
        from clients.models import Notification
        _unsigned_clients = Client.objects.filter(
            user__groups__name='Client',
            user__is_staff=False,
            user__is_superuser=False,
        ).exclude(
            user__groups__name__in=['Owner', 'Coach']
        ).exclude(
            waivers__valid_year=current_year,
            waivers__waiver_version=ClientWaiver.WAIVER_VERSION,
        ).distinct()
        count = 0
        for client in _unsigned_clients:
            Notification.objects.create(
                client=client,
                title='Action Required: Sign Your 2026 Waiver',
                message='You have not yet signed the 2026 annual waiver. Please log in to your portal and sign it under My Profile to continue booking sessions.',
                notification_type='general',
            )
            count += 1
        messages.success(request, f'Waiver reminder sent to {count} unsigned client{"s" if count != 1 else ""}.')
        return redirect('owner_waivers')

    # Only track waivers for Client group members — exclude coaches, owners, staff
    all_clients = Client.objects.select_related('user').filter(
        user__groups__name='Client',
        user__is_staff=False,
        user__is_superuser=False,
    ).exclude(
        user__groups__name__in=['Owner', 'Coach']
    ).distinct().order_by('user__first_name')

    signed_ids = set(
        ClientWaiver.objects.filter(
            valid_year=current_year,
            waiver_version=ClientWaiver.WAIVER_VERSION,
        ).values_list('client_id', flat=True)
    )

    signed   = [c for c in all_clients if c.id in signed_ids]
    unsigned = [c for c in all_clients if c.id not in signed_ids]

    recent_waivers = ClientWaiver.objects.select_related(
        'client__user'
    ).order_by('-signed_at')[:100]

    if request.GET.get('export') == 'csv':
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="waivers_{current_year}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Name', 'Email', 'Phone', 'Waiver Signed', 'Signed At'])
        for c in signed:
            w = next((w for w in recent_waivers if w.client_id == c.id), None)
            writer.writerow([
                c.user.get_full_name(),
                c.user.email,
                c.phone or '',
                'Yes',
                w.signed_at.strftime('%Y-%m-%d %H:%M') if w else '',
            ])
        for c in unsigned:
            writer.writerow([
                c.user.get_full_name(),
                c.user.email,
                c.phone or '',
                'No',
                '',
            ])
        return response

    context = {
        'signed': signed,
        'unsigned': unsigned,
        'recent_waivers': recent_waivers,
        'current_year': current_year,
        'waiver_version': ClientWaiver.WAIVER_VERSION,
        'total': all_clients.count(),
        'signed_count': len(signed),
    }
    return render(request, 'owner/waivers.html', context)
