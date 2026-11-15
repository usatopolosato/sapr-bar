'''Описывает исходные данные без зависимости от интерфейса.'''

from dataclasses import dataclass
from decimal import Decimal, localcontext


@dataclass(frozen=True)
class Bar:
    '''Хранит параметры одного стержня в единицах СИ.

    Attributes:
        length_m: Длина в метрах.
        area_m2: Площадь поперечного сечения в квадратных метрах.
        modulus_pa: Модуль упругости в паскалях.
        allowable_stress_pa: Допускаемое напряжение в паскалях.
    '''

    length_m: Decimal
    area_m2: Decimal
    modulus_pa: Decimal
    allowable_stress_pa: Decimal


@dataclass(frozen=True)
class StructuralModel:
    '''Хранит последовательную цепочку стержней и внешние воздействия.

    Attributes:
        bars: Стержни в порядке слева направо.
        nodal_forces: Продольные силы в узлах в ньютонах.
        distributed_loads: Погонные нагрузки на стержнях в ньютонах на метр.
        supports: Признаки жёстких опор в узлах.
    '''

    bars: tuple[Bar, ...] = ()
    nodal_forces: tuple[Decimal, ...] = ()
    distributed_loads: tuple[Decimal, ...] = ()
    supports: tuple[bool, ...] = ()

    @property
    def node_positions_m(self) -> tuple[Decimal, ...]:
        '''Возвращает координаты узлов без округления исходных длин.'''
        if not self.bars:
            return ()
        values = tuple(bar.length_m for bar in self.bars)
        if not all(isinstance(value, Decimal) and value.is_finite() for value in values):
            raise ValueError('Координаты требуют конечных значений длины')
        precision = max(value.adjusted() for value in values)
        precision -= min(value.as_tuple().exponent for value in values)
        with localcontext() as context:
            context.prec = max(28, precision + len(str(len(values))) + 3)
            positions = [Decimal('0')]
            for value in values:
                positions.append(positions[-1] + value)
        return tuple(positions)

    @property
    def total_length_m(self) -> Decimal:
        '''Возвращает полную длину цепочки в метрах.'''
        positions = self.node_positions_m
        return positions[-1] if positions else Decimal('0')

    @property
    def left_support(self) -> bool:
        '''Возвращает наличие опоры в первом узле.'''
        return bool(self.supports and self.supports[0])

    @property
    def right_support(self) -> bool:
        '''Возвращает наличие опоры в последнем узле.'''
        return bool(self.supports and self.supports[-1])


def demo_model() -> StructuralModel:
    '''Создаёт демонстрационную конструкцию для начального экрана.'''
    return StructuralModel(
        bars=(
            Bar(Decimal('2'), Decimal('8e-4'), Decimal('2.1e11'), Decimal('1.6e8')),
            Bar(Decimal('3'), Decimal('1.4e-3'), Decimal('2.1e11'), Decimal('1.6e8')),
            Bar(Decimal('1'), Decimal('1e-3'), Decimal('2.1e11'), Decimal('1.6e8')),
        ),
        nodal_forces=(Decimal('0'), Decimal('-6000'), Decimal('0'), Decimal('12000')),
        distributed_loads=(Decimal('0'), Decimal('2000'), Decimal('0')),
        supports=(True, False, False, False),
    )
