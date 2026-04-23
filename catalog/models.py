from django.db import models


class CostItem(models.Model):
    class Unit(models.TextChoices):
        SQM = 'sqm', 'Square meter'
        LM = 'lm', 'Linear meter'
        PCS = 'pcs', 'Pieces'
        COMPLEX = 'complex', 'Complex'
        RUBLES = 'rubles', 'Rubles'

    class Category(models.TextChoices):
        FLOORS = 'floors', 'Floors'
        WALLS = 'walls', 'Walls'
        OPENINGS = 'openings', 'Openings'
        ROOF = 'roof', 'Roof'
        BATHROOM = 'bathroom', 'Bathroom'
        ENGINEERING = 'engineering', 'Engineering'
        OVERHEAD = 'overhead', 'Overhead'
        ADDITIONAL = 'additional', 'Additional'

    code = models.CharField(max_length=100, unique=True)
    name_ru = models.CharField(max_length=255)
    unit = models.CharField(max_length=20, choices=Unit.choices)
    category = models.CharField(max_length=20, choices=Category.choices)
    price_material = models.DecimalField(max_digits=12, decimal_places=2)
    price_work = models.DecimalField(max_digits=12, decimal_places=2)
    formula_multiplier = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.code} - {self.name_ru}'
