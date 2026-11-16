'''Объясняет исключение коэффициентов с подстановкой фактических чисел.'''

from ...domain.elimination import ForwardElimination
from ...domain.processor import ProcessorResult
from ..math_notation import formula_html
from .linear_system import number_text


class ForwardEliminationDetails:
    '''Готовит пояснение выбранной строки в кратком или точном формате.

    Args:
        result: Завершённый расчёт в арифметике Decimal.
        compact: Признак округления только отображаемых чисел.
    '''

    def __init__(self, result: ProcessorResult, compact: bool) -> None:
        self.trace = ForwardElimination(result)
        self.compact = compact

    def details(self, row: int) -> str:
        '''Показывает множитель, преобразование строки и новое уравнение.'''
        step = self.trace.step(row)
        node, previous = row + 1, row
        text = lambda value: number_text(value, self.compact)
        factor = text(step.factor)
        lines = [f'Исключаем Δ{previous} из уравнения узла {node}',
                 f'Опорная строка {previous}   Изменяемая строка {node}',
                 f'm = A{node},{previous} / A{previous},{previous}'
                 f' = ({text(step.lower)}) / ({text(step.pivot)}) = {factor}']
        if not step.lower:
            lines.append(f'A{node},{previous} уже равен 0 после закреплений. Строка не меняется')
        else:
            lines.extend((
                f'Строка {node} = Строка {node} - ({factor}) * Строка {previous}',
                f'Обнуление   A{node},{previous}: ({text(step.lower)}) - ({factor}) * ({text(step.pivot)}) = 0',
                f'Диагональ   A{node},{node}: ({text(step.diagonal_before)}) - ({factor})'
                f' * ({text(step.pivot_upper)}) = {text(step.diagonal_after)}',
                f'Правая часть   b{node}: ({text(step.rhs_before)}) - ({factor})'
                f' * ({text(step.pivot_rhs)}) = {text(step.rhs_after)}',
            ))
        terms = []
        for column, value in self.trace.result.eliminated.row_terms(row):
            sign = (' - ' if value < 0 else ' + ') if terms else ('-' if value < 0 else '')
            terms.append(f'{sign}{text(value.copy_abs())} * Δ{column + 1}')
        lines.extend(('После шага', ''.join(terms) + ' = ' + text(step.rhs_after)))
        return '\n'.join(lines)

    def details_html(self, row: int) -> str:
        '''Оформляет коэффициенты и перемещения нижними индексами.'''
        return formula_html(self.details(row))
