import json
import mimetypes

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import can_use_umnik_chat

from .models import Room, RoomMessageAttachment
from .services import (
    add_umnik,
    attachment_abs,
    avatar_color,
    colleague_qs,
    display_name,
    filter_rooms,
    get_or_create_room,
    has_umnik,
    human_members,
    initials,
    mark_read,
    member_of,
    post_message,
    remove_umnik,
    room_title_for,
    serialize_message,
    serialize_person,
    serialize_room,
    visible_rooms,
)


def _ns(request) -> str:
    return getattr(request.resolver_match, 'namespace', None) or 'rooms'


def _is_app(request) -> bool:
    return _ns(request) == 'app'


def _require_member(request, room_id) -> Room:
    room = get_object_or_404(Room.objects.prefetch_related('members__user', 'deal'), pk=room_id)
    if member_of(room, request.user) is None:
        raise Http404()
    return room


FOLDERS = (
    ('all', 'Все'),
    ('new', 'Новые'),
    ('work', 'Рабочая'),
    ('clients', 'Клиенты'),
)


def _folder(request) -> str:
    value = (request.GET.get('folder') or 'all').strip()
    allowed = {item[0] for item in FOLDERS}
    return value if value in allowed else 'all'


def _messenger(request, nav_tab='chats', extra=None):
    ns = _ns(request)
    folder = _folder(request)
    all_rooms = [serialize_room(room, request.user, ns) for room in visible_rooms(request.user)]
    ctx = {
        'is_app_shell': _is_app(request),
        'nav_tab': nav_tab,
        'folder': folder,
        'folders': FOLDERS,
        'all_rooms': all_rooms,
        'rooms': filter_rooms(all_rooms, folder),
        'unread_total': sum(1 for item in all_rooms if item.get('unread')),
        'can_use_umnik': can_use_umnik_chat(request.user),
    }
    if extra:
        ctx.update(extra)
    return ctx


@login_required
def room_list(request):
    return render(request, 'rooms/list.html', _messenger(request, 'chats'))


@login_required
def room_contacts(request):
    ns = _ns(request)
    people = [serialize_person(user, ns) for user in colleague_qs(request.user)]
    return render(
        request,
        'rooms/contacts.html',
        _messenger(request, 'contacts', {'people': people}),
    )


@login_required
def room_calls(request):
    return render(request, 'rooms/calls.html', _messenger(request, 'calls'))


@login_required
def room_settings(request):
    return render(request, 'rooms/settings.html', _messenger(request, 'settings'))


@login_required
def room_open_user(request, user_id):
    ns = _ns(request)
    target = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    if target.pk == request.user.pk:
        return redirect(f'{ns}:contacts')
    room = get_or_create_room(creator=request.user, user_ids=[target.id], with_umnik=False)
    return redirect(f'{ns}:detail', room.id)


@login_required
def room_open_umnik(request):
    ns = _ns(request)
    if not can_use_umnik_chat(request.user):
        raise Http404()
    room = get_or_create_room(creator=request.user, user_ids=[], with_umnik=True)
    return redirect(f'{ns}:detail', room.id)


@login_required
@require_http_methods(['GET', 'POST'])
def room_new(request):
    ns = _ns(request)
    colleagues = colleague_qs(request.user)
    if request.method == 'POST':
        raw_ids = request.POST.getlist('user_ids')
        with_umnik = request.POST.get('with_umnik') in {'on', '1', 'true', 'yes'}
        try:
            room = get_or_create_room(creator=request.user, user_ids=raw_ids, with_umnik=with_umnik)
        except ValueError:
            return render(
                request,
                'rooms/new.html',
                _messenger(
                    request,
                    'chats',
                    {
                        'colleagues': colleagues,
                        'error': 'Выберите сотрудника или добавьте Умника.',
                    },
                ),
                status=400,
            )
        return redirect(f'{ns}:detail', room.id)
    return render(
        request,
        'rooms/new.html',
        _messenger(request, 'chats', {'colleagues': colleagues}),
    )


