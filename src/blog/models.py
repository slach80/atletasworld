from django.db import models
from django.utils.text import slugify


class BlogPost(models.Model):
    CATEGORY_CHOICES = [
        ('age_groups', 'Age Groups & Development'),
        ('programs', 'Programs & Training'),
        ('select_team', 'Select Team'),
        ('authority', 'Coach Stories'),
        ('general', 'General'),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    excerpt = models.TextField(max_length=300, help_text='1-2 sentences shown in list view')
    body = models.TextField(help_text='HTML content')
    image = models.ImageField(upload_to='blog/', blank=True, null=True)
    og_description = models.CharField(max_length=160, blank=True, help_text='Overrides excerpt for meta description')
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False, help_text='Show as the large featured post at top of list')
    published_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('blog_detail', args=[self.slug])

    @property
    def meta_description(self):
        return self.og_description or self.excerpt

    @property
    def category_label(self):
        return dict(self.CATEGORY_CHOICES).get(self.category, '')
