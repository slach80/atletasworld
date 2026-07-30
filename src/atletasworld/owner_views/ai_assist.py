from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_blog_ai_assist(request):
    import json as _json
    import requests as _requests
    from django.conf import settings as _settings
    from django.http import JsonResponse, StreamingHttpResponse

    action = request.POST.get('action', '')
    title = request.POST.get('title', '').strip()
    category = request.POST.get('category', '')
    body = request.POST.get('body', '').strip()
    excerpt = request.POST.get('excerpt', '').strip()

    PROMPTS = {
        'generate': (
            f"You are a sports content writer for Atletas Performance Center (APC), "
            f"an elite youth soccer academy in Overland Park, Kansas City. "
            f"Write a complete, engaging blog post body in HTML format for the following:\n\n"
            f"Title: {title}\n"
            f"Category: {category}\n\n"
            f"Requirements:\n"
            f"- Use <h2> for section headings, <p> for paragraphs, <ul>/<li> for lists\n"
            f"- Write 400-600 words\n"
            f"- Tone: authoritative, encouraging, parent-friendly\n"
            f"- Include specific, practical advice relevant to youth soccer\n"
            f"- End with a brief call-to-action paragraph mentioning APC\n"
            f"- Return ONLY the HTML body content, no extra commentary"
        ),
        'improve': (
            f"You are a sports content editor. Improve the following blog post body for "
            f"Atletas Performance Center, an elite youth soccer academy in Kansas City. "
            f"Make it more engaging, clear, and compelling while preserving the original meaning and structure.\n\n"
            f"Title: {title}\n\n"
            f"Current body:\n{body}\n\n"
            f"Return ONLY the improved HTML body. Keep the same HTML structure."
        ),
        'excerpt': (
            f"Write a 1-2 sentence excerpt (max 280 characters) for this blog post. "
            f"It should hook the reader and make them want to read more. "
            f"Plain text only, no HTML.\n\n"
            f"Title: {title}\n\n"
            f"Body:\n{body[:2000]}\n\n"
            f"Return ONLY the excerpt text."
        ),
        'grammar': (
            f"Fix the grammar, spelling, and tone of the following blog post body. "
            f"Keep the HTML structure exactly as-is. "
            f"Make the tone consistent, professional, and parent-friendly. "
            f"Return ONLY the corrected HTML.\n\n{body}"
        ),
        'html_format': (
            f"Convert the following text into clean, well-structured HTML suitable for a blog post body. "
            f"Use <h2> for section headings, <p> for paragraphs, <ul>/<li> for bullet lists, "
            f"<ol>/<li> for numbered lists, <strong> for emphasis, <blockquote> for quotes. "
            f"Return ONLY the HTML, no markdown, no code fences.\n\n{body or excerpt or title}"
        ),
    }

    prompt = PROMPTS.get(action)
    if not prompt:
        return JsonResponse({'error': 'Invalid action'}, status=400)

    ollama_url = getattr(_settings, 'OLLAMA_BASE_URL', 'http://192.168.1.70:11434')
    model = getattr(_settings, 'OLLAMA_MODEL', 'qwen3:8b-32k')

    try:
        resp = _requests.post(
            f'{ollama_url}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False, 'options': {'temperature': 0.7}},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get('response', '').strip()
        # Strip any markdown code fences Ollama might add
        if result.startswith('```'):
            result = '\n'.join(result.split('\n')[1:])
        if result.endswith('```'):
            result = '\n'.join(result.split('\n')[:-1])
        return JsonResponse({'result': result})
    except _requests.exceptions.Timeout:
        return JsonResponse({'error': 'Ollama timed out — the model may be loading, try again in a moment.'}, status=504)
    except Exception as e:
        return JsonResponse({'error': f'AI assist unavailable: {str(e)}'}, status=503)


@login_required
@user_passes_test(is_owner)
def owner_naming_ai_assist(request):
    """AI Assist for package / session-type name and description fields."""
    import requests as _requests
    from django.conf import settings as _settings

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    action = request.POST.get('action', '')
    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    context_type = request.POST.get('context_type', 'package')  # 'package' or 'session'

    ctx = 'training package' if context_type == 'package' else 'session type'

    PROMPTS = {
        'suggest_name': (
            f"You are naming {ctx}s for Atletas Performance Center (APC), an elite youth soccer "
            f"academy in Overland Park, Kansas City. Suggest 5 clear, professional names for a "
            f"{ctx} with the following description or context:\n\n"
            f"{description or name or 'No context provided'}\n\n"
            f"Requirements:\n"
            f"- Short (2-5 words each)\n"
            f"- Professional and parent-friendly\n"
            f"- Consistent naming convention (e.g. 'Elite 8', 'Select Sunday', 'U13 Development')\n"
            f"- Return ONLY a numbered list of 5 names, nothing else"
        ),
        'write_description': (
            f"Write a short, clear description (2-3 sentences) for the following {ctx} at "
            f"Atletas Performance Center, an elite youth soccer academy in Kansas City.\n\n"
            f"Name: {name}\n"
            f"{'Current description: ' + description if description else ''}\n\n"
            f"Requirements:\n"
            f"- Plain text only\n"
            f"- Parent-friendly, clear, concise\n"
            f"- Mention who it's for and what they get\n"
            f"- Return ONLY the description text"
        ),
        'fix_description': (
            f"Fix the grammar, spelling, and clarity of this {ctx} description for "
            f"Atletas Performance Center. Keep the same meaning and length.\n\n"
            f"{description}\n\n"
            f"Return ONLY the corrected description."
        ),
    }

    prompt = PROMPTS.get(action)
    if not prompt:
        return JsonResponse({'error': 'Invalid action'}, status=400)

    if action == 'fix_description' and not description:
        return JsonResponse({'error': 'Description is empty — nothing to fix.'}, status=400)
    if action == 'write_description' and not name:
        return JsonResponse({'error': 'Enter a name first so AI knows what to describe.'}, status=400)

    ollama_url = getattr(_settings, 'OLLAMA_BASE_URL', 'http://192.168.1.70:11434')
    model = getattr(_settings, 'OLLAMA_MODEL', 'qwen3:8b-32k')

    try:
        resp = _requests.post(
            f'{ollama_url}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False, 'options': {'temperature': 0.7}},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json().get('response', '').strip()
        return JsonResponse({'result': result})
    except _requests.exceptions.Timeout:
        return JsonResponse({'error': 'Ollama timed out — try again in a moment.'}, status=504)
    except Exception as e:
        return JsonResponse({'error': f'AI assist unavailable: {str(e)}'}, status=503)


@login_required
@user_passes_test(is_owner)
def owner_notification_ai_assist(request):
    """AI Assist for the owner notification composer (subject + message)."""
    import requests as _requests
    from django.conf import settings as _settings

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    action = request.POST.get('action', '')
    subject = request.POST.get('subject', '').strip()
    message = request.POST.get('message', '').strip()

    PROMPTS = {
        'draft': (
            f"You are writing a bulk email for Atletas Performance Center (APC), an elite youth "
            f"soccer academy in Overland Park, Kansas City. Write a clear, professional email body "
            f"based on the subject line below.\n\n"
            f"Subject: {subject}\n\n"
            f"Requirements:\n"
            f"- Plain text, no HTML\n"
            f"- Warm but professional tone\n"
            f"- 3-5 short paragraphs\n"
            f"- Leave [brackets] where specific details should be filled in\n"
            f"- End with 'Best regards,\\nAtletas Performance Center Team'\n"
            f"Return ONLY the email body."
        ),
        'subject': (
            f"Write a clear, compelling email subject line for the following message body. "
            f"Max 60 characters. Plain text only.\n\n"
            f"Message:\n{message[:1000]}\n\n"
            f"Return ONLY the subject line text."
        ),
        'grammar': (
            f"Fix the grammar, spelling, and tone of the following email for Atletas Performance "
            f"Center. Keep the same meaning and structure. Plain text only.\n\n"
            f"{message}\n\n"
            f"Return ONLY the corrected email body."
        ),
        'shorten': (
            f"Shorten the following email to 2-3 short paragraphs while keeping the key information. "
            f"Plain text only.\n\n"
            f"{message}\n\n"
            f"Return ONLY the shortened email body."
        ),
    }

    prompt = PROMPTS.get(action)
    if not prompt:
        return JsonResponse({'error': 'Invalid action'}, status=400)

    if action == 'draft' and not subject:
        return JsonResponse({'error': 'Enter a subject line first.'}, status=400)
    if action in ('grammar', 'shorten', 'subject') and not message:
        return JsonResponse({'error': 'Message is empty — nothing to improve.'}, status=400)

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
        return JsonResponse({'error': 'Ollama timed out — try again in a moment.'}, status=504)
    except Exception as e:
        return JsonResponse({'error': f'AI assist unavailable: {str(e)}'}, status=503)
