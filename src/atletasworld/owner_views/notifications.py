from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from coaches.models import Coach
from bookings.models import Booking
from clients.models import Client
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_notifications(request):
    """Owner notification center - send emails to different groups."""
    from clients.models import Package, ClientPackage, ContactParent, EmailBroadcast
    # Get counts for each recipient group
    all_clients = Client.objects.select_related('user').filter(user__email__isnull=False).exclude(user__email='')
    all_coaches = Coach.objects.select_related('user').filter(is_active=True, user__email__isnull=False).exclude(user__email='')
    all_users = User.objects.filter(is_active=True, email__isnull=False).exclude(email='')

    today = timezone.localdate()

    # Clients with bookings in last 30 days
    active_client_ids = Booking.objects.filter(
        scheduled_date__gte=today - timedelta(days=30)
    ).values_list('client_id', flat=True).distinct()
    active_clients = Client.objects.filter(id__in=active_client_ids).select_related('user')

    # Clients with bookings this week
    weekly_client_ids = Booking.objects.filter(
        scheduled_date__gte=today,
        scheduled_date__lte=today + timedelta(days=7)
    ).values_list('client_id', flat=True).distinct()
    clients_with_bookings_this_week = Client.objects.filter(id__in=weekly_client_ids).select_related('user')

    # Clients with any active package
    packaged_client_ids = ClientPackage.objects.filter(
        status='active',
        expiry_date__gte=today,
    ).values_list('client_id', flat=True).distinct()
    packaged_clients_count = Client.objects.filter(
        id__in=packaged_client_ids,
        user__email__isnull=False,
    ).exclude(user__email='').count()

    # Active packages with their active client counts (for per-package targeting)
    active_packages = Package.objects.filter(is_active=True).order_by('package_type', 'name')
    packages_with_counts = []
    for pkg in active_packages:
        count = ClientPackage.objects.filter(
            package=pkg,
            status='active',
            expiry_date__gte=today,
        ).values('client_id').distinct().count()
        packages_with_counts.append((pkg, count))

    # Contact list counts
    all_contacts     = ContactParent.objects.exclude(email='').order_by('last_name', 'first_name', 'email')
    unregistered_contacts = all_contacts.filter(client__isnull=True)
    contact_sources  = ContactParent.SOURCE_CHOICES

    # Per-source counts
    from django.db.models import Count as DjCount
    contacts_by_source = {
        row['source']: row['n']
        for row in ContactParent.objects.exclude(email='').values('source').annotate(n=DjCount('id'))
    }

    context = {
        'all_clients_count': all_clients.count(),
        'all_coaches_count': all_coaches.count(),
        'all_users_count': all_users.count(),
        'active_clients_count': active_clients.count(),
        'clients_with_bookings_this_week_count': clients_with_bookings_this_week.count(),
        'packaged_clients_count': packaged_clients_count,
        'packages_with_counts': packages_with_counts,
        'all_clients': all_clients,
        'all_coaches': all_coaches,
        # contact list
        'all_contacts': all_contacts,
        'all_contacts_count': all_contacts.count(),
        'unregistered_contacts_count': unregistered_contacts.count(),
        'contact_sources': contact_sources,
        'contacts_by_source': contacts_by_source,
        'recent_broadcasts': EmailBroadcast.objects.order_by('-created_at')[:10],
    }
    return render(request, 'owner/notifications.html', context)


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_send_notification(request):
    """Send notifications to selected recipients with optional attachments and images."""
    import logging
    logger = logging.getLogger(__name__)

    recipient_group = request.POST.get('recipient_group', '')
    subject = request.POST.get('subject', '').strip().replace('\n', '').replace('\r', '')
    message = request.POST.get('message', '').strip()
    individual_emails = request.POST.getlist('individual_emails')
    send_as_html = request.POST.get('send_as_html') == 'on'

    # Handle file uploads — filter out zero-byte entries (mobile browsers often submit empty file fields)
    attachments = [f for f in request.FILES.getlist('attachments') if f.size > 0]
    inline_image = request.FILES.get('inline_image')
    if inline_image and inline_image.size == 0:
        inline_image = None

    if not subject or not message:
        messages.error(request, 'Please provide both subject and message.')
        return redirect('owner_notifications')

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@atletasperformancecenter.com')

    try:
        if recipient_group == 'individual' and not individual_emails:
            messages.error(request, 'No recipients specified for individual send.')
            return redirect('owner_notifications')

        # Save uploaded files to disk so Celery can read them after the HTTP request ends.
        import uuid, os
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'email_attachments')
        os.makedirs(upload_dir, exist_ok=True)

        saved_attachments = []
        for att in attachments:
            safe_name = f"{uuid.uuid4().hex}_{att.name}"
            save_path = os.path.join(upload_dir, safe_name)
            with open(save_path, 'wb') as fh:
                for chunk in att.chunks():
                    fh.write(chunk)
            saved_attachments.append({'path': save_path, 'name': att.name, 'content_type': att.content_type})

        saved_inline_image = None
        if inline_image:
            safe_name = f"{uuid.uuid4().hex}_{inline_image.name}"
            save_path = os.path.join(upload_dir, safe_name)
            with open(save_path, 'wb') as fh:
                for chunk in inline_image.chunks():
                    fh.write(chunk)
            saved_inline_image = {'path': save_path, 'name': inline_image.name, 'content_type': inline_image.content_type}

        # Always dispatch to Celery — never block the HTTP request on email sends.
        from clients.models import EmailBroadcast
        from clients.tasks import send_bulk_email_task, run_task
        broadcast = EmailBroadcast.objects.create(
            recipient_group=recipient_group,
            subject=subject,
            sent_by=request.user,
        )
        run_task(send_bulk_email_task,
                 broadcast_id=broadcast.id,
                 recipient_group=recipient_group,
                 subject=subject,
                 message=message,
                 from_email=from_email,
                 send_as_html=send_as_html,
                 extra_params={
                     'package_id': request.POST.get('package_id', ''),
                     'contact_source': request.POST.get('contact_source', ''),
                     'individual_emails': list(individual_emails),
                     'attachments': saved_attachments,
                     'inline_image': saved_inline_image,
                 })
        messages.success(request,
            'Email queued for sending. Check "Recent Sends" below for delivery results.')

    except Exception as e:
        logger.error(f'owner_send_notification error: {e}', exc_info=True)
        messages.error(request, f'Error preparing email: {str(e)}')

    return redirect('owner_notifications')


