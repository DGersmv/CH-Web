from django.contrib import admin

from .models import Room, RoomMember, RoomMessage, RoomMessageAttachment


class RoomMemberInline(admin.TabularInline):
    model = RoomMember
    extra = 0


class RoomMessageAttachmentInline(admin.TabularInline):
    model = RoomMessageAttachment
    extra = 0
    readonly_fields = ('relative_path', 'original_name', 'mime_type', 'size_bytes')


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'created_by', 'updated_at')
    list_filter = ('status',)
    inlines = [RoomMemberInline]


@admin.register(RoomMessage)
class RoomMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'room', 'author_kind', 'author', 'kind', 'created_at')
    list_filter = ('author_kind', 'kind')
    inlines = [RoomMessageAttachmentInline]
