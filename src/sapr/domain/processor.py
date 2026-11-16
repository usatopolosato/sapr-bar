'''Решает осевую задачу методом прогонки в десятичной арифметике.'''

from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, localcontext
from itertools import chain

from .model import StructuralModel
from .validation import ModelValidationError, validate_model


ZERO = Decimal('0')
ONE = Decimal('1')
TWO = Decimal('2')
TOLERANCE = Decimal('1e-24')


class CalculationError(ValueError):
    '''Сообщает о невозможности получить достоверное решение.'''


@dataclass(frozen=True, slots=True)
class LinearSystem:
    '''Хранит систему A * delta = b в разреженном диагональном формате.

    В памяти находятся только три ленты коэффициентов. Элементы вне лент
    вычисляются по запросу интерфейса и никогда не образуют плотный массив.

    Attributes:
        diagonal: Главная диагональ.
        lower: Диагональ под главной, длина на единицу меньше.
        upper: Диагональ над главной, длина на единицу меньше.
        rhs: Правая часть системы.
    '''

    diagonal: tuple[Decimal, ...]
    lower: tuple[Decimal, ...]
    upper: tuple[Decimal, ...]
    rhs: tuple[Decimal, ...]

    def coefficient(self, row: int, column: int) -> Decimal:
        '''Возвращает элемент полной матрицы по индексам с нуля.'''
        if row == column:
            return self.diagonal[row]
        if row == column + 1:
            return self.lower[column]
        if column == row + 1:
            return self.upper[row]
        return ZERO

    def row_terms(self, row: int) -> tuple[tuple[int, Decimal], ...]:
        '''Возвращает ненулевые коэффициенты строки с номерами столбцов.'''
        terms = []
        if row and self.lower[row - 1]:
            terms.append((row - 1, self.lower[row - 1]))
        if self.diagonal[row]:
            terms.append((row, self.diagonal[row]))
        if row < len(self.upper) and self.upper[row]:
            terms.append((row + 1, self.upper[row]))
        return tuple(terms)


@dataclass(frozen=True, slots=True)
class ProcessorResult:
    '''Хранит неизменяемые этапы решения и результат в СИ.

    Attributes:
        model: Проверенная расчётная модель.
        stiffnesses: Жёсткости стержней в Н/м.
        end_loads: Эквивалентные нагрузки на один конец каждого стержня в Н.
        original: Система до учёта закреплений.
        constrained: Система после учёта закреплений.
        eliminated: Система после прямого хода прогонки.
        displacements: Вектор перемещений узлов в м.
        reactions: Реакции в закреплённых узлах в Н, нули в свободных.
        relative_residual: Максимальная относительная невязка свободных узлов.
        precision: Число значащих десятичных цифр расчёта.
    '''

    model: StructuralModel
    stiffnesses: tuple[Decimal, ...]
    end_loads: tuple[Decimal, ...]
    original: LinearSystem
    constrained: LinearSystem
    eliminated: LinearSystem
    displacements: tuple[Decimal, ...]
    reactions: tuple[Decimal, ...]
    relative_residual: Decimal
    precision: int


