from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import User


SUPERADMIN_USERNAME = 'superadmin'
SUPERADMIN_PASSWORD = '123456789'
SUPERADMIN_EMAIL = '2277277@bk.ru'
SUPERADMIN_FIRST_NAME = 'Дмитрий'
SUPERADMIN_LAST_NAME = 'Герасимов'


class Command(BaseCommand):
    help = 'Create or update the hidden superadmin platform-owner account.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-password',
            action='store_true',
            help='Reset the platform owner password to the default.',
        )

    def handle(self, *args, **options):
        user_model = get_user_model()
        user = user_model.objects.filter(username=SUPERADMIN_USERNAME).first()
        created = user is None
        if created:
            user = user_model(username=SUPERADMIN_USERNAME)
            user.set_password(SUPERADMIN_PASSWORD)

        user.email = SUPERADMIN_EMAIL
        user.first_name = SUPERADMIN_FIRST_NAME
        user.last_name = SUPERADMIN_LAST_NAME
        user.role = User.Role.SUPERADMIN
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        if options['reset_password'] and not created:
            user.set_password(SUPERADMIN_PASSWORD)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f'Created platform owner {SUPERADMIN_USERNAME}.'))
        elif options['reset_password']:
            self.stdout.write(self.style.SUCCESS(f'Reset password for {SUPERADMIN_USERNAME}.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Updated platform owner {SUPERADMIN_USERNAME}.'))
