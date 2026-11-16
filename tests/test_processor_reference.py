'''Сверяет процессор с эталонными задачами и независимым точным расчётом.'''

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from random import Random

import pytest

from src.sapr.domain import Bar, StructuralModel
from src.sapr.domain.processor import AxialProcessor
from src.sapr.storage import ProjectStore


D = Decimal


@dataclass(frozen=True)
class ReferenceCase:
    '''Описывает безразмерные параметры и эталонное решение задачи.'''

    name: str
    lengths: tuple
    areas: tuple
    forces: tuple
    loads: tuple
    supports: tuple
    displacements: tuple
    reactions: tuple
    distributed: bool = False


CASES = (
    ReferenceCase('example_1', (3, 2), (2, 3), (0, 26, 0), (0, 0), (True, False, True),
                  (0, 12, 0), (-8, 0, -18)),
    ReferenceCase('example_2', (1, 2, 1), (3, 2, 1), (0, 3, 1, 0), (0, 0, 0), (True, False, False, True),
                  (0, 1, 1, 0), (-3, 0, 0, -1)),
    ReferenceCase('example_3', (2, 1), (1, 2), (0, -4, 0), (1, 0), (True, False, True),
                  (0, '-1.2', 0), ('-0.4', 0, '2.4'), True),
    ReferenceCase('example_4', (2, 1), (2, 1), (0, -2, 0), (0, 1), (True, False, False),
                  (0, -1, '-0.5'), (1, 0, 0), True),
    ReferenceCase('example_5', (1, 2, 2, 1), (1, 2, 2, 1), (0, 0, 1, 0, 0), (1, 0, 0, -1),
                  (True, False, False, False, True), (0, '0.75', 1, '0.25', 0), ('-1.25', 0, 0, 0, '0.25'), True),
    ReferenceCase('example_6', (2, 4), (2, 1), (0, 0, 0), (9, -2), (True, False, True),
                  (0, 4, 0), (-13, 0, 3), True),
    ReferenceCase('simple_1', (1,), (1,), (0, 1), (0,), (True, False), (0, 1), (-1, 0)),
    ReferenceCase('simple_2', (1,), (1,), (1, 0), (0,), (False, True), (1, 0), (0, -1)),
    ReferenceCase('simple_3', (1,), (1,), (0, 0), (1,), (True, False), (0, '0.5'), (-1, 0), True),
    ReferenceCase('simple_4', (1,), (1,), (0, 0), (1,), (True, True), (0, 0), ('-0.5', '-0.5'), True),
    ReferenceCase('simple_5', (1, 1), (1, 1), (0, 0, 0), (1, -1), (True, False, True),
                  (0, 0, 0), ('-0.5', 0, '0.5'), True),
)


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.name)
@pytest.mark.parametrize('scale', [('1', '1', '1', '1', '1'), ('2.1e11', '8e-4', '0.7', '12500', '2300')],
                         ids=['unit', 'si'])
def test_reference_cases_through_checked_project_files(tmp_path, case, scale):
    '''Сверяет все узловые перемещения и реакции после чтения CNX и LDX.

    Проверяет узловое решение для цепочек стержней и отдельных стержней
    в безразмерном представлении и единицах СИ.
    '''
    with localcontext() as context:
        context.prec = 100
        modulus, area, length, force, q = map(D, scale)
        force_scale = q * length if case.distributed else force
        displacement_scale = force_scale * length / (modulus * area)
        model = StructuralModel(
            tuple(Bar(D(l) * length, D(a) * area, modulus, D('1.6e8')) for l, a in zip(case.lengths, case.areas)),
            tuple(D(f) * force_scale for f in case.forces),
            tuple(D(value) * q for value in case.loads), case.supports,
        )
        store = ProjectStore()
        project = store.create(tmp_path, case.name)
        project = store.save(project, model, validate=True)
        prepared, _ = store.read_for_processor(project)
        result = AxialProcessor().solve(prepared)
        for index, coefficient in enumerate(case.displacements):
            expected = D(coefficient) * displacement_scale
            assert abs(result.displacements[index] - expected) <= max(abs(displacement_scale), D('1e-100')) * D('1e-40')
        for index, coefficient in enumerate(case.reactions):
            expected = D(coefficient) * force_scale
            assert abs(result.reactions[index] - expected) <= force_scale * D('1e-40')


def equilibrium_solution(model: StructuralModel) -> tuple[Fraction, ...]:
    '''Находит перемещения интегрированием N / EA без сборки матрицы.

    На пролёте между закреплениями неизвестная начальная сила находится
    из нулевого суммарного удлинения. На свободных концах она определяется
    равновесием нагрузок. Дроби Fraction дают независимый точный ответ.
    '''
    count = len(model.bars)
    lengths = [Fraction(bar.length_m) for bar in model.bars]
    rigidity = [Fraction(bar.area_m2) * Fraction(bar.modulus_pa) for bar in model.bars]
    forces = list(map(Fraction, model.nodal_forces))
    loads = list(map(Fraction, model.distributed_loads))
    fixed = [index for index, enabled in enumerate(model.supports) if enabled]
    displacement = [Fraction(0)] * (count + 1)

    def integrate(start, end, initial):
        '''Интегрирует деформации последовательно от заданного конца.'''
        value, axial = Fraction(0), initial
        values = [value]
        for bar in range(start, end):
            length = lengths[bar]
            value += (axial * length - loads[bar] * length ** 2 / 2) / rigidity[bar]
            values.append(value)
            axial -= loads[bar] * length + forces[bar + 1]
        return values

    if fixed[0] > 0:
        values = integrate(0, fixed[0], -forces[0])
        displacement[:fixed[0] + 1] = [value - values[-1] for value in values]
    for start, end in zip(fixed, fixed[1:]):
        flexibility = sum((lengths[i] / rigidity[i] for i in range(start, end)), Fraction(0))
        initial = -integrate(start, end, Fraction(0))[-1] / flexibility
        displacement[start:end + 1] = integrate(start, end, initial)
    if fixed[-1] < count:
        start = fixed[-1]
        initial = sum(forces[start + 1:], Fraction(0))
        initial += sum((loads[i] * lengths[i] for i in range(start, count)), Fraction(0))
        displacement[start:] = integrate(start, count, initial)
    return tuple(displacement)


@pytest.mark.parametrize('seed', range(100))
def test_against_independent_equilibrium_and_strain_integral(seed):
    '''Сверяет разные сечения, модули, знаки нагрузок и внутренние закрепления.'''
    random = Random(seed)
    count = random.randint(1, 12)
    bars = tuple(Bar(D(random.randint(1, 6)), D(random.randint(1, 7)), D(random.randint(50, 500)), D(1000))
                 for _ in range(count))
    supports = [random.randrange(4) == 0 for _ in range(count + 1)]
    supports[random.randrange(count + 1)] = True
    model = StructuralModel(bars, tuple(D(random.randint(-20, 20)) for _ in supports),
                            tuple(D(random.randint(-10, 10)) for _ in bars), tuple(supports))
    expected = equilibrium_solution(model)
    result = AxialProcessor().solve(model)
    with localcontext() as context:
        context.prec = 100
        for actual, exact in zip(result.displacements, expected):
            reference = D(exact.numerator) / D(exact.denominator)
            assert abs(actual - reference) <= max(abs(reference), D(1)) * D('1e-40')
