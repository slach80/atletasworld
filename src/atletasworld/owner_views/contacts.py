from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_contacts(request):
    """Imported contact registry — parents from past events with their players."""
    from clients.models import ContactParent, ContactPlayer
    from django.db.models import Count, Prefetch

    # Invite All — send registration invitation to all unregistered contacts with email
    if request.method == 'POST' and request.POST.get('action') == 'invite_all':
        from django.core.mail import send_mail
        from django.conf import settings as _s
        unregistered = ContactParent.objects.filter(client__isnull=True).exclude(email='').exclude(email__isnull=True)
        sent = 0
        signup_url = request.build_absolute_uri('/accounts/signup/')
        for contact in unregistered:
            try:
                send_mail(
                    subject='Join Atletas Performance Center — Create Your Account',
                    message=(
                        f"Hi {contact.first_name or 'there'},\n\n"
                        "We'd like to invite you to create your account at Atletas Performance Center so you can book sessions, "
                        "track your players' progress, and manage your family's training schedule online.\n\n"
                        f"Sign up here: {signup_url}\n\n"
                        "If you have any questions, reply to this email.\n\n"
                        "— Atletas Performance Center"
                    ),
                    from_email=_s.DEFAULT_FROM_EMAIL,
                    recipient_list=[contact.email],
                    fail_silently=True,
                )
                sent += 1
            except Exception:
                pass
        messages.success(request, f'Invitation sent to {sent} unregistered contact{"s" if sent != 1 else ""}.')
        return redirect('owner_contacts')

    search  = request.GET.get('q', '').strip()
    status  = request.GET.get('status', '')   # linked / unlinked
    source  = request.GET.get('source', '')

    qs = ContactParent.objects.prefetch_related('players').annotate(
        annotated_player_count=Count('players', distinct=True)
    ).order_by('last_name', 'first_name', 'email')

    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(phone__icontains=search) |
            Q(players__first_name__icontains=search) |
            Q(players__last_name__icontains=search)
        ).distinct()

    if status == 'linked':
        qs = qs.filter(client__isnull=False)
    elif status == 'unlinked':
        qs = qs.filter(client__isnull=True)

    if source:
        qs = qs.filter(source=source)

    total         = ContactParent.objects.count()
    linked_count  = ContactParent.objects.filter(client__isnull=False).count()
    player_count  = ContactPlayer.objects.count()

    context = {
        'contacts':      qs,
        'total':         total,
        'linked_count':  linked_count,
        'unlinked_count':total - linked_count,
        'player_count':  player_count,
        'search':        search,
        'status':        status,
        'source_filter': source,
        'source_choices':ContactParent.SOURCE_CHOICES,
    }
    return render(request, 'owner/contacts.html', context)


@login_required
@user_passes_test(is_owner)
def owner_contact_edit(request, pk):
    """Edit a ContactParent and all their associated players."""
    from clients.models import ContactParent, ContactPlayer
    contact = get_object_or_404(ContactParent, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action', 'save_parent')

        if action == 'save_parent':
            contact.first_name = request.POST.get('first_name', '').strip()
            contact.last_name  = request.POST.get('last_name', '').strip()
            contact.email      = request.POST.get('email', '').strip()
            contact.phone      = request.POST.get('phone', '').strip()
            contact.source     = request.POST.get('source', contact.source)
            contact.notes      = request.POST.get('notes', '').strip()
            contact.save()
            messages.success(request, 'Contact updated.')

        elif action == 'save_player':
            player_id = request.POST.get('player_id')
            if player_id:
                player = get_object_or_404(ContactPlayer, pk=player_id, parent=contact)
            else:
                player = ContactPlayer(parent=contact)
            player.first_name  = request.POST.get('first_name', '').strip()
            player.last_name   = request.POST.get('last_name', '').strip()
            by = request.POST.get('birth_year', '').strip()
            player.birth_year  = int(by) if by.isdigit() else None
            player.sex         = request.POST.get('sex', '')
            player.club_team   = request.POST.get('club_team', '').strip()
            player.position    = request.POST.get('position', '').strip()
            player.notes       = request.POST.get('notes', '').strip()
            player.save()
            messages.success(request, f'Player {"added" if not player_id else "updated"}.')

        elif action == 'delete_player':
            player_id = request.POST.get('player_id')
            ContactPlayer.objects.filter(pk=player_id, parent=contact).delete()
            messages.success(request, 'Player removed.')

        elif action == 'delete_contact':
            contact.delete()
            messages.success(request, 'Contact deleted.')
            return redirect('owner_contacts')

        return redirect('owner_contact_edit', pk=contact.pk)

    context = {
        'contact':  contact,
        'players':  contact.players.order_by('last_name', 'first_name'),
        'source_choices': ContactParent.SOURCE_CHOICES,
        'sex_choices': ContactPlayer.SEX_CHOICES,
    }
    return render(request, 'owner/contact_edit.html', context)
