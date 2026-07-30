from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_guide(request):
    """Owner how-to guide."""
    return render(request, 'owner/guide.html')
