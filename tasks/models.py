from django.conf import settings
from django.db import models
from django.utils import timezone

from deals.models import Deal


class Task(models.Model):
    deal = models.ForeignKey(
        Deal,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='tasks',
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks',
    )
    title = models.CharField(max_length=255)
    due_date = models.DateField()
    is_done = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def mark_done(self):
        self.is_done = True
        self.completed_at = timezone.now()
        self.save(update_fields=['is_done', 'completed_at'])

    def __str__(self):
        return self.title
