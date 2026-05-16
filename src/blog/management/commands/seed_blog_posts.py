from django.core.management.base import BaseCommand
from django.utils import timezone
from blog.models import BlogPost


POSTS = [
    {
        'title': 'From Kansas City to the World Stage: What Roger Espinoza\'s Career Teaches Young Athletes',
        'slug': 'roger-espinoza-career-lessons-youth-soccer',
        'category': 'authority',
        'is_featured': True,
        'excerpt': (
            'Roger Espinoza grew up in Honduras, won the FA Cup with Wigan Athletic, and spent 14 seasons '
            'in MLS with Sporting KC — now he\'s coaching the next generation right here in Overland Park. '
            'Here\'s what his journey teaches young players about elite development.'
        ),
        'body': '''
<p>Most youth soccer players dream of going pro. Very few understand what that journey actually looks like from the inside. Roger Espinoza is one of the rare coaches who can tell them — not from a book, but from 20 years of living it.</p>

<p>Roger grew up in Honduras playing street soccer before earning a scholarship to the University of Akron, where he developed under one of the country's top collegiate programs. From there, he was drafted into MLS and went on to become one of Sporting Kansas City's most recognizable players — a relentless midfielder known for his engine, his work rate, and his ability to win the ball in any situation.</p>

<h2>The FA Cup Moment</h2>

<p>On May 11, 2013, Roger scored the decisive goal in Wigan Athletic's FA Cup Final victory over Manchester City — one of the biggest upsets in Cup history. It wasn't a fluke. It was the product of everything he'd built: tactical discipline, physical fitness, and the mental composure to perform in front of 86,000 people at Wembley.</p>

<p>"That moment taught me that preparation is everything," Roger says. "You don't rise to the occasion. You fall to the level of your training."</p>

<h2>Two World Cups</h2>

<p>Roger represented Honduras in two FIFA World Cups — 2010 (South Africa) and 2014 (Brazil). Competing against the world's best players at that level requires more than talent. It requires the kind of physical conditioning, tactical intelligence, and mental resilience that only comes from years of deliberate training.</p>

<p>At APC, Roger brings that same standard to every session. Not to pressure young players — but to show them what's possible when they commit to the process.</p>

<h2>What Elite Development Actually Looks Like</h2>

<p>There's a misconception in youth sports that elite players are simply born with talent. Roger's career disproves this. He wasn't the fastest player on the field. He wasn't the most technically gifted as a teenager. What set him apart was his relentless work ethic, his coachability, and his willingness to keep improving even after reaching the top.</p>

<p>The lessons he passes on at APC aren't complicated:</p>

<ul>
<li><strong>First touch is everything.</strong> At the professional level, you have fractions of a second. Train your touch every single day.</li>
<li><strong>Positioning beats pace.</strong> Read the game before the ball arrives. The best players are never surprised by the ball.</li>
<li><strong>Fitness is non-negotiable.</strong> In competitive soccer, technical quality disappears when you're tired. Build your engine first.</li>
<li><strong>Compete every session.</strong> The habit of competing — not winning, but competing fully — is what separates players who develop from players who plateau.</li>
</ul>

<h2>Why Kansas City</h2>

<p>After 14 seasons with Sporting KC, Roger chose to stay in Kansas City and give back to the community that supported him. APC represents his vision for what youth development should look like in this city: world-class coaching, a professional standard, and a genuine pathway for dedicated players.</p>

<p>"Kansas City has incredible soccer talent," he says. "My job is to help these kids discover how good they can be."</p>

<p>If your athlete trains with Roger at APC, they're getting something rare: a coach who has been exactly where they want to go — and knows the specific steps to get there.</p>
''',
        'og_description': (
            'Roger Espinoza won the FA Cup, played two World Cups, and spent 14 seasons at Sporting KC. '
            'Now he\'s coaching the next generation at APC in Overland Park. Here\'s what his career teaches young athletes.'
        ),
    },
    {
        'title': 'U8–U10 Soccer Development: The Fundamentals That Actually Matter',
        'slug': 'u8-u10-soccer-development-fundamentals',
        'category': 'age_groups',
        'is_featured': False,
        'excerpt': (
            'The U8–U10 window is the most important period in a young player\'s development — '
            'but most training programs focus on the wrong things. Here\'s what APC\'s coaches '
            'actually prioritize at this age, and why.'
        ),
        'body': '''
<p>Parents of U8–U10 players often ask the same question: "Is my kid learning the right things?" It's a good question. The research on youth athletic development is clear: what players learn between ages 7 and 10 creates habits — both physical and cognitive — that are extraordinarily difficult to change later.</p>

<p>So what actually matters at this age? At APC, our approach is shaped by the same principles that guide elite academies in Europe and South America. Here's what we focus on — and what we deliberately don't rush.</p>

<h2>1. First Touch: The Foundation of Everything</h2>

<p>Ask any professional player what skill separates good players from great ones, and the answer is almost always the same: first touch. A clean first touch buys you time. It creates options. It keeps you calm under pressure.</p>

<p>At U8–U10, we spend a significant portion of every session on ball mastery — not through repetitive drills, but through dynamic exercises that make players constantly adjust to the ball, use both feet, and develop spatial awareness simultaneously.</p>

<p>The goal by U10 isn't to have a perfect touch. It's for the touch to be automatic — something the player doesn't have to think about.</p>

<h2>2. Positional Awareness (Not Positions)</h2>

<p>There's an important distinction between teaching positions and teaching positional awareness. At U8–U10, we don't lock players into fixed roles. Instead, we teach them to read the game: where is space? Where are my teammates? Where is pressure coming from?</p>

<p>This is why our training at this age emphasizes small-sided games (3v3, 4v4) rather than 11v11 formats. In a small-sided game, every player touches the ball more, makes more decisions, and learns to read the game faster.</p>

<h2>3. Comfort With Both Feet</h2>

<p>Most players develop a dominant foot early. The window to establish genuine two-footedness largely closes around age 11–12. At U8–U10, we deliberately design exercises that force players to use their weak foot — not punitively, but through games and challenges that make it natural.</p>

<p>A player who is comfortable with both feet at U10 has a massive advantage as they move into competitive soccer. They're simply harder to defend.</p>

<h2>4. 1v1 Confidence</h2>

<p>At the younger ages, many players avoid 1v1 situations. They pass too early, or they freeze when they have a defender in front of them. This is a habit that compounds over time — by U14, players who never learned to take defenders on become entirely predictable.</p>

<p>We train 1v1 situations constantly at U8–U10. Not to produce dribblers, but to build confidence. A player who isn't afraid of 1v1s is a player who keeps the ball under pressure, creates chances, and trusts themselves in critical moments.</p>

<h2>What We Don't Focus On (Yet)</h2>

<p>We don't drill tactics heavily at this age. We don't run intense fitness work. We don't emphasize winning above learning. These things matter — but they matter later. Rushing tactical structure onto players who are still building basic technical fluency produces players who look organized but can't actually play.</p>

<p>The U8–U10 years are about love of the game, technical foundation, and competitive spirit. Get those three things right, and the rest of the development pathway opens up naturally.</p>

<h2>Is My Child Ready for APC?</h2>

<p>We get this question a lot. The honest answer: if your child loves soccer and wants to be challenged, they're ready. We don't require prior experience for our U8–U10 training groups. We do require coachability, effort, and a genuine desire to improve.</p>

<p>If that sounds like your athlete, we'd love to have them come train with us.</p>
''',
        'og_description': (
            'The U8–U10 window shapes habits that are hard to change later. '
            'Here\'s what APC\'s coaches actually prioritize for young players — and what can wait.'
        ),
    },
]


class Command(BaseCommand):
    help = 'Seed 2 foundation blog posts'

    def handle(self, *args, **options):
        for data in POSTS:
            post, created = BlogPost.objects.update_or_create(
                slug=data['slug'],
                defaults={
                    'title': data['title'],
                    'category': data['category'],
                    'excerpt': data['excerpt'],
                    'body': data['body'].strip(),
                    'og_description': data.get('og_description', ''),
                    'is_featured': data['is_featured'],
                    'is_published': True,
                    'published_at': timezone.now(),
                }
            )
            verb = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{verb}: {post.title}'))
