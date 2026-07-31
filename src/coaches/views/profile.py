from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.db import models
from coaches.models import Coach
from bookings.models import Booking
from ._auth import coach_required


@coach_required
def profile_ai_assist(request):
    """AI Assist endpoint for the coach profile editor (bio, philosophy, achievements)."""
    import requests as _requests
    from django.conf import settings as _settings

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    coach = request.coach
    if not coach.profile_enabled:
        return JsonResponse({'error': 'Profile not enabled.'}, status=403)

    action = request.POST.get('action', '')
    text = request.POST.get('text', '').strip()
    field = request.POST.get('field', 'bio')

    FIELD_LABELS = {
        'full_bio': 'full biography',
        'coaching_philosophy': 'coaching philosophy',
        'achievements': 'achievements and career highlights',
        'tagline': 'tagline',
    }
    field_label = FIELD_LABELS.get(field, field)

    PROMPTS = {
        'draft': (
            f"You are a youth soccer coach at Atletas Performance Center (APC), an elite academy "
            f"in Overland Park, Kansas City. Write a professional coach {field_label}.\n\n"
            f"Requirements:\n"
            f"- Plain text only, no HTML or markdown\n"
            f"- Confident, warm, professional tone\n"
            f"- Under 150 words\n"
            f"- Write in first person\n"
            f"Context provided by the coach: {text if text else 'none'}\n\n"
            f"Return ONLY the text."
        ),
        'improve': (
            f"Improve the following coach {field_label} to be more compelling and professional. "
            f"Keep the same approximate length and first-person voice. Plain text only.\n\n"
            f"{field_label.capitalize()}:\n{text}\n\n"
            f"Return ONLY the improved text."
        ),
        'shorten': (
            f"Shorten the following coach {field_label} to under 80 words. "
            f"Keep the key points and first-person voice. Plain text only.\n\n"
            f"{field_label.capitalize()}:\n{text}\n\n"
            f"Return ONLY the shortened text."
        ),
        'grammar': (
            f"Fix the spelling, grammar, and punctuation of the following coach {field_label}. "
            f"Keep the meaning, length, and voice identical. Plain text only.\n\n"
            f"{field_label.capitalize()}:\n{text}\n\n"
            f"Return ONLY the corrected text."
        ),
    }

    prompt = PROMPTS.get(action)
    if not prompt:
        return JsonResponse({'error': 'Invalid action.'}, status=400)

    if action != 'draft' and not text:
        return JsonResponse({'error': 'Text is empty — nothing to improve.'}, status=400)

    ollama_url = getattr(_settings, 'OLLAMA_BASE_URL', 'http://192.168.1.70:11434')
    model = getattr(_settings, 'OLLAMA_MODEL', 'qwen3:8b-32k')

    try:
        resp = _requests.post(
            f'{ollama_url}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False, 'options': {'temperature': 0.6}},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json().get('response', '').strip()
        return JsonResponse({'result': result})
    except _requests.exceptions.Timeout:
        return JsonResponse({'error': 'AI request timed out. Try again.'}, status=504)
    except Exception as e:
        return JsonResponse({'error': f'AI unavailable: {str(e)}'}, status=503)


@coach_required
def availability(request):
    """Coach availability calendar using Toast UI Calendar."""
    coach = request.coach
    context = {
        'coach': coach,
    }
    return render(request, 'coaches/availability.html', context)


@coach_required
def edit_profile(request):
    """Coach profile edit page - only accessible if profile_enabled."""
    coach = request.coach

    profile_locked = not coach.profile_enabled

    if request.method == 'POST':
        # Update coach profile fields (only the coach-editable fields)
        coach.tagline = request.POST.get('tagline', '')[:200]
        coach.full_bio = request.POST.get('full_bio', '')
        coach.experience_years = int(request.POST.get('experience_years', 0) or 0)
        coach.coaching_philosophy = request.POST.get('coaching_philosophy', '')
        coach.achievements = request.POST.get('achievements', '')

        # Social links
        coach.instagram_url = request.POST.get('instagram_url', '')
        coach.facebook_url = request.POST.get('facebook_url', '')
        coach.twitter_url = request.POST.get('twitter_url', '')
        coach.linkedin_url = request.POST.get('linkedin_url', '')
        coach.youtube_url = request.POST.get('youtube_url', '')
        coach.personal_website = request.POST.get('personal_website', '')

        # Handle photo upload
        if 'photo' in request.FILES:
            coach.photo = request.FILES['photo']

        # Handle gallery images
        if 'gallery_image_1' in request.FILES:
            coach.gallery_image_1 = request.FILES['gallery_image_1']
        if 'gallery_image_2' in request.FILES:
            coach.gallery_image_2 = request.FILES['gallery_image_2']
        if 'gallery_image_3' in request.FILES:
            coach.gallery_image_3 = request.FILES['gallery_image_3']

        # Clear gallery images if requested
        if request.POST.get('clear_gallery_1'):
            coach.gallery_image_1 = None
        if request.POST.get('clear_gallery_2'):
            coach.gallery_image_2 = None
        if request.POST.get('clear_gallery_3'):
            coach.gallery_image_3 = None

        coach.save()
        messages.success(request, 'Your profile has been updated!')
        return redirect('coaches:edit_profile')

    context = {
        'coach': coach,
        'profile_locked': profile_locked,
    }
    return render(request, 'coaches/edit_profile.html', context)


def coach_public_profile(request, slug):
    """Public coach profile page."""
    coach = get_object_or_404(Coach, slug=slug, is_active=True, profile_enabled=True)

    # Get review stats if available
    from reviews.models import Review
    reviews = Review.objects.filter(coach=coach, is_approved=True).order_by('-created_at')[:5]
    review_stats = Review.objects.filter(coach=coach, is_approved=True).aggregate(
        avg_rating=models.Avg('rating'),
        total_reviews=models.Count('id')
    )

    # Get session count — floor to coach's display setting to account for pre-platform history
    db_sessions = Booking.objects.filter(coach=coach, status='completed').count()
    total_sessions = max(db_sessions, coach.sessions_display_floor)

    # Parse specializations
    specializations = []
    if coach.specializations:
        specializations = [s.strip() for s in coach.specializations.split(',') if s.strip()]

    context = {
        'coach': coach,
        'reviews': reviews,
        'review_stats': review_stats,
        'total_sessions': total_sessions,
        'specializations': specializations,
    }
    return render(request, 'coaches/public_profile.html', context)
