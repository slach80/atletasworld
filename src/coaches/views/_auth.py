from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect
from coaches.models import Coach


def coach_required(view_func):
    """Decorator to ensure user is a coach with proper group membership."""
    @login_required
    def wrapper(request, *args, **kwargs):
        # Check user is in Coach group — owners/staff are silently redirected (no error banner)
        if not request.user.groups.filter(name='Coach').exists():
            if not (request.user.is_staff or request.user.is_superuser or
                    request.user.groups.filter(name='Owner').exists()):
                messages.error(request, 'You do not have coach access.')
            return redirect('home')

        # Get associated Coach profile
        try:
            request.coach = Coach.objects.get(user=request.user)
            if not request.coach.is_active:
                messages.error(request, 'Your coach account is not active.')
                return redirect('home')
        except Coach.DoesNotExist:
            messages.error(request, 'Coach profile not found.')
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper
