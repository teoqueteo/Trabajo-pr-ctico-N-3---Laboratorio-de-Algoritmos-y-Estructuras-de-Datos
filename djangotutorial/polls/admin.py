import csv
from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html
from django.urls import path, reverse
from django.shortcuts import render, redirect
from django.db.models import Sum, Count, Q
import datetime

from .models import Choice, Question


# Custom Filters (defined first so they can be referenced)
class PublishedRecentlyFilter(admin.SimpleListFilter):
    title = 'publication status'
    parameter_name = 'pub_status'
    
    def lookups(self, request, model_admin):
        return (
            ('recent', 'Published recently'),
            ('old', 'Published more than a week ago'),
            ('future', 'Scheduled for future'),
        )
    
    def queryset(self, request, queryset):
        now = timezone.now()
        if self.value() == 'recent':
            return queryset.filter(
                pub_date__gte=now - datetime.timedelta(days=7),
                pub_date__lte=now
            )
        elif self.value() == 'old':
            return queryset.filter(
                pub_date__lt=now - datetime.timedelta(days=7)
            )
        elif self.value() == 'future':
            return queryset.filter(pub_date__gt=now)


class VoteCountFilter(admin.SimpleListFilter):
    title = 'vote count'
    parameter_name = 'vote_count'
    
    def lookups(self, request, model_admin):
        return (
            ('no_votes', 'No votes'),
            ('low_votes', 'Low votes (1-10)'),
            ('medium_votes', 'Medium votes (11-50)'),
            ('high_votes', 'High votes (50+)'),
        )
    
    def queryset(self, request, queryset):
        # Fixed: Use 'choices__votes' instead of 'choice__votes'
        queryset = queryset.annotate(total_votes=Sum('choices__votes'))
        
        if self.value() == 'no_votes':
            return queryset.filter(Q(total_votes=0) | Q(total_votes__isnull=True))
        elif self.value() == 'low_votes':
            return queryset.filter(total_votes__range=(1, 10))
        elif self.value() == 'medium_votes':
            return queryset.filter(total_votes__range=(11, 50))
        elif self.value() == 'high_votes':
            return queryset.filter(total_votes__gt=50)


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 2
    min_num = 2  # Ensure at least 2 choices
    fields = ['choice_text', 'votes']
    readonly_fields = ['votes']
    
    def get_extra(self, request, obj=None, **kwargs):
        # Show fewer extra forms when editing existing questions
        if obj:
            return 1
        return self.extra


class QuestionAdmin(admin.ModelAdmin):
    fieldsets = [
        (None, {"fields": ["question_text"]}),
        ("Date information", {"fields": ["pub_date"], "classes": ["collapse"]}),
    ]
    inlines = [ChoiceInline]
    list_display = [
        "question_text", 
        "pub_date", 
        "was_published_recently",
        "total_votes_display",
        "choice_count",
        "is_active",
        "days_since_published"
    ]
    list_filter = [
        "pub_date", 
        PublishedRecentlyFilter,
        VoteCountFilter
    ]
    # Fixed: Use 'choices__choice_text' instead of 'choice__choice_text'
    search_fields = ["question_text", "choices__choice_text"]
    readonly_fields = ["total_votes_display", "choice_count"]
    date_hierarchy = "pub_date"
    list_per_page = 20
    actions = [
        'make_published_today',
        'reset_all_votes',
        'export_as_csv',
        'duplicate_questions'
    ]
    
    def get_queryset(self, request):
        # Optimize queries by prefetching related choices
        queryset = super().get_queryset(request)
        # Fixed: Use 'choices' instead of 'choice_set' and 'choices__votes' instead of 'choice__votes'
        return queryset.prefetch_related('choices').annotate(
            total_votes=Sum('choices__votes'),
            choice_count=Count('choices')
        )
    
    def total_votes_display(self, obj):
        """Display total votes with color coding"""
        total = obj.total_votes or 0
        if total == 0:
            color = 'red'
        elif total < 10:
            color = 'orange'
        else:
            color = 'green'
        return format_html(
            '<span style="color: {};">{} votes</span>',
            color,
            total
        )
    total_votes_display.short_description = "Total Votes"
    total_votes_display.admin_order_field = 'total_votes'
    
    def choice_count(self, obj):
        """Display number of choices"""
        return obj.choice_count
    choice_count.short_description = "# Choices"
    choice_count.admin_order_field = 'choice_count'
    
    def is_active(self, obj):
        """Show if question is currently active (published and recent)"""
        now = timezone.now()
        is_published = obj.pub_date <= now
        is_recent = now - obj.pub_date <= datetime.timedelta(days=30)
        active = is_published and is_recent
        
        # Return boolean value for Django's boolean field rendering
        return active
    is_active.short_description = "Active"
    is_active.boolean = True  # This tells Django to show checkmark/X icons
    
    def days_since_published(self, obj):
        """Show days since publication"""
        if obj.pub_date > timezone.now():
            return "Future"
        delta = timezone.now() - obj.pub_date
        return f"{delta.days} days ago"
    days_since_published.short_description = "Age"
    
    # Custom Actions
    def make_published_today(self, request, queryset):
        """Set publication date to today for selected questions"""
        updated = queryset.update(pub_date=timezone.now())
        self.message_user(
            request,
            f"{updated} questions were successfully published today.",
            messages.SUCCESS
        )
    make_published_today.short_description = "Publish selected questions today"
    
    def reset_all_votes(self, request, queryset):
        """Reset all votes for selected questions"""
        total_reset = 0
        for question in queryset:
            # Fixed: Use 'choices' instead of 'choice_set'
            choices_updated = question.choices.update(votes=0)
            total_reset += choices_updated
            
        self.message_user(
            request,
            f"Reset votes for {total_reset} choices across {queryset.count()} questions.",
            messages.SUCCESS
        )
    reset_all_votes.short_description = "Reset all votes for selected questions"
    
    def export_as_csv(self, request, queryset):
        """Export selected questions and their data as CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="polls_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Question', 'Publication Date', 'Choice', 'Votes', 'Total Votes'])
        
        # Fixed: Use 'choices' instead of 'choice_set'
        for question in queryset.prefetch_related('choices'):
            total_votes = sum(choice.votes for choice in question.choices.all())
            for choice in question.choices.all():
                writer.writerow([
                    question.question_text,
                    question.pub_date.strftime('%Y-%m-%d %H:%M'),
                    choice.choice_text,
                    choice.votes,
                    total_votes
                ])
        
        return response
    export_as_csv.short_description = "Export selected questions as CSV"
    
    def duplicate_questions(self, request, queryset):
        """Create duplicates of selected questions"""
        duplicated = 0
        for question in queryset:
            # Store original choices - Fixed: Use 'choices' instead of 'choice_set'
            original_choices = list(question.choices.all())
            
            # Create duplicate question
            question.pk = None
            question.question_text = f"Copy of {question.question_text}"
            question.pub_date = timezone.now()
            question.save()
            
            # Create duplicate choices
            for choice in original_choices:
                choice.pk = None
                choice.question = question
                choice.votes = 0  # Reset votes for duplicates
                choice.save()
            
            duplicated += 1
            
        self.message_user(
            request,
            f"Successfully created {duplicated} duplicate questions.",
            messages.SUCCESS
        )
    duplicate_questions.short_description = "Duplicate selected questions"


class ChoiceAdmin(admin.ModelAdmin):
    list_display = ['choice_text', 'question', 'votes', 'percentage_of_total']
    list_filter = ['question__pub_date', 'votes']
    search_fields = ['choice_text', 'question__question_text']
    list_editable = ['votes']
    list_per_page = 50
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('question')
    
    def percentage_of_total(self, obj):
        """Show what percentage of total votes this choice has"""
        total_votes = obj.question.total_votes
        if total_votes == 0:
            return "0%"
        percentage = (obj.votes / total_votes) * 100
        return f"{percentage:.1f}%"
    percentage_of_total.short_description = "% of Total"


# Register models
admin.site.register(Question, QuestionAdmin)
admin.site.register(Choice, ChoiceAdmin)

# Customize admin site headers
admin.site.site_header = "Polls Administration"
admin.site.site_title = "Polls Admin"
admin.site.index_title = "Welcome to Polls Administration"