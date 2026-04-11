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
