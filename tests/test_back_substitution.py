'''Проверяет показ обратного хода по фактической треугольной системе.'''

from decimal import Decimal

import pytest
from PyQt6.QtCore import Qt

from src.sapr.domain import Bar, StructuralModel
from src.sapr.domain.processor import AxialProcessor
from src.sapr.ui.widgets.back_substitution import BackSubstitutionModel


@pytest.mark.parametrize('sign', ['1', '-1'])
def test_back_substitution_uses_eliminated_rhs_and_next_displacement(sign):
    '''Проверяет подстановку после исключения и знак следующего перемещения.'''
    force = Decimal(sign)
    bar = Bar(Decimal(1), Decimal(1), Decimal(1), Decimal(10))
    model = StructuralModel((bar, bar), (Decimal(0), force, force), (Decimal(0), Decimal(0)), (True, False, False))
    result = AxialProcessor().solve(model)
    table = BackSubstitutionModel(result, True)
    assert [table.headerData(row, Qt.Orientation.Vertical) for row in range(3)] == ['Узел 3', 'Узел 2', 'Узел 1']
    assert result.original.rhs[2] != result.eliminated.rhs[2]
    negative = '-' if force < 0 else ''
    assert table.substitution(0, True) == f'Δ3 = {negative}1.5 / 0.5'
    assert table.substitution(1, True) == f'Δ2 = ({negative}1 - (-1) * ({negative}3)) / 2'
    assert table.index(1, 1).data(Qt.ItemDataRole.UserRole) == Decimal(negative + '2')
    assert table.substitution(2, True) == 'Δ1 = 0 / 1'
    assert 'Узел закреплён' in table.details(2)
    assert f'Найдено ранее   Δ3 = {negative}3 м' in table.details(1)


def test_exact_back_substitution_keeps_long_decimal_result():
    '''Не повторяет расчёт по сокращённым значениям из таблицы.'''
    force = Decimal('1.2345678901234567890123456789')
    bar = Bar(Decimal(1), Decimal(1), Decimal(3), Decimal(10))
    model = StructuralModel((bar,), (Decimal(0), force), (Decimal(0),), (True, False))
    result = AxialProcessor().solve(model)
    exact = BackSubstitutionModel(result, False)
    compact = BackSubstitutionModel(result, True)
    assert str(force) in exact.substitution(0, False)
    assert exact.index(0, 1).data() == str(result.displacements[1])
    assert exact.index(0, 1).data(Qt.ItemDataRole.UserRole) is result.displacements[1]
    assert compact.index(0, 1).data() != exact.index(0, 1).data()
    assert compact.index(0, 0).data(Qt.ItemDataRole.ToolTipRole) == exact.index(0, 0).data()
