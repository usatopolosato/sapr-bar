'''Описывает неизменяемый пример для демонстрации интерфейса.'''

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PreviewBar:
    '''Хранит геометрию и материал демонстрационного стержня.

    Attributes:
        length_m: Длина в метрах.
        area_m2: Площадь сечения в квадратных метрах.
        modulus_pa: Модуль упругости в паскалях.
        allowable_stress_pa: Допускаемое напряжение в паскалях.
    '''

    length_m: Decimal
    area_m2: Decimal
    modulus_pa: Decimal = Decimal('2.1e11')
    allowable_stress_pa: Decimal = Decimal('1.6e8')


@dataclass(frozen=True)
class PreviewLoad:
    '''Хранит демонстрационную нагрузку в единицах СИ.

    Attributes:
        kind: Название вида нагрузки.
        element: Название нагруженного элемента.
        value_si: Значение в ньютонах или ньютонах на метр.
        unit: Подпись единицы СИ.
    '''

    kind: str
    element: str
    value_si: Decimal
    unit: str


PREVIEW_BARS = (
    PreviewBar(length_m=Decimal('2'), area_m2=Decimal('8e-4')),
    PreviewBar(length_m=Decimal('3'), area_m2=Decimal('1.4e-3')),
    PreviewBar(length_m=Decimal('1'), area_m2=Decimal('1e-3')),
)

PREVIEW_LOADS = (
    PreviewLoad('Узловая', 'Узел 02', Decimal('-6000'), 'Н'),
    PreviewLoad('Узловая', 'Узел 04', Decimal('12000'), 'Н'),
    PreviewLoad('Погонная', 'Стержень 02', Decimal('2000'), 'Н на м'),
)
