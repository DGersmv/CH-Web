from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from system_settings.job_handlers import JOB_HANDLERS
from system_settings.models import PlatformJob


class Command(BaseCommand):
    help = 'Run pending platform jobs such as portal cleanup.'

    def handle(self, *args, **options):
        due_jobs = list(
            PlatformJob.objects.filter(
                status=PlatformJob.Status.PENDING,
                run_after__lte=timezone.now(),
            ).order_by('run_after', 'created_at')[:100],
        )

        if not due_jobs:
            self.stdout.write('No pending platform jobs.')
            return

        for job in due_jobs:
            self._run_job(job)

    def _run_job(self, job: PlatformJob):
        handler = JOB_HANDLERS.get(job.job_type)
        if handler is None:
            job.status = PlatformJob.Status.FAILED
            job.last_error = f'No handler for job type {job.job_type}'
            job.finished_at = timezone.now()
            job.save(update_fields=['status', 'last_error', 'finished_at'])
            self.stdout.write(self.style.ERROR(f'No handler: {job.job_type}'))
            return

        with transaction.atomic():
            job.status = PlatformJob.Status.RUNNING
            job.attempts += 1
            job.started_at = timezone.now()
            job.last_error = ''
            job.save(update_fields=['status', 'attempts', 'started_at', 'last_error'])

        try:
            result = handler(job)
        except Exception as error:  # noqa: BLE001
            job.status = PlatformJob.Status.FAILED
            job.last_error = str(error)
            job.finished_at = timezone.now()
            job.save(update_fields=['status', 'last_error', 'finished_at'])
            self.stdout.write(self.style.ERROR(f'FAILED {job.job_type}: {error}'))
            return

        job.status = PlatformJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.payload = {**job.payload, 'result': result or {}}
        job.save(update_fields=['status', 'finished_at', 'payload'])
        self.stdout.write(self.style.SUCCESS(f'SUCCEEDED {job.job_type}'))
