"""
Management command: send a test email using the configured email backend.

Usage:
    python manage.py send_test_email slach80@gmail.com
    python manage.py send_test_email slach80@gmail.com --template booking_confirmation

Useful for verifying:
  - SMTP credentials work
  - Email formatting/layout looks correct
  - Social links and logos render
  - Notification preferences flow is wired up
"""
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings


SAMPLE_CONTEXTS = {
    'booking_confirmation': {
        'subject': '🎉 [TEST] Booking Confirmed — APC',
        'template': 'emails/booking_confirmation.html',
        'context': {
            'client_name': 'Test Client',
            'session_type': 'Serie A Elite Scouts — U13',
            'session_format': 'Group Session',
            'session_duration': '90 min',
            'coach_name': 'Mirko Trapletti',
            'date': 'Sunday, May 25, 2026',
            'time': '4:00 PM',
            'location': 'APC Indoor Facility',
            'player_name': 'Tommy Smith',
            'package_name': 'Basic 4 Sessions',
            'sessions_remaining': 3,
            'payment_method': 'package',
            'payment_confirmed': False,
            'amount_paid': None,
            'booking_link': f"{settings.SITE_URL}/portal/bookings/",
        },
    },
    'base': {
        'subject': '🔧 [TEST] APC Email — Base Template Check',
        'template': None,  # inline content
        'context': {},
    },
}


class Command(BaseCommand):
    help = 'Send a test email to verify email delivery and formatting.'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='Recipient email address')
        parser.add_argument(
            '--template',
            type=str,
            default='base',
            choices=list(SAMPLE_CONTEXTS.keys()),
            help='Which email template to test (default: base)',
        )

    def handle(self, *args, **options):
        to_email = options['email']
        template_key = options['template']
        config = SAMPLE_CONTEXTS[template_key]

        self.stdout.write(f"Sending test email to {to_email} ...")
        self.stdout.write(f"Email backend: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"Template: {template_key}")

        # Build content
        if config['template']:
            ctx = config['context'].copy()
            ctx.update({
                'site_url': getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com'),
                'current_year': timezone.now().year,
            })
            html_content = render_to_string(config['template'], ctx)
            # Wrap in base email layout
            wrapped = render_to_string('emails/base_email.html', {
                'subject': config['subject'],
                'client_name': ctx.get('client_name', 'there'),
                'content': html_content,
                'site_url': ctx['site_url'],
                'current_year': ctx['current_year'],
            })
        else:
            # Minimal inline test using base template
            site_url = getattr(settings, 'SITE_URL', 'https://atletasperformancecenter.com')
            wrapped = render_to_string('emails/base_email.html', {
                'subject': config['subject'],
                'client_name': 'Test',
                'content': (
                    '<h2>✅ Email System Working</h2>'
                    '<p>This is a test email from Atletas Performance Center.</p>'
                    '<p>If you can read this, the email backend is configured correctly.</p>'
                    '<div class="highlight-box">'
                    '<div class="label">Sent at</div>'
                    f'<div class="value">{timezone.now().strftime("%Y-%m-%d %H:%M:%S %Z")}</div>'
                    '</div>'
                    '<div class="highlight-box">'
                    '<div class="label">Backend</div>'
                    f'<div class="value">{settings.EMAIL_BACKEND}</div>'
                    '</div>'
                ),
                'site_url': site_url,
                'current_year': timezone.now().year,
            })

        text_content = 'This is a test email from Atletas Performance Center. Please view in HTML.'

        try:
            msg = EmailMultiAlternatives(
                subject=config['subject'],
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
            )
            msg.attach_alternative(wrapped, 'text/html')
            msg.send()
            self.stdout.write(self.style.SUCCESS(
                f"✓ Test email sent to {to_email}"
            ))
        except Exception as e:
            raise CommandError(f"Failed to send email: {e}")
