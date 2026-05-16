from django.contrib import admin
from .models import BlogPost


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'is_published', 'is_featured', 'published_at']
    list_filter = ['category', 'is_published', 'is_featured']
    list_editable = ['is_published', 'is_featured']
    prepopulated_fields = {'slug': ('title',)}
    search_fields = ['title', 'excerpt', 'body']
    date_hierarchy = 'published_at'
    fieldsets = [
        (None, {'fields': ['title', 'slug', 'category', 'excerpt', 'body', 'image']}),
        ('Publishing', {'fields': ['is_published', 'is_featured', 'published_at']}),
        ('SEO', {'fields': ['og_description'], 'classes': ['collapse']}),
    ]
