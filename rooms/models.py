from django.conf import settings
from django.db import models


class Room(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        ARCHIVED = 'archived', 'Archived'

    title = models.CharField(max_length=255, blank=True, default='')
    deal = models.ForeignKey(
        'deals.Deal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rooms',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_rooms',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    livekit_room_name = models.CharField(max_length=80, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title or f'Room {self.pk}'


class RoomMember(models.Model):
    class Kind(models.TextChoices):
        USER = 'user', 'User'
        UMNIK = 'umnik', 'Umnik'

    class Role(models.TextChoices):
        HOST = 'host', 'Host'
        MEMBER = 'member', 'Member'

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='room_memberships',
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.USER)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    last_read_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['room', 'user'],
                condition=models.Q(kind='user', user__isnull=False),
                name='rooms_member_unique_user',
            ),
            models.UniqueConstraint(
                fields=['room'],
                condition=models.Q(kind='umnik'),
                name='rooms_member_unique_umnik',
            ),
        ]

    def __str__(self):
        if self.kind == self.Kind.UMNIK:
            return f'Umnik in {self.room_id}'
        name = getattr(self.user, 'username', '?')
        return f'{name} in {self.room_id}'


class RoomMessage(models.Model):
    class Kind(models.TextChoices):
        TEXT = 'text', 'Text'
        FILE = 'file', 'File'
        VOICE_NOTE = 'voice_note', 'Voice note'
        SYSTEM = 'system', 'System'
        UMNIK = 'umnik', 'Umnik'

    class AuthorKind(models.TextChoices):
        USER = 'user', 'User'
        UMNIK = 'umnik', 'Umnik'
        SYSTEM = 'system', 'System'

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='room_messages',
    )
    author_kind = models.CharField(max_length=20, choices=AuthorKind.choices, default=AuthorKind.USER)
    body = models.TextField(blank=True, default='')
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.TEXT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.room_id}:{self.pk}'


class RoomMessageAttachment(models.Model):
    message = models.ForeignKey(RoomMessage, on_delete=models.CASCADE, related_name='attachments')
    relative_path = models.CharField(max_length=500)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120, blank=True, default='')
    size_bytes = models.PositiveIntegerField(default=0)

    @property
    def is_image(self) -> bool:
        return (self.mime_type or '').startswith('image/')

    @property
    def is_pdf(self) -> bool:
        name = (self.original_name or '').lower()
        return self.mime_type == 'application/pdf' or name.endswith('.pdf')

    @property
    def is_audio(self) -> bool:
        mime = (self.mime_type or '').lower()
        name = (self.original_name or '').lower()
        return mime.startswith('audio/') or name.endswith(('.ogg', '.webm', '.m4a', '.mp3', '.wav', '.aac', '.mp4'))

    def __str__(self):
        return self.original_name
