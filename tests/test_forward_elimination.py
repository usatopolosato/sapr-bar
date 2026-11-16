'''Проверяет числовые шаги исключения и их представление пользователю.'''

from decimal import Context, Decimal as D, localcontext

import pytest

from src.sapr.domain import Bar, StructuralModel
from src.sapr.domain.elimination import ForwardElimination
from src.sapr.domain.processor import AxialProcessor
from src.sapr.ui.widgets.forward_elimination import ForwardEliminationDetails


def example_result():
    '''Рассчитывает два одинаковых стержня с закреплённым первым узлом.'''
    bar = Bar(D(2), D('1e-3'), D('2e11'), D('1e8'))
    model = StructuralModel((bar, bar), (D(0), D(0), D(1000)), (D(0), D(0)), (True, False, False))
    return AxialProcessor().solve(model)


def test_explained_example_matches_both_matrix_states():
    '''Повторяет ручное обнуление минус 1e8 множителем минус 0.5.'''
    result = example_result()
    trace = ForwardElimination(result)
    assert trace.system_after(0) is result.constrained
    assert trace.system_after(2) is result.eliminated
    assert trace.step(1).factor == 0
    assert trace.system_after(1) == result.constrained
    step = trace.step(2)
    assert (step.lower, step.pivot, step.factor) == (D('-1e8'), D('2e8'), D('-0.5'))
    assert (step.diagonal_before, step.diagonal_after) == (D('1e8'), D('5e7'))
    assert step.rhs_before == step.rhs_after == D(1000)
    assert trace.system_after(1).coefficient(2, 1) == D('-1e8')
    assert trace.system_after(2).coefficient(2, 1) == 0
    assert result.displacements == (D(0), D('1e-5'), D('2e-5'))
    details = ForwardEliminationDetails(result, True)
    assert 'Строка 3 = Строка 3 - (-0.5) * Строка 2' in details.details(2)
    assert '(-1e8) - (-0.5) * (2e8) = 0' in details.details(2)
    assert '5e7 * Δ3 = 1000' in details.details(2)
    assert 'уже равен 0 после закреплений' in details.details(1)
    assert '<sub>32</sub>' in details.details_html(2)


@pytest.mark.parametrize('supports', [(True, False, False, False), (False, False, False, True),
                                     (True, False, False, True), (False, True, False, False),
                                     (True, True, True, True)])
@pytest.mark.parametrize('sign', [1, -1])
def test_each_snapshot_matches_independent_row_elimination(supports, sign):
    '''Сравнивает каждый шаг с прямым преобразованием маленькой полной матрицы.'''
    bars = tuple(Bar(D(length), D('0.001'), D('2e11'), D('1e8')) for length in (2, 3, 5))
    model = StructuralModel(bars, tuple(D(sign * value) for value in (300, 1500, -700, 2000)),
                            tuple(D(sign * value) for value in (400, -300, 600)), supports)
    result = AxialProcessor().solve(model)
    trace = ForwardElimination(result)
    dense = [[result.constrained.coefficient(i, j) for j in range(4)] for i in range(4)]
    rhs = list(result.constrained.rhs)
    with localcontext(Context(prec=result.precision)):
        for row in range(1, 4):
            factor = dense[row][row - 1] / dense[row - 1][row - 1]
            assert trace.step(row).factor == factor
            for column in range(row, 4):
                dense[row][column] -= factor * dense[row - 1][column]
            dense[row][row - 1] = D(0)
            rhs[row] -= factor * rhs[row - 1]
            snapshot = trace.system_after(row)
            assert snapshot.rhs == tuple(rhs)
            assert [[snapshot.coefficient(i, j) for j in range(4)] for i in range(4)] == dense
            assert snapshot.upper is result.constrained.upper


def test_details_keep_eliminated_rhs_and_full_decimal_precision():
    '''Использует уже преобразованную опорную строку при изменении правой части.'''
    bar = Bar(D(1), D(1), D(3), D(10))
    force = D('1.2345678901234567890123456789')
    model = StructuralModel((bar,) * 3, (D(0), force, D(2), D(3)), (D(0),) * 3, (True, False, False, False))
    result = AxialProcessor().solve(model)
    with localcontext() as context:
        context.prec = 6
        step = ForwardElimination(result).step(3)
        details = ForwardEliminationDetails(result, False).details(3)
    assert step.pivot_rhs == result.eliminated.rhs[2] != result.constrained.rhs[2]
    assert str(result.eliminated.rhs[2]) in details
    assert str(result.eliminated.diagonal[3]) in details
    with localcontext(Context(prec=result.precision)):
        assert step.factor == result.constrained.lower[2] / result.eliminated.diagonal[2]


@pytest.mark.parametrize('row', [0, -1, 3, True, 1.5])
def test_out_of_range_step_is_rejected(row):
    '''Не допускает опорную строку и несуществующие шаги.'''
    with pytest.raises(ValueError):
        ForwardElimination(example_result()).step(row)


@pytest.mark.parametrize('completed', [-1, 3, True, 1.5])
def test_out_of_range_snapshot_is_rejected(completed):
    '''Проверяет границы числа выполненных исключений.'''
    with pytest.raises(ValueError):
        ForwardElimination(example_result()).system_after(completed)
