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
