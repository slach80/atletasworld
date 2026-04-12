"""
Tests for coaches models.
"""
import pytest
from datetime import date, time, timedelta
from django.utils import timezone

from coaches.models import Coach, Availability, ScheduleBlock, PlayerAssessment
from clients.models import Player


@pytest.mark.unit
class TestCoachModel:
    """Test cases for Coach model."""

    def test_coach_creation(self, coach, coach_user):
        """Test that a coach profile is created correctly."""
        assert coach.user == coach_user
        assert coach.slug == 'mirko-test'
        assert coach.bio == 'Test coach bio'
        assert coach.hourly_rate == 75.00
        assert coach.is_active is True
        assert coach.profile_enabled is True

    def test_coach_string_representation(self, coach):
        """Test the string representation of a coach."""
        expected = f"Coach {coach.user.get_full_name()}"
        assert str(coach) == expected

    def test_coach_default_values(self, coach_user):
        """Test default values for coach fields."""
        coach = Coach.objects.create(
            user=coach_user,
            slug='test-coach'
        )
        assert coach.hourly_rate == 0
        assert coach.is_active is True
        assert coach.profile_enabled is False
        assert coach.experience_years == 0

    def test_coach_ordering(self, db):
        """Test that coaches are ordered by first name."""
        from django.contrib.auth.models import User

        user1 = User.objects.create_user(
            username='coach_a',
            first_name='Aaron',
            last_name='Test'
        )
        user2 = User.objects.create_user(
            username='coach_z',
            first_name='Zach',
            last_name='Test'
        )

        coach2 = Coach.objects.create(user=user2, slug='zach')
        coach1 = Coach.objects.create(user=user1, slug='aaron')

        coaches = list(Coach.objects.all())
        assert coaches[0] == coach1
        assert coaches[1] == coach2


@pytest.mark.unit
class TestAvailabilityModel:
    """Test cases for Availability model."""

    def test_availability_creation(self, availability, coach):
        """Test that availability is created correctly."""
        assert availability.coach == coach
        assert availability.day_of_week == 0  # Monday
        assert availability.start_time == time(9, 0)
        assert availability.end_time == time(17, 0)
        assert availability.is_active is True

    def test_availability_ordering(self, coach):
        """Test that availabilities are ordered by day and time."""
        # Create availabilities out of order
        avail_wed = Availability.objects.create(
            coach=coach,
            day_of_week=2,  # Wednesday
            start_time=time(10, 0),
            end_time=time(12, 0)
        )
        avail_mon = Availability.objects.create(
            coach=coach,
            day_of_week=0,  # Monday
            start_time=time(14, 0),
            end_time=time(16, 0)
        )
        avail_mon_morning = Availability.objects.create(
            coach=coach,
            day_of_week=0,  # Monday
            start_time=time(9, 0),
            end_time=time(11, 0)
        )

        availabilities = list(Availability.objects.filter(coach=coach))
        # Should be ordered by day_of_week, then start_time
        assert availabilities[0] == avail_mon_morning
        assert availabilities[1] == avail_mon
        assert availabilities[2] == avail_wed

    def test_availability_verbose_name_plural(self):
        """Test the verbose name plural is correct."""
        assert Availability._meta.verbose_name_plural == 'Availabilities'


@pytest.mark.unit
class TestScheduleBlockModel:
    """Test cases for ScheduleBlock model."""

    def test_schedule_block_creation(self, schedule_block, coach):
        """Test that schedule block is created correctly."""
        assert schedule_block.coach == coach
        assert schedule_block.session_type == 'private'
        assert schedule_block.duration_minutes == 60
        assert schedule_block.max_participants == 1
        assert schedule_block.status == 'available'

    def test_schedule_block_is_available(self, schedule_block):
        """Test the is_available property."""
        assert schedule_block.is_available is True

        # Make it booked
        schedule_block.status = 'booked'
        schedule_block.save()
        assert schedule_block.is_available is False

    def test_schedule_block_spots_remaining(self, schedule_block):
        """Test the spots_remaining property."""
        assert schedule_block.spots_remaining == 1

        schedule_block.current_participants = 1
        schedule_block.save()
        assert schedule_block.spots_remaining == 0

    def test_schedule_block_check_overlap_warnings(self, coach):
        """Test checking for overlapping blocks with other coaches."""
        test_date = date.today() + timedelta(days=1)

        # Create first block
        block1 = ScheduleBlock.objects.create(
            coach=coach,
            date=test_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            status='available'
        )

        # Create overlapping block with different coach
        from django.contrib.auth.models import User
        other_user = User.objects.create_user(
            username='other_coach',
            first_name='Other',
            last_name='Coach'
        )
        other_coach = Coach.objects.create(
            user=other_user,
            slug='other-coach'
        )

        block2 = ScheduleBlock.objects.create(
            coach=other_coach,
            date=test_date,
            start_time=time(10, 30),
            end_time=time(11, 30),
            status='available'
        )

        overlaps = block1.check_overlap_warnings()
        assert block2 in list(overlaps)

    def test_schedule_block_no_overlap(self, coach):
        """Test that non-overlapping blocks are not flagged."""
        test_date = date.today() + timedelta(days=1)

        block1 = ScheduleBlock.objects.create(
            coach=coach,
            date=test_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            status='available'
        )

        # Create non-overlapping block
        block2 = ScheduleBlock.objects.create(
            coach=coach,
            date=test_date,
            start_time=time(12, 0),
            end_time=time(13, 0),
            status='available'
        )

        overlaps = block1.check_overlap_warnings()
        assert block2 not in list(overlaps)

    def test_schedule_block_unique_constraint(self, coach):
        """Test that duplicate blocks for same coach/date/time are prevented."""
        test_date = date.today() + timedelta(days=1)

        ScheduleBlock.objects.create(
            coach=coach,
            date=test_date,
            start_time=time(10, 0),
            end_time=time(11, 0)
        )

        # Should raise integrity error for duplicate
        with pytest.raises(Exception):
            ScheduleBlock.objects.create(
                coach=coach,
                date=test_date,
                start_time=time(10, 0),
                end_time=time(11, 30)
            )

    def test_schedule_block_string_representation(self, schedule_block):
        """Test the string representation."""
        expected = f"{schedule_block.coach} - {schedule_block.date} {schedule_block.start_time} ({schedule_block.get_session_type_display()})"
        assert str(schedule_block) == expected


