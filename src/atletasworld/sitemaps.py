from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticSitemap(Sitemap):
    priority = 0.9
    changefreq = "weekly"

    def items(self):
        return [
            'home',
            'programs',
            'faq',
            'book',
            'about',
            'contact',
            'terms',
            'privacy',
        ]

    def location(self, item):
        return reverse(item)


class CoachProfileSitemap(Sitemap):
    priority = 0.7
    changefreq = "monthly"

    def items(self):
        from coaches.models import Coach
        return Coach.objects.filter(is_active=True, profile_enabled=True)

    def location(self, coach):
        return reverse('coach_public_profile', args=[coach.slug])
