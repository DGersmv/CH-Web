from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MANAGER = 'manager', 'Manager'
        DESIGNER = 'designer', 'Designer'
        ADMIN = 'admin', 'Admin'
        HEAD = 'head', 'Head'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MANAGER,
    )
