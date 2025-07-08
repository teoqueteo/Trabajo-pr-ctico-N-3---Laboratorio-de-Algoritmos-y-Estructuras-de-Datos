import datetime
from django.contrib import admin
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator


class Question(models.Model):
    question_text = models.CharField(
        max_length=200,
        validators=[MinLengthValidator(10, "Question must be at least 10 characters long.")],
        help_text="Enter a clear, concise question (10-200 characters)"
    )
    pub_date = models.DateTimeField(
        "date published",
        help_text="When this question should be published"
    )
    
    # Store the annotated total_votes value
    _total_votes_cache = None
    
    class Meta:
        ordering = ['-pub_date']
        verbose_name = "Poll Question"
        verbose_name_plural = "Poll Questions"
    
    def __str__(self):
        return self.question_text
    
    def clean(self):
        """Custom validation for the question"""
        super().clean()
        if self.question_text and not self.question_text.endswith('?'):
            raise ValidationError({'question_text': 'Questions should end with a question mark.'})
        
        # Prevent questions with identical text published on the same day
        if self.question_text and self.pub_date:
            same_day_questions = Question.objects.filter(
                question_text__iexact=self.question_text,
                pub_date__date=self.pub_date.date()
            )
            if self.pk:
                same_day_questions = same_day_questions.exclude(pk=self.pk)
            
            if same_day_questions.exists():
                raise ValidationError({
                    'question_text': 'A question with this text already exists for this date.'
                })
    
    @admin.display(
        boolean=True,
        ordering="pub_date", 
        description="Published recently?",
    )
    def was_published_recently(self):
        now = timezone.now()
        return now - datetime.timedelta(days=1) <= self.pub_date <= now
    
    @property
    def total_votes(self):
        """Calculate total votes for this question"""
        # If we have an annotated value (from admin queryset), use it
        if hasattr(self, '_total_votes_cache') and self._total_votes_cache is not None:
            return self._total_votes_cache or 0
        
        # Otherwise calculate it from related choices
        return sum(choice.votes for choice in self.choices.all())
    
    @total_votes.setter
    def total_votes(self, value):
        """Setter to handle annotated values from Django ORM"""
        self._total_votes_cache = value
    
    @property
    def is_published(self):
        """Check if question is published"""
        return self.pub_date <= timezone.now()
    
    @property
    def top_choice(self):
        """Get the choice with most votes"""
        return self.choices.order_by('-votes').first()
    
    def get_vote_percentage(self, choice):
        """Get percentage of votes for a specific choice"""
        if self.total_votes == 0:
            return 0
        return (choice.votes / self.total_votes) * 100
    
    def has_votes(self):
        """Check if question has any votes"""
        return self.total_votes > 0
    
    def reset_votes(self):
        """Reset all votes for this question"""
        self.choices.update(votes=0)
        # Clear the cache so it recalculates
        self._total_votes_cache = None


class Choice(models.Model):
    question = models.ForeignKey(
        Question, 
        on_delete=models.CASCADE,
        related_name='choices'
    )
    choice_text = models.CharField(
        max_length=200,
        validators=[MinLengthValidator(2, "Choice must be at least 2 characters long.")],
        help_text="Enter a clear choice option (2-200 characters)"
    )
    votes = models.IntegerField(
        default=0,
        help_text="Number of votes this choice has received"
    )
    
    class Meta:
        ordering = ['-votes', 'choice_text']
        verbose_name = "Choice Option"
        verbose_name_plural = "Choice Options"
        # Ensure no duplicate choices for the same question
        unique_together = ['question', 'choice_text']
    
    def __str__(self):
        return f"{self.choice_text} ({self.votes} votes)"
    
    def clean(self):
        """Custom validation for choices"""
        super().clean()
        
        # Ensure votes are not negative
        if self.votes < 0:
            raise ValidationError({'votes': 'Votes cannot be negative.'})
        
        # Prevent empty or whitespace-only choices
        if self.choice_text and not self.choice_text.strip():
            raise ValidationError({'choice_text': 'Choice cannot be empty or contain only whitespace.'})
    
    @property
    def percentage_of_total(self):
        """Get percentage of total votes for this choice"""
        if not self.question or self.question.total_votes == 0:
            return 0
        return (self.votes / self.question.total_votes) * 100
    
    def is_winning(self):
        """Check if this choice is currently winning"""
        return self == self.question.top_choice
    
    def vote_difference_from_leader(self):
        """Get vote difference from the leading choice"""
        top_choice = self.question.top_choice
        if not top_choice:
            return 0
        return top_choice.votes - self.votes