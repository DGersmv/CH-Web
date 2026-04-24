from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MANAGER = 'manager', 'Manager'
        DESIGNER = 'designer', 'Designer'
        PRODUCTION = 'production', 'Production'
        ADMIN = 'admin', 'Admin'
        HEAD = 'head', 'Head'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MANAGER,
    )


class DirectMessage(models.Model):
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_direct_messages',
    )
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='received_direct_messages',
    )
    body = models.TextField()
    attachment = models.FileField(upload_to='direct_messages/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.sender.username} -> {self.recipient.username}'


class Notification(models.Model):
    class Type(models.TextChoices):
        TASK_ASSIGNED = 'task_assigned', 'Task assigned'
        MESSAGE_RECEIVED = 'message_received', 'Message received'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_notifications',
    )
    notification_type = models.CharField(max_length=40, choices=Type.choices)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default='')
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    related_model = models.CharField(max_length=100, blank=True, default='')
    related_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_events',
    )
    event_type = models.CharField(max_length=100)
    entity_model = models.CharField(max_length=100)
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    ip_address = models.CharField(max_length=64, blank=True, default='')
    user_agent = models.CharField(max_length=512, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
