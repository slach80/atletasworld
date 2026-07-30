from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from ._auth import is_owner


@login_required
@user_passes_test(is_owner)
def owner_blog_list(request):
    from blog.models import BlogPost
    posts = BlogPost.objects.all().order_by('-created_at')
    return render(request, 'owner/blog_list.html', {'posts': posts})


@login_required
@user_passes_test(is_owner)
def owner_blog_edit(request, pk=None):
    from blog.models import BlogPost
    post = get_object_or_404(BlogPost, pk=pk) if pk else None

    if request.method == 'POST':
        data = request.POST
        if post is None:
            post = BlogPost()
        post.title = data.get('title', '').strip()
        if not post.slug:
            from django.utils.text import slugify
            post.slug = slugify(post.title)
        post.category = data.get('category', 'general')
        post.excerpt = data.get('excerpt', '').strip()
        post.body = data.get('body', '').strip()
        post.og_description = data.get('og_description', '').strip()
        post.is_featured = 'is_featured' in data
        was_unpublished = not post.is_published
        post.is_published = 'is_published' in data
        if post.is_published and was_unpublished and not post.published_at:
            post.published_at = timezone.now()
        if 'image' in request.FILES:
            post.image = request.FILES['image']
        post.save()
        messages.success(request, f'Post {"created" if pk is None else "updated"}: {post.title}')
        return redirect('owner_blog_list')

    return render(request, 'owner/blog_edit.html', {
        'post': post,
        'categories': BlogPost.CATEGORY_CHOICES,
    })


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_blog_delete(request, pk):
    from blog.models import BlogPost
    post = get_object_or_404(BlogPost, pk=pk)
    title = post.title
    post.delete()
    messages.success(request, f'Post deleted: {title}')
    return redirect('owner_blog_list')


@login_required
@user_passes_test(is_owner)
@require_POST
def owner_blog_toggle_publish(request, pk):
    from blog.models import BlogPost
    post = get_object_or_404(BlogPost, pk=pk)
    post.is_published = not post.is_published
    if post.is_published and not post.published_at:
        post.published_at = timezone.now()
    post.save()
    status = 'published' if post.is_published else 'unpublished'
    messages.success(request, f'"{post.title}" {status}.')
    return redirect('owner_blog_list')
