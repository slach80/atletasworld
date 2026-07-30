def is_owner(user):
    """Check if user is staff/superuser or in Owner group."""
    return user.is_staff or user.is_superuser or user.groups.filter(name='Owner').exists()