def _resolve_recipient_emails(recipient_group, package_id='', contact_source='', individual_emails=None):
    """Resolve a recipient group name to a set of email addresses."""
    from bookings.models import Booking
    recipients = set()
    today = timezone.localdate()

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

    elif recipient_group == 'packaged_clients':
        from clients.models import ClientPackage
        packaged_ids = ClientPackage.objects.filter(
            status='active',
            expiry_date__gte=today,
        ).values_list('client_id', flat=True).distinct()
        emails = Client.objects.filter(
            id__in=packaged_ids,
            user__email__isnull=False,
        ).exclude(user__email='').values_list('user__email', flat=True)
        recipients.update(emails)

    elif recipient_group == 'package_specific':
        from clients.models import ClientPackage
        if package_id:
            packaged_ids = ClientPackage.objects.filter(
                package_id=package_id,
                status='active',
                expiry_date__gte=today,
            ).values_list('client_id', flat=True).distinct()
            emails = Client.objects.filter(
                id__in=packaged_ids,
                user__email__isnull=False,
            ).exclude(user__email='').values_list('user__email', flat=True)
            recipients.update(emails)

    elif recipient_group == 'contacts_all':
        from clients.models import ContactParent
        emails = ContactParent.objects.exclude(email='').values_list('email', flat=True)
        recipients.update(emails)

    elif recipient_group == 'contacts_unregistered':
        from clients.models import ContactParent
        emails = ContactParent.objects.filter(
            client__isnull=True
        ).exclude(email='').values_list('email', flat=True)
        recipients.update(emails)

    elif recipient_group == 'contacts_by_source':
        from clients.models import ContactParent
        if contact_source:
            emails = ContactParent.objects.filter(
                source=contact_source
            ).exclude(email='').values_list('email', flat=True)
            recipients.update(emails)

    elif recipient_group == 'individual':
        if individual_emails:
            recipients.update(individual_emails)

    return recipients