@pytest.mark.unit
class TestPlayerAssessmentModel:
    """Test cases for PlayerAssessment model."""

    def test_assessment_creation(self, player_assessment, booking, coach, player):
        """Test that assessment is created correctly."""
        assert player_assessment.booking == booking
        assert player_assessment.coach == coach
        assert player_assessment.player == player
        assert player_assessment.training_type == 'technical'

    def test_assessment_ratings(self, player_assessment):
        """Test that ratings are stored correctly."""
        assert player_assessment.effort_engagement == 4
        assert player_assessment.technical_proficiency == 3
        assert player_assessment.tactical_awareness == 3
        assert player_assessment.physical_performance == 4
        assert player_assessment.goals_achievement == 4

    def test_overall_rating_property(self, player_assessment):
        """Test the overall rating calculation."""
        expected = (4 + 3 + 3 + 4 + 4) / 5
        assert player_assessment.overall_rating == round(expected, 1)

    def test_overall_rating_all_fives(self):
        """Test overall rating with all 5s — no DB access needed, pure calculation."""
        assessment = PlayerAssessment(
            effort_engagement=5,
            technical_proficiency=5,
            tactical_awareness=5,
            physical_performance=5,
            goals_achievement=5,
        )
        assert assessment.overall_rating == 5.0

    def test_overall_rating_all_ones(self):
        """Test overall rating with all 1s."""
        assessment = PlayerAssessment(
            effort_engagement=1,
            technical_proficiency=1,
            tactical_awareness=1,
            physical_performance=1,
            goals_achievement=1
        )
        assert assessment.overall_rating == 1.0

    def test_assessment_ordering(self, booking, coach, player):
        """Test that assessments are ordered by date descending."""
        from django.contrib.auth.models import User
        from clients.models import Client

        user = User.objects.create_user(username='test_user2')
        client = Client.objects.create(user=user)
        player2 = Player.objects.create(
            client=client,
            first_name='Test',
            last_name='Player2',
            birth_year=2010,
            gender='M'
        )

        # Create assessments with explicit dates
        assessment1 = PlayerAssessment.objects.create(
            booking=booking,
            coach=coach,
            player=player2,
            training_type='technical',
            effort_engagement=3,
            technical_proficiency=3,
            tactical_awareness=3,
            physical_performance=3,
            goals_achievement=3
        )

        # Wait a moment to ensure different timestamps
        import time
        time.sleep(0.01)

        assessment2 = PlayerAssessment.objects.create(
            booking=booking,
            coach=coach,
            player=player2,
            training_type='tactical',
            effort_engagement=4,
            technical_proficiency=4,
            tactical_awareness=4,
            physical_performance=4,
            goals_achievement=4
        )

        assessments = list(PlayerAssessment.objects.filter(player=player2))
        # Should be ordered by assessment_date descending (newest first)
        assert assessments[0] == assessment2
        assert assessments[1] == assessment1

    def test_assessment_string_representation(self, player_assessment):
        """Test the string representation."""
        expected = f"{player_assessment.player} - {player_assessment.get_training_type_display()} ({player_assessment.assessment_date.date()})"
        assert str(player_assessment) == expected

    def test_assessment_notes_fields(self, player_assessment):
        """Test that all note fields are stored correctly."""
        assert player_assessment.focus_areas == 'Improve first touch'
        assert player_assessment.highlights == 'Great effort today'
        assert player_assessment.coach_notes == ''
        assert player_assessment.parent_visible_notes == 'Excellent progress on passing'
