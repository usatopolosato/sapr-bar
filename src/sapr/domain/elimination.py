'''Восстанавливает отдельные шаги прямого хода из результата прогонки.'''

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

from .processor import LinearSystem, ProcessorResult, ZERO


@dataclass(frozen=True, slots=True)
class EliminationStep:
    '''Описывает исключение коэффициента под диагональю одной строки.'''

    row: int
    factor: Decimal
    pivot: Decimal
    pivot_upper: Decimal
    pivot_rhs: Decimal
    lower: Decimal
    diagonal_before: Decimal
    rhs_before: Decimal
    diagonal_after: Decimal
    rhs_after: Decimal


class ForwardElimination:
    '''Предоставляет шаги без повторного решения и хранения истории матриц.

    Args:
        result: Согласованные системы до и после прямого хода.
    '''

    def __init__(self, result: ProcessorResult) -> None:
        self.result = result

    def step(self, row: int) -> EliminationStep:
        '''Возвращает коэффициенты операции над строкой с индексом от единицы.

        Args:
            row: Индекс строки с нуля, исключение начинается со второй строки.

        Returns:
            Точные значения в рабочем контексте Decimal процессора.

        Raises:
            ValueError: Строка не соответствует шагу исключения.
        '''
        source, final = self.result.constrained, self.result.eliminated
        if type(row) is not int or not 1 <= row < len(source.diagonal):
            raise ValueError('Прямой ход начинается со второй строки')
        with localcontext(Context(prec=self.result.precision)):
            factor = source.lower[row - 1] / final.diagonal[row - 1]
        return EliminationStep(row, factor, final.diagonal[row - 1], source.upper[row - 1],
                               final.rhs[row - 1], source.lower[row - 1], source.diagonal[row],
                               source.rhs[row], final.diagonal[row], final.rhs[row])

    def system_after(self, completed: int) -> LinearSystem:
        '''Создаёт только выбранное состояние в формате трёх диагоналей.

        Args:
            completed: Число выполненных исключений от нуля до числа узлов минус один.

        Returns:
            Система с обработанным префиксом строк и исходным остатком.

        Raises:
            ValueError: Число шагов выходит за границы расчёта.
        '''
        source, final = self.result.constrained, self.result.eliminated
        count = len(source.diagonal)
        if type(completed) is not int or not 0 <= completed < count:
            raise ValueError('Число шагов вне диапазона прямого хода')
        if completed == 0:
            return source
        if completed == count - 1:
            return final
        boundary = completed + 1
        return LinearSystem(final.diagonal[:boundary] + source.diagonal[boundary:],
                            (ZERO,) * completed + source.lower[completed:], source.upper,
                            final.rhs[:boundary] + source.rhs[boundary:])