def _build_html_email(html_message, site_url):
    """Return branded APC HTML email string."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif; line-height: 1.6; color: #333333; background-color: #f5f5f5; margin: 0; padding: 0; }}
    .email-wrapper {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
    .email-header {{ background: linear-gradient(135deg, #1a1a1a 0%, #2c3e50 100%); padding: 30px; text-align: center; }}
    .email-header img {{ max-height: 60px; width: auto; }}
    .email-header h1 {{ color: #ffffff; margin: 12px 0 0 0; font-size: 22px; font-weight: 600; letter-spacing: 0.5px; }}
    .email-body {{ padding: 40px 30px; }}
    .email-body p {{ margin: 0 0 15px 0; color: #555555; }}
    .divider {{ border: none; border-top: 1px solid #eeeeee; margin: 30px 0; }}
    .signature {{ font-size: 14px; color: #444444; }}
    .signature strong {{ color: #1a1a1a; font-size: 15px; }}
    .signature .title {{ color: #888888; font-size: 13px; margin: 2px 0; }}
    .signature .contact {{ color: #888888; font-size: 13px; margin: 2px 0; }}
    .signature .contact a {{ color: #1a1a1a; text-decoration: none; }}
    .signature-bar {{ width: 40px; height: 3px; background-color: #D7FF00; margin: 10px 0; }}
    .email-footer {{ background-color: #1a1a1a; padding: 25px 30px; text-align: center; }}
    .email-footer p {{ color: #888888; font-size: 12px; margin: 4px 0; }}
    .email-footer a {{ color: #D7FF00; text-decoration: none; }}
    .footer-logo {{ color: #ffffff; font-size: 15px; font-weight: 700; letter-spacing: 1px; margin-bottom: 8px; }}
    @media only screen and (max-width: 600px) {{
        .email-body {{ padding: 25px 20px; }}
        .email-header {{ padding: 20px; }}
    }}
</style>
</head>
<body>
<div class="email-wrapper">
    <div class="email-header">
        <img src="{site_url}/static/img/apc-logo-yellow.png" alt="Atletas Performance Center" onerror="this.style.display='none'">
        <h1>Atletas Performance Center</h1>
    </div>
    <div class="email-body">
        {html_message}
        <hr class="divider">
        <div class="signature">
            <div class="signature-bar"></div>
            <strong>Atletas Performance Center</strong><br>
            <div class="title">High Performance &amp; Athletic Development</div>
            <div class="contact">📧 <a href="mailto:info@atletasperformancecenter.com">info@atletasperformancecenter.com</a></div>
            <div class="contact">🌐 <a href="{site_url}">{site_url.replace("https://", "")}</a></div>
        </div>
    </div>
    <div class="email-footer">
        <div class="footer-logo">APC</div>
        <p>
            <a href="https://www.instagram.com/atletasworld/" target="_blank">Instagram</a> &nbsp;|&nbsp;
            <a href="https://www.facebook.com/atletasworld/" target="_blank">Facebook</a>
        </p>
        <p style="margin-top: 8px;">
            <a href="{site_url}/portal/notifications/" style="color:#aaaaaa;font-size:11px;">Manage Notification Preferences</a>
        </p>
        <p style="margin-top: 12px; font-size: 11px; color: #555555;">
            &copy; 2026 Atletas Performance Center. All rights reserved.
        </p>
    </div>
</div>
</body>
</html>'''