@login_required
def room_detail(request, room_id):
    ns = _ns(request)
    room = _require_member(request, room_id)
    mark_read(room, request.user)
    messages = [
        serialize_message(msg, ns)
        for msg in room.messages.select_related('author').prefetch_related('attachments').order_by('created_at', 'id')
    ]
    people = [display_name(m.user) for m in human_members(room)]
    title = room_title_for(room, request.user)
    extra = {
        'room': room,
        'room_title': title,
        'room_initials': initials(title),
        'room_color': avatar_color(str(room.id)),
        'messages_json': json.dumps(messages, ensure_ascii=False),
        'has_umnik': has_umnik(room),
        'people': people,
        'send_url': reverse(f'{ns}:send', args=[room.id]),
        'poll_url': reverse(f'{ns}:messages', args=[room.id]),
        'umnik_url': reverse(f'{ns}:umnik', args=[room.id]),
        'active_room_id': room.id,
    }
    return render(request, 'rooms/detail.html', _messenger(request, 'chats', extra))


@login_required
@require_GET
def room_messages(request, room_id):
    ns = _ns(request)
    room = _require_member(request, room_id)
    after = request.GET.get('after') or '0'
    try:
        after_id = int(after)
    except (TypeError, ValueError):
        after_id = 0
    qs = room.messages.select_related('author').prefetch_related('attachments').filter(pk__gt=after_id).order_by('id')
    mark_read(room, request.user)
    return JsonResponse({'items': [serialize_message(msg, ns) for msg in qs]})


@login_required
@require_POST
def room_send(request, room_id):
    ns = _ns(request)
    room = _require_member(request, room_id)
    body = request.POST.get('body') or ''
    uploads = [item for item in request.FILES.getlist('files') if item and getattr(item, 'size', 1)]
    if not uploads:
        uploads = [item for item in request.FILES.getlist('file') if item and getattr(item, 'size', 1)]
    try:
        payload = post_message(room=room, author=request.user, body=body, uploads=uploads, url_namespace=ns)
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'empty'}, status=400)
    mark_read(room, request.user)
    return JsonResponse({'ok': True, **payload})


@login_required
@require_POST
def room_toggle_umnik(request, room_id):
    ns = _ns(request)
    room = _require_member(request, room_id)
    if not can_use_umnik_chat(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    action = (request.POST.get('action') or 'add').strip()
    if action == 'remove':
        remove_umnik(room, request.user)
    else:
        add_umnik(room, request.user)
    if request.headers.get('Accept', '').find('application/json') >= 0:
        return JsonResponse({'ok': True, 'has_umnik': has_umnik(room)})
    return redirect(f'{ns}:detail', room.id)


@login_required
@require_GET
def room_file(request, room_id, att_id):
    room = _require_member(request, room_id)
    att = get_object_or_404(RoomMessageAttachment, pk=att_id, message__room=room)
    path = attachment_abs(att)
    if not path.is_file():
        raise Http404()
    mime = att.mime_type or mimetypes.guess_type(att.original_name)[0] or 'application/octet-stream'
    return FileResponse(path.open('rb'), as_attachment=False, filename=att.original_name, content_type=mime)


@login_required
def app_install(request):
    return render(request, 'rooms/install.html', _messenger(request, 'settings'))


def web_manifest(request):
    payload = {
        'id': '/app/',
        'name': 'CH-CRM Комнаты',
        'short_name': 'Комнаты',
        'start_url': '/app/',
        'scope': '/app/',
        'display': 'standalone',
        'display_override': ['standalone', 'browser'],
        'background_color': '#f8f9fa',
        'theme_color': '#f8f9fa',
        'lang': 'ru',
        'icons': [
            {
                'src': '/static/img/apple-touch-icon.png?v=2',
                'sizes': '180x180',
                'type': 'image/png',
                'purpose': 'any',
            }
        ],
    }
    return JsonResponse(payload, content_type='application/manifest+json')


def service_worker(request):
    js = (
        "self.addEventListener('install', function () { self.skipWaiting(); });\n"
        "self.addEventListener('activate', function (e) {\n"
        "  e.waitUntil(self.registration.unregister());\n"
        "});\n"
    )
    response = HttpResponse(js, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/app/'
    return response
