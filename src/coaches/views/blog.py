from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from coaches.models import Coach


@login_required
def coach_blog_posts(request):
    coach = get_object_or_404(Coach, user=request.user)
    from blog.models import BlogPost
    posts = BlogPost.objects.filter(author_coach=coach).order_by('-created_at') if hasattr(BlogPost, 'author_coach') else BlogPost.objects.none()
    # Fallback: show all posts if no author FK (owner sees all, coach sees drafts)
    posts = BlogPost.objects.all().order_by('-created_at')
    return render(request, 'coaches/blog_list.html', {'posts': posts, 'coach': coach})


@login_required
def coach_blog_submit(request):
    coach = get_object_or_404(Coach, user=request.user)
    from blog.models import BlogPost

    if request.method == 'POST':
        from django.utils.text import slugify
        title = request.POST.get('title', '').strip()
        post = BlogPost(
            title=title,
            slug=slugify(title),
            category=request.POST.get('category', 'general'),
            excerpt=request.POST.get('excerpt', '').strip(),
            body=request.POST.get('body', '').strip(),
            is_published=False,
        )
        if 'image' in request.FILES:
            post.image = request.FILES['image']
        post.save()
        from django.contrib import messages
        messages.success(request, f'Post submitted as draft: "{post.title}" — the owner will review and publish it.')
        return redirect('coaches:blog_posts')

    from blog.models import BlogPost
    return render(request, 'coaches/blog_submit.html', {
        'coach': coach,
        'categories': BlogPost.CATEGORY_CHOICES,
    })
