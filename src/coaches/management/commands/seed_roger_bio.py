"""
Management command to seed Roger Espinoza's public profile bio fields.

Usage:
    python manage.py seed_roger_bio

Safe to re-run — only updates if the coach record exists.
"""
from django.core.management.base import BaseCommand


TAGLINE = "FA Cup Winner · 2x World Cup · 14 Seasons Sporting KC"

EXPERIENCE_YEARS = 12

FULL_BIO = """Roger Espinoza is one of the most decorated players in Kansas City soccer history. Born in Honduras and raised with an elite footballing education, Roger earned his place among the best midfielders in MLS history through relentless work rate, tactical intelligence, and an engine that never stops. His crowning moment came on May 11, 2013, when he scored the decisive goal in Wigan Athletic's FA Cup Final victory over Manchester City — one of the greatest upsets in FA Cup history and a moment that reverberated around the world.

At Sporting Kansas City, Roger became an institution over 14 seasons, cementing his place as one of the top three appearance-makers in club history. He represented Honduras in two World Cup cycles, competing in the 2014 Brazil World Cup and playing a pivotal role in the 2018 qualifying campaign. His 2012 Olympic performance included a memorable goal against Brazil in the group stage — a statement on the world's biggest youth football stage.

Now based in Overland Park, Roger brings that same world-class mindset to youth development at Atletas Performance Center. His coaching philosophy centers on developing complete athletes — technically sharp, tactically aware, physically prepared, and mentally resilient — to give every player the tools they need to compete at the highest level their talent allows."""

ACHIEVEMENTS = """FA Cup winner with Wigan Athletic (2013) — scored the decisive final goal
2014 FIFA World Cup appearance with Honduras (Brazil)
2018 World Cup qualifying campaign with Honduras
2012 London Olympics — scored against Brazil in group stage
Sporting Kansas City: 3rd all-time in club appearances (14 seasons)"""

COACHING_PHILOSOPHY = """Development at the elite level is about building the whole athlete, not just the technician. Every player I work with gets the same focus I brought to every training session at Sporting KC: maximum effort, tactical clarity, and the mental toughness to compete when it matters. I want my players to understand the game deeply — to see two passes ahead, to win their duels, and to trust their preparation. Youth development is the most important phase of a soccer career. Done right, it opens doors that stay open for life."""

SPECIALIZATIONS = "Midfield Development, Tactical Awareness, High-Performance Training, Youth Elite Development"


class Command(BaseCommand):
    help = "Seed Roger Espinoza's public coach profile bio fields"

    def handle(self, *args, **options):
        from coaches.models import Coach

        # Try to find Roger by first name; fall back to slug if set
        qs = Coach.objects.filter(user__first_name__iexact="Roger").select_related("user")
        if not qs.exists():
            # Try slug
            qs = Coach.objects.filter(slug="roger").select_related("user")

        if not qs.exists():
            self.stdout.write(
                self.style.WARNING(
                    "Roger's coach record not found — no changes made. "
                    "This command will succeed once his account exists in this database."
                )
            )
            return

        coach = qs.first()
        coach.tagline = TAGLINE
        coach.experience_years = EXPERIENCE_YEARS
        coach.full_bio = FULL_BIO
        coach.achievements = ACHIEVEMENTS
        coach.coaching_philosophy = COACHING_PHILOSOPHY
        coach.specializations = SPECIALIZATIONS
        coach.save(update_fields=[
            "tagline",
            "experience_years",
            "full_bio",
            "achievements",
            "coaching_philosophy",
            "specializations",
        ])

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded bio for {coach.user.get_full_name()} (id={coach.pk})"
            )
        )
