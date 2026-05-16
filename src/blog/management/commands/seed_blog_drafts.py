from django.core.management.base import BaseCommand
from blog.models import BlogPost

DRAFTS = [
    {
        'title': 'What Happens at an APC Trial Session? (A Parent\'s Guide)',
        'slug': 'apc-trial-session-what-to-expect',
        'category': 'programs',
        'excerpt': (
            'Your child has been invited to an APC trial session — or you\'re considering signing up for one. '
            'Here\'s exactly what happens from the moment you arrive: duration, format, drills, and how our '
            'coaches evaluate players.'
        ),
        'body': '<p><!-- TODO: Fill in from owner. Cover: duration, warm-up format, technical drills used, small-sided game, evaluation criteria, what coaches are watching for, what happens after, how to prepare. --></p>',
        'og_description': (
            'Wondering what an APC trial session looks like? Here\'s what to expect: duration, drills, '
            'evaluation criteria, and how to prepare your athlete.'
        ),
    },
    {
        'title': 'APC Select Team Tryouts: What We\'re Actually Looking For',
        'slug': 'apc-select-team-tryouts-evaluation-criteria',
        'category': 'select_team',
        'excerpt': (
            'Making the APC Select Team isn\'t just about who\'s the most skilled player on the day. '
            'Here\'s an honest breakdown of the specific qualities our coaches evaluate during tryouts — '
            'and what separates players who earn a spot from those who don\'t.'
        ),
        'body': '<p><!-- TODO: Fill in from owner. Cover: coachability, attitude, work rate, positioning IQ, how skill is evaluated vs. other factors, age group differences (U10 vs U14 vs U16), what happens if a player doesn\'t make it, re-tryout policy. --></p>',
        'og_description': (
            'APC Select Team tryouts evaluate more than raw skill. Here\'s what our coaches are specifically '
            'looking for — and what gives players the best chance of earning a spot.'
        ),
    },
    {
        'title': 'Elite Sunday Class vs. Weekly Training: Which Is Right for Your Athlete?',
        'slug': 'elite-sunday-class-vs-weekly-training',
        'category': 'programs',
        'excerpt': (
            'APC\'s Elite Sunday Class isn\'t just training on a different day — it\'s a different format, '
            'intensity level, and player profile entirely. Here\'s how to decide which program fits '
            'your athlete right now.'
        ),
        'body': '<p><!-- TODO: Fill in from owner. Cover: what makes Sunday class different (intensity, format, who attends), ideal player profile for Sunday vs weekly, can players do both, age groups, pricing difference if any, typical session structure for each. --></p>',
        'og_description': (
            'APC\'s Elite Sunday Class and weekly training sessions serve different player profiles. '
            'Here\'s how to decide which is the right fit for your athlete.'
        ),
    },
    {
        'title': 'Mirko Trapletti: The Italian Academy Method and What It Means for Kansas City Players',
        'slug': 'mirko-trapletti-italian-academy-coaching-kansas-city',
        'category': 'authority',
        'excerpt': (
            'Mirko Trapletti brought something rare to Kansas City: a coaching philosophy forged inside '
            'the Italian professional academy system. Here\'s his background, his playing career, and '
            'why the Italian model produces technically superior players.'
        ),
        'body': '<p><!-- TODO: Fill in from owner. Cover: which Italian clubs Mirko trained/coached at, his playing career (positions, levels), how many years coaching, specific aspects of Italian academy methodology he uses at APC, difference between Italian and American youth development approach, what APC players gain from this background. --></p>',
        'og_description': (
            'Mirko Trapletti\'s coaching philosophy comes from inside the Italian professional academy system. '
            'Here\'s his background and what that means for players training at APC in Kansas City.'
        ),
    },
]


class Command(BaseCommand):
    help = 'Seed 4 placeholder blog draft posts (unpublished)'

    def handle(self, *args, **options):
        for data in DRAFTS:
            post, created = BlogPost.objects.update_or_create(
                slug=data['slug'],
                defaults={
                    'title': data['title'],
                    'category': data['category'],
                    'excerpt': data['excerpt'],
                    'body': data['body'],
                    'og_description': data['og_description'],
                    'is_featured': False,
                    'is_published': False,
                    'published_at': None,
                }
            )
            verb = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{verb} (draft): {post.title}'))

        self.stdout.write(self.style.WARNING(
            '\nAll 4 posts created as UNPUBLISHED drafts.'
            '\nEdit and publish at: https://atletasperformancecenter.com/admin/blog/blogpost/'
        ))
