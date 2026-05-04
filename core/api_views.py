from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import DirectMessage
from accounts.models import Notification


def _user_payload(user):
    full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
    return {
        'id': user.id,
        'username': user.username,
        'full_name': full_name,
    }


def _message_payload(message):
    return {
        'id': message.id,
        'sender': _user_payload(message.sender),
        'recipient': _user_payload(message.recipient),
        'body': message.body,
        'attachment_url': message.attachment.url if message.attachment else None,
        'attachment_name': message.attachment.name.split('/')[-1] if message.attachment else None,
        'created_at': message.created_at.isoformat(),
        'read_at': message.read_at.isoformat() if message.read_at else None,
        'is_read': message.read_at is not None,
    }


class DirectMessageListCreateApi(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        dialog_with = request.GET.get('dialog_with')
        base = DirectMessage.objects.select_related('sender', 'recipient').filter(
            Q(sender=request.user) | Q(recipient=request.user)
        )
        if dialog_with and str(dialog_with).isdigit():
            counterpart = get_user_model().objects.filter(pk=int(dialog_with), is_active=True).first()
            if counterpart is None:
                return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
            items = [
                _message_payload(item)
                for item in base.filter(
                    (Q(sender=request.user) & Q(recipient=counterpart))
                    | (Q(sender=counterpart) & Q(recipient=request.user))
                ).order_by('-created_at')[:100]
            ]
            return Response({'dialog_with': _user_payload(counterpart), 'items': items}, status=status.HTTP_200_OK)

        dialogs = {}
        for msg in base.order_by('-created_at')[:500]:
            counterpart = msg.recipient if msg.sender_id == request.user.id else msg.sender
            if counterpart.id not in dialogs:
                dialogs[counterpart.id] = {
                    'user': _user_payload(counterpart),
                    'last_message': _message_payload(msg),
                    'unread_count': 0,
                }
            if msg.recipient_id == request.user.id and msg.read_at is None:
                dialogs[counterpart.id]['unread_count'] += 1
        return Response({'dialogs': list(dialogs.values())}, status=status.HTTP_200_OK)

    def post(self, request):
        recipient_id = request.data.get('recipient_id')
        body = (request.data.get('body') or '').strip()
        attachment = request.FILES.get('attachment')
        if not recipient_id:
            return Response({'detail': 'recipient_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not body and not attachment:
            return Response({'detail': 'body or attachment is required.'}, status=status.HTTP_400_BAD_REQUEST)

        user_model = get_user_model()
        recipient = user_model.objects.filter(pk=recipient_id, is_active=True).first()
        if recipient is None:
            return Response({'detail': 'Recipient not found or inactive.'}, status=status.HTTP_400_BAD_REQUEST)
        if recipient.pk == request.user.pk:
            return Response({'detail': 'Cannot send message to yourself.'}, status=status.HTTP_400_BAD_REQUEST)

        message = DirectMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            body=body,
            attachment=attachment,
        )
        return Response(_message_payload(message), status=status.HTTP_201_CREATED)


class DirectMessageReadApi(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, message_id):
        message = DirectMessage.objects.select_related('sender', 'recipient').filter(pk=message_id, recipient=request.user).first()
        if message is None:
            return Response({'detail': 'Message not found.'}, status=status.HTTP_404_NOT_FOUND)
        if message.read_at is None:
            message.read_at = timezone.now()
            message.save(update_fields=['read_at'])
            Notification.objects.filter(
                user=request.user,
                notification_type=Notification.Type.MESSAGE_RECEIVED,
                related_model='DirectMessage',
                related_id=message.id,
                is_read=False,
            ).update(is_read=True, read_at=timezone.now())
        return Response(_message_payload(message), status=status.HTTP_200_OK)


class NotificationListApi(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Notification.objects.select_related('actor').filter(user=request.user)[:50]
        items = [
            {
                'id': item.id,
                'type': item.notification_type,
                'title': item.title,
                'body': item.body,
                'is_read': item.is_read,
                'read_at': item.read_at.isoformat() if item.read_at else None,
                'created_at': item.created_at.isoformat(),
                'actor': _user_payload(item.actor) if item.actor else None,
                'related_model': item.related_model,
                'related_id': item.related_id,
            }
            for item in queryset
        ]
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'unread_count': unread_count, 'items': items}, status=status.HTTP_200_OK)


class NotificationReadAllApi(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = Notification.objects.filter(user=request.user, is_read=False).update(
            is_read=True,
            read_at=timezone.now(),
        )
        return Response({'updated': updated}, status=status.HTTP_200_OK)
