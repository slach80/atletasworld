from django.shortcuts import get_object_or_404, render
from .models import BlogPost


def blog_list(request):
    posts = BlogPost.objects.filter(is_published=True)
    featured = posts.filter(is_featured=True).first()
    rest = posts.exclude(pk=featured.pk) if featured else posts
    return render(request, 'blog/list.html', {
        'featured': featured,
        'posts': rest,
    })


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    related = BlogPost.objects.filter(
        is_published=True, category=post.category
    ).exclude(pk=post.pk)[:3]
    return render(request, 'blog/detail.html', {
        'post': post,
        'related': related,
    })
