'''Проверяет расчёт по аналитическим задачам и сохранение точности.'''

from decimal import Decimal, FloatOperation, localcontext

import pytest

from src.sapr.domain import Bar, ModelValidationError, StructuralModel
from src.sapr.domain.processor import AxialProcessor


D = Decimal


def model(lengths, areas, forces, loads, supports, modulus='1'):
    '''Создаёт задачу в СИ из строковых или целых исходных значений.'''
    bars = tuple(Bar(D(length), D(area), D(modulus), D('1000')) for length, area in zip(lengths, areas))
    return StructuralModel(bars, tuple(map(D, forces)), tuple(map(D, loads)), tuple(supports))


@pytest.mark.parametrize(('data', 'expected'), [
    (model([3, 2], [2, 3], [0, 26, 0], [0, 0], [True, False, True]), ['0', '12', '0']),
    (model([2, 1], [1, 2], [0, -4, 0], [1, 0], [True, False, True]), ['0', '-1.2', '0']),
    (model([2, 1], [2, 1], [0, -2, 0], [0, 1], [True, False, False]), ['0', '-1', '-0.5']),
    (model([1, 2, 2, 1], [1, 2, 2, 1], [0, 0, 1, 0, 0], [1, 0, 0, -1],
           [True, False, False, False, True]), ['0', '0.75', '1', '0.25', '0']),
    (model([2], [3], [0, 12], [0], [True, False], modulus='4'), ['0', '2']),
    (model([2], [3], [12, 0], [0], [False, True], modulus='4'), ['2', '0']),
    (model([1, 1], [1, 1], [2, 0, 3], [0, 0], [False, True, False]), ['2', '0', '3']),
    (model([2], [1], [9, -2], [3], [True, True]), ['0', '0']),
    (model([2], [1], [0, 0], [0], [True, False]), ['0', '0']),
])
def test_analytic_displacements(data, expected):
    '''Сравнивает перемещения с независимыми ответами лекции и простых задач.'''
    with localcontext() as context:
        context.traps[FloatOperation] = True
        result = AxialProcessor().solve(data)
    for actual, answer in zip(result.displacements, map(D, expected)):
        assert abs(actual - answer) < D('1e-40')
        assert isinstance(actual, D)


def test_boundary_rows_and_original_forces_are_preserved():
    '''Проверяет единицы на закреплениях и сохранение нагрузок для реакций.'''
    result = AxialProcessor().solve(model([2, 1], [1, 2], [7, -4, 9], [1, 0], [True, False, True]))
    assert result.original.diagonal == (D('0.5'), D('2.5'), D('2'))
    assert result.original.upper == (D('-0.5'), D('-2'))
    assert result.original.rhs == (D('8'), D('-3'), D('9'))
    assert result.constrained.diagonal == (D('1'), D('2.5'), D('1'))
    assert result.constrained.upper == result.constrained.lower == (D('0'), D('0'))
    assert result.constrained.rhs == (D('0'), D('-3'), D('0'))
    assert result.reactions == (D('-7.4'), D('0'), D('-6.6'))


def test_precision_ignores_callers_small_context():
    '''Сохраняет длинные данные и устойчивость при большом различии жёсткостей.'''
    data = model([1, 1], ['1e100', '1'], [0, 0, '1.23456789012345678901234567890123456789'],
                 [0, 0], [True, False, False])
    with localcontext() as context:
        context.prec = 6
        context.traps[FloatOperation] = True
        result = AxialProcessor().solve(data)
        assert context.prec == 6
    assert result.displacements[1] == D('1.23456789012345678901234567890123456789e-100')
    with localcontext() as context:
        context.prec = result.precision
        assert result.displacements[2] == data.nodal_forces[2] + result.displacements[1]


def test_missing_support_is_rejected():
    '''Не решает вырожденную конструкцию без закреплений.'''
    with pytest.raises(ModelValidationError):
        AxialProcessor().solve(model([1], [1], [0, 1], [0], [False, False]))


def test_large_chain_uses_linear_storage_and_correct_solution():
    '''Проверяет 10000 стержней без квадратного массива коэффициентов.'''
    count = 10000
    data = model([1] * count, [1] * count, [0] * count + [1], [0] * count, [True] + [False] * count)
    result = AxialProcessor().solve(data)
    assert abs(result.displacements[-1] - D(count)) < D('1e-40')
    for system in (result.original, result.constrained, result.eliminated):
        assert len(system.diagonal) + len(system.upper) + len(system.lower) == 3 * count + 1
        assert system.coefficient(0, count) == 0
    assert result.eliminated.lower == (D(0),) * count
