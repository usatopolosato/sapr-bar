'''Задаёт общую сетку сечений для таблицы и отчёта без хранения всех точек.'''

from bisect import bisect_left
from decimal import Context, Decimal, ROUND_CEILING, localcontext

from .postprocessor import BarResponse


class BarSamples:
    '''Индексирует равномерные отсчёты и аналитические характерные точки.

    Args:
        bar: Аналитическое решение одного стержня.
        subdivisions: Число интервалов при равномерном разбиении.
        step: Шаг в метрах, заменяющий число интервалов.
        extrema_only: Выводить только уникальные координаты экстремумов.
    '''

    MAX_ROWS = 20000000

    def __init__(self, bar: BarResponse, subdivisions: int = 10, *,
                 step: Decimal | None = None, extrema_only: bool = False) -> None:
        if type(subdivisions) is not int or not 1 <= subdivisions <= 1000:
            raise ValueError('Число разбиений должно быть от 1 до 1000')
        if step is not None and (not isinstance(step, Decimal) or not step.is_finite() or step <= 0):
            raise ValueError('Шаг должен быть конечным числом больше нуля')
        self.bar = bar
        self.step = step
        self.extrema_only = extrema_only
        self.intervals = subdivisions
        with localcontext(Context(prec=bar.precision)):
            if extrema_only:
                self.extras = tuple(sorted({point.x_m for component in ('N', 'sigma', 'u')
                                            for point in bar.extrema(component)}))
                self.extra_rows = ()
                self.count = len(self.extras)
                return
            if step is not None:
                ratio = bar.geometry.length_m / step
                if ratio > self.MAX_ROWS - 8:
                    raise ValueError('Слишком маленький шаг. Увеличьте шаг таблицы')
                self.intervals = int(ratio.to_integral_value(rounding=ROUND_CEILING))
            self.extras = tuple(x for x in bar.critical_positions() if not self._on_grid(x))
            self.extra_rows = tuple(int(self._grid_index(x)) + 1 + i for i, x in enumerate(self.extras))
            self.count = self.intervals + 1 + len(self.extras)

    def _grid_index(self, x: Decimal) -> Decimal:
        '''Возвращает дробный номер равномерного отсчёта.'''
        return x / self.step if self.step is not None else x * self.intervals / self.bar.geometry.length_m

    def _grid_x(self, index: int) -> Decimal:
        '''Включает конец стержня при неполном последнем интервале.'''
        length = self.bar.geometry.length_m
        return min(length, self.step * index) if self.step is not None else length * index / self.intervals

    def _on_grid(self, x: Decimal) -> bool:
        '''Проверяет совпадение характерной точки с узлом равномерной сетки.'''
        if x == self.bar.geometry.length_m:
            return True
        index = int(self._grid_index(x).to_integral_value())
        return self._grid_x(index) == x

    def position(self, row: int) -> Decimal:
        '''Возвращает точную локальную координату строки по её индексу.'''
        if not 0 <= row < self.count:
            raise IndexError('Строка таблицы находится вне диапазона')
        if self.extrema_only:
            return self.extras[row]
        extra = bisect_left(self.extra_rows, row)
        if extra < len(self.extra_rows) and self.extra_rows[extra] == row:
            return self.extras[extra]
        with localcontext(Context(prec=self.bar.precision)):
            return self._grid_x(row - extra)