class AxialProcessor:
    '''Собирает систему, учитывает закрепления и контролирует решение.'''

    def solve(self, model: StructuralModel) -> ProcessorResult:
        '''Рассчитывает перемещения без преобразования величин в float.

        Args:
            model: Последовательная конструкция с нулевыми закреплениями.

        Returns:
            Все этапы системы и вычисленный вектор перемещений.

        Raises:
            ModelValidationError: Модель не удовлетворяет условиям задачи.
            CalculationError: Не удалось достичь расчётной точности.
        '''
        issues = validate_model(model)
        if issues:
            raise ModelValidationError(issues)
        precision = self._precision(model)
        try:
            with localcontext(Context(prec=precision)):
                stiffnesses = tuple(bar.modulus_pa * bar.area_m2 / bar.length_m for bar in model.bars)
                end_loads = tuple(q * bar.length_m / TWO for q, bar in zip(model.distributed_loads, model.bars))
                original = self._assemble(model, stiffnesses, end_loads)
                constrained = self._constrain(original, model.supports)
                eliminated, displacements = self._eliminate(constrained)
                reactions, residual = self._check(model, original, displacements)
                return ProcessorResult(model, stiffnesses, end_loads, original, constrained,
                                       eliminated, displacements, reactions, residual, precision)
        except DecimalException as error:
            raise CalculationError('Числовой диапазон задачи превышает возможности расчёта') from error

    @staticmethod
    def _precision(model: StructuralModel) -> int:
        '''Выбирает точность с запасом для различающихся жёсткостей и нагрузок.'''
        values = tuple(value for bar in model.bars for value in
                       (bar.length_m, bar.area_m2, bar.modulus_pa))
        values += model.nodal_forces + model.distributed_loads
        digits = max(len(value.as_tuple().digits) for value in values)
        orders = [bar.modulus_pa.adjusted() + bar.area_m2.adjusted() - bar.length_m.adjusted()
                  for bar in model.bars]
        loads = [value.adjusted() for value in model.nodal_forces if value]
        loads += [q.adjusted() + bar.length_m.adjusted()
                  for q, bar in zip(model.distributed_loads, model.bars) if q]
        spread = max(orders) - min(orders)
        if loads:
            spread += max(loads) - min(loads)
        precision = max(60, 3 * digits + spread + 30 + len(str(len(model.bars))))
        if precision > 20000:
            raise CalculationError('Слишком большой разброс величин для надёжного расчёта')
        return precision

    @staticmethod
    def _assemble(model, stiffnesses, end_loads) -> LinearSystem:
        '''Складывает вклады каждого стержня и внешние узловые силы.'''
        diagonal = [ZERO] * len(model.supports)
        rhs = list(model.nodal_forces)
        for index, (stiffness, load) in enumerate(zip(stiffnesses, end_loads)):
            diagonal[index] += stiffness
            diagonal[index + 1] += stiffness
            rhs[index] += load
            rhs[index + 1] += load
        adjacent = tuple(-value for value in stiffnesses)
        return LinearSystem(tuple(diagonal), adjacent, adjacent, tuple(rhs))

    @staticmethod
    def _constrain(system: LinearSystem, supports: tuple[bool, ...]) -> LinearSystem:
        '''Обнуляет строки и столбцы опор, оставляя единицу на диагонали.'''
        diagonal, rhs = list(system.diagonal), list(system.rhs)
        adjacent = list(system.upper)
        for index, fixed in enumerate(supports):
            if fixed:
                diagonal[index], rhs[index] = ONE, ZERO
                if index:
                    adjacent[index - 1] = ZERO
                if index < len(adjacent):
                    adjacent[index] = ZERO
        adjacent = tuple(adjacent)
        return LinearSystem(tuple(diagonal), adjacent, adjacent, tuple(rhs))

    @staticmethod
    def _eliminate(system: LinearSystem) -> tuple[LinearSystem, tuple[Decimal, ...]]:
        '''Выполняет прямой и обратный ход прогонки за линейное время.'''
        diagonal, rhs = list(system.diagonal), list(system.rhs)
        count = len(diagonal)
        for index in range(1, count):
            if diagonal[index - 1] <= ZERO:
                raise CalculationError('Система не имеет устойчивого единственного решения')
            if system.lower[index - 1]:
                factor = system.lower[index - 1] / diagonal[index - 1]
                diagonal[index] -= factor * system.upper[index - 1]
                rhs[index] -= factor * rhs[index - 1]
        if diagonal[-1] <= ZERO:
            raise CalculationError('Система не имеет устойчивого единственного решения')
        displacement = [ZERO] * count
        displacement[-1] = rhs[-1] / diagonal[-1]
        for index in range(count - 2, -1, -1):
            displacement[index] = (rhs[index] - system.upper[index] * displacement[index + 1]) / diagonal[index]
        eliminated = LinearSystem(tuple(diagonal), (ZERO,) * (count - 1), system.upper, tuple(rhs))
        return eliminated, tuple(displacement)

    @staticmethod
    def _check(model, system, displacement) -> tuple[tuple[Decimal, ...], Decimal]:
        '''Проверяет невязку, закрепления и суммарный баланс сил.'''
        reactions = []
        residual = ZERO
        for index, fixed in enumerate(model.supports):
            total = system.diagonal[index] * displacement[index]
            scale = abs(system.rhs[index]) + abs(total)
            if index:
                term = system.lower[index - 1] * displacement[index - 1]
                total += term
                scale += abs(term)
            if index < len(system.upper):
                term = system.upper[index] * displacement[index + 1]
                total += term
                scale += abs(term)
            difference = total - system.rhs[index]
            if not displacement[index].is_finite() or (fixed and displacement[index] != ZERO):
                raise CalculationError('Не выполнены условия закрепления узлов')
            if fixed:
                reactions.append(difference)
            else:
                reactions.append(ZERO)
                relative = abs(difference) / scale if scale else abs(difference)
                residual = max(residual, relative)
        loads = (q * bar.length_m for q, bar in zip(model.distributed_loads, model.bars))
        total, scale = ZERO, ZERO
        for force in chain(reactions, model.nodal_forces, loads):
            total += force
            scale += abs(force)
        balance = abs(total) / scale if scale else ZERO
        if residual > TOLERANCE or balance > TOLERANCE:
            raise CalculationError('Не достигнута точность решения. Проверьте диапазон исходных величин')
        return tuple(reactions), residual
