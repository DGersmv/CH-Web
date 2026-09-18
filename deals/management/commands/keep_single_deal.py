"""Оставить в базе и на диске только один проект (и одного пользователя admin)."""
from __future__ import annotations

import shutil

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.fields.related import ForeignKey, ManyToManyField, OneToOneField

from deals.models import Deal
from deals.services.storage_paths import get_client_root, get_files_root


KEEP_DEAL_CODE = "6МД-Ирина-Раздолье"
KEEP_USERNAME = "admin"


class Command(BaseCommand):
    help = "Keep one deal with its client/files and drop other projects and employees."

    def add_arguments(self, parser):
        parser.add_argument("--deal-code", default=KEEP_DEAL_CODE)
        parser.add_argument("--keep-user", default=KEEP_USERNAME)

    def handle(self, *args, **options):
        deal_code = options["deal_code"]
        keep_username = options["keep_user"]
        User = get_user_model()
        deal = Deal.objects.filter(project_code=deal_code).select_related("client").first()
        if deal is None:
            raise CommandError(f"Deal {deal_code!r} not found")
        keeper = User.objects.filter(username=keep_username).first()
        if keeper is None:
            raise CommandError(f"User {keep_username!r} not found")
        client = deal.client
        if client is None:
            raise CommandError(f"Deal {deal_code!r} has no client")

        with transaction.atomic():
            extra_deals = Deal.objects.exclude(pk=deal.pk)
            extra_deal_count = extra_deals.count()
            extra_deals.delete()
            extra_clients = Client.objects.exclude(pk=client.pk)
            extra_client_count = extra_clients.count()
            extra_clients.delete()
            self._reassign_users(keeper)
            extra_users = User.objects.exclude(pk=keeper.pk)
            extra_user_count = extra_users.count()
            extra_users.delete()

        removed_dirs = self._cleanup_files(client)
        self.stdout.write(
            self.style.SUCCESS(
                f"Kept deal #{deal.pk} {deal.project_code}, client #{client.pk} {client.full_name}, "
                f"user {keeper.username}. Deleted deals={extra_deal_count}, "
                f"clients={extra_client_count}, users={extra_user_count}, dirs={removed_dirs}."
            )
        )

    def _reassign_users(self, keeper):
        User = get_user_model()
        for model in apps.get_models():
            if model is User:
                continue
            for field in model._meta.get_fields():
                if not isinstance(field, (ForeignKey, OneToOneField)):
                    continue
                if field.remote_field.model is not User:
                    continue
                if field.auto_created and not field.concrete:
                    continue
                qs = model.objects.exclude(**{field.name: keeper}).exclude(**{f"{field.name}__isnull": True})
                qs.update(**{field.name: keeper})
            for field in model._meta.local_many_to_many:
                if not isinstance(field, ManyToManyField):
                    continue
                if field.remote_field.model is not User:
                    continue
                through = field.remote_field.through
                if through._meta.auto_created:
                    user_field_name = None
                    for through_field in through._meta.fields:
                        if isinstance(through_field, (ForeignKey, OneToOneField)) and through_field.remote_field.model is User:
                            user_field_name = through_field.name
                            break
                    if user_field_name:
                        through.objects.exclude(**{user_field_name: keeper}).delete()

    def _cleanup_files(self, client) -> int:
        files_root = get_files_root()
        clients_root = files_root / "clients"
        keep_dir = get_client_root(client).resolve()
        removed = 0
        if not clients_root.exists():
            return removed
        for child in clients_root.iterdir():
            if not child.is_dir():
                continue
            if child.resolve() != keep_dir:
                shutil.rmtree(child)
                removed += 1
        keep_projects = keep_dir / "projects"
        deal = Deal.objects.filter(client=client).first()
        if keep_projects.exists() and deal is not None:
            keep_name = f"{deal.id}-"
            for child in keep_projects.iterdir():
                if child.is_dir() and not child.name.startswith(keep_name):
                    shutil.rmtree(child)
                    removed += 1
        return removed
