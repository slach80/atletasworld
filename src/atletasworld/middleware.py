from django.shortcuts import redirect
from django.urls import reverse


# URLs that are always accessible — never redirect here
_EXEMPT_PREFIXES = (
    '/accounts/',
    '/admin/',
    '/static/',
    '/media/',
    '/__debug__/',
)

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' cdn.tailwindcss.com cdn.jsdelivr.net js.stripe.com; "
    "style-src 'self' 'unsafe-inline' fonts.googleapis.com cdn.tailwindcss.com cdn.jsdelivr.net; "
    "font-src 'self' fonts.gstatic.com cdn.jsdelivr.net data:; "
    "img-src 'self' data: blob: *.stripe.com *.squarespace-cdn.com images.unsplash.com; "
    "frame-src js.stripe.com *.stripe.com; "
    "connect-src 'self' *.stripe.com api.stripe.com; "
    "object-src 'none'; "
    "base-uri 'self';"
)


class SecurityHeadersMiddleware:
    """Adds Content-Security-Policy and Referrer-Policy to every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Content-Security-Policy'] = _CSP
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response


class PasswordExpiryMiddleware:
    """
    Redirects authenticated users to the password change page when their
    password is older than UserPasswordExpiry.PASSWORD_EXPIRY_DAYS (365 days).

    Existing users were seeded with password_changed_at = now() - 6 months,
    giving them a 6-month grace period before their first forced change.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if not any(request.path.startswith(p) for p in _EXEMPT_PREFIXES):
                try:
                    from clients.models import UserPasswordExpiry
                    expiry = UserPasswordExpiry.objects.get(user=request.user)
                    if expiry.is_expired:
                        return redirect(
                            f"{reverse('account_change_password')}?next={request.path}&expired=1"
                        )
                except UserPasswordExpiry.DoesNotExist:
                    # New user with no record — create one starting now (full year)
                    from clients.models import UserPasswordExpiry
                    from django.utils import timezone
                    UserPasswordExpiry.objects.create(
                        user=request.user,
                        password_changed_at=timezone.now()
                    )

        return self.get_response(request)
