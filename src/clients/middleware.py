"""
Middleware for clients app.
"""


class ReferralCodeMiddleware:
    """
    Captures ?ref=CODE from URL query parameters and stores in session.

    The code is retrieved later during signup by the track_referral_on_signup signal handler.
    Only captures for unauthenticated users (new signups).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only capture referral code for anonymous users
        ref_code = request.GET.get('ref')
        if ref_code and not request.user.is_authenticated:
            # Store in session for retrieval during signup
            request.session['referral_code'] = ref_code.strip().upper()

        response = self.get_response(request)
        return response
