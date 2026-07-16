from django.utils import timezone
from rest_framework import authentication
from rest_framework import exceptions

from .models import IntegrationToken


class IntegrationTokenAuthentication(authentication.BaseAuthentication):
    keyword_values = ('token', 'bearer')

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode('utf-8')
        if not header:
            return None

        parts = header.split()
        if len(parts) != 2:
            return None

        keyword, token_key = parts[0].lower(), parts[1].strip()
        if keyword not in self.keyword_values:
            return None

        token = (
            IntegrationToken.objects.select_related('owner')
            .filter(key=token_key, is_active=True, owner__is_active=True)
            .first()
        )
        if token is None:
            raise exceptions.AuthenticationFailed('Invalid integration token.')

        token.last_used_at = timezone.now()
        token.save(update_fields=['last_used_at'])
        return token.owner, token
