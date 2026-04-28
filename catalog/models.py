from decimal import Decimal

from django.db import models


class Section(models.Model):
    class Kind(models.TextChoices):
        BATHROOM_TEMPLATE = 'bathroom_template', 'Шаблон наполнения санузла'

    code = models.CharField(max_length=100, unique=True)
    name_ru = models.CharField(max_length=255)
    kind = models.CharField(max_length=40, choices=Kind.choices)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'code')

    def __str__(self):
        return f'{self.code} — {self.name_ru}'


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

    class ItemKind(models.TextChoices):
        MATERIAL = 'material', 'Материал'
        WORK = 'work', 'Работа'
        MIXED = 'mixed', 'Смешанный'

    code = models.CharField(max_length=100, unique=True)
    name_ru = models.CharField(max_length=255)
    unit = models.CharField(max_length=20, choices=Unit.choices)
    category = models.CharField(max_length=20, choices=Category.choices)
    price_material = models.DecimalField(max_digits=12, decimal_places=2)
    price_work = models.DecimalField(max_digits=12, decimal_places=2)
    formula_multiplier = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    section = models.ForeignKey(
        Section,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='items',
    )
    kind = models.CharField(
        max_length=20,
        choices=ItemKind.choices,
        default=ItemKind.MIXED,
    )
    default_included = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('category', 'sort_order', 'name_ru')

    def __str__(self):
        return f'{self.code} - {self.name_ru}'


class CostItemOption(models.Model):
    """Варианты моделей/комплектаций для конкретного наименования каталога."""

    cost_item = models.ForeignKey(
        CostItem,
        on_delete=models.CASCADE,
        related_name='options',
    )
    code = models.CharField(max_length=100)
    name_ru = models.CharField(max_length=255)
    manufacturer = models.CharField(max_length=255, blank=True)
    article = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    unit = models.CharField(
        max_length=20,
        choices=CostItem.Unit.choices,
        blank=True,
    )
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    description = models.CharField(max_length=500, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'name_ru')
        constraints = [
            models.UniqueConstraint(fields=['cost_item', 'code'], name='uniq_cost_item_option_code'),
        ]

    def __str__(self):
        return f'{self.cost_item.name_ru} -> {self.name_ru}'
