def user_roles(request):
    """Inject user portal role flags for multi-role switcher."""
    if not request.user.is_authenticated:
        return {}
    groups = set(request.user.groups.values_list('name', flat=True))
    is_owner = request.user.is_staff or request.user.is_superuser or 'Owner' in groups
    is_coach = 'Coach' in groups
    is_client = 'Client' in groups
    multi = sum([is_owner, is_coach, is_client]) > 1
    return {
        'role_is_owner': is_owner,
        'role_is_coach': is_coach,
        'role_is_client': is_client,
        'role_multi': multi,
    }


def pending_field_rentals(request):
    """Inject pending field rental count for owner portal nav badge."""
    if not request.user.is_authenticated:
        return {}
    if not request.user.groups.filter(name='Owner').exists():
        return {}
    try:
        from clients.models import FieldRentalSlot
        return {'pending_field_count': FieldRentalSlot.objects.filter(status='pending_approval').count()}
    except Exception:
        return {}
