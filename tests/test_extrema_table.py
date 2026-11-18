'''Проверяет выбор величины и понятные строки экстремумов в постпроцессоре.'''

from decimal import Decimal as D, localcontext
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication

from src.sapr.app import create_application
from src.sapr.domain import Bar, StructuralModel
from src.sapr.domain.postprocessor import AxialPostprocessor
from src.sapr.domain.processor import AxialProcessor
from src.sapr.ui.pages.postprocessor import PostprocessorPage
from src.sapr.ui.widgets.response_table import ResponseTableModel


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or create_application([], persist_theme=False)


def solve(force='0', load='8', fixed=True, limit='1'):
    source = StructuralModel((Bar(D(1), D(1), D(1), D(limit)),),
                             (D(0), D(force)), (D(load),), (True, fixed))
    return AxialPostprocessor().analyze(AxialProcessor().solve(source))


@pytest.mark.parametrize('component, expected', [
    ('N', ((D(1), D(-4)), (D(0), D(4)))),
    ('sigma', ((D(1), D(-4)), (D(0), D(4)))),
    ('u', ((D(0), D(0)), (D('0.5'), D(1)))),
])
def test_selected_extrema_have_names_coordinates_and_values(app, component, expected):
    table = ResponseTableModel(solve(), extrema_only=True, component=component)
    assert table.rowCount() == 2
    assert table.columnCount() == 4
    assert table.headerData(3, Qt.Orientation.Horizontal) == table.COMPONENTS[component]
    for row, ((x, value), kind) in enumerate(zip(expected, ('Минимум', 'Максимум'))):
        assert table.index(row, 1).data() == kind
        assert table.index(row, 2).data(Qt.ItemDataRole.UserRole) == x
        assert table.index(row, 3).data(Qt.ItemDataRole.UserRole) == value
        assert table.section(row).x_m == x


@pytest.mark.parametrize('force', ['-12', '0', '12'])
@pytest.mark.parametrize('component', ['N', 'sigma', 'u'])
def test_constant_extrema_are_not_hidden(app, force, component):
    result = solve(force=force, load='0', fixed=False)
    table = ResponseTableModel(result, extrema_only=True, component=component)
    assert table.rowCount() == 2
    assert [table.index(row, 1).data() for row in range(2)] == ['Минимум', 'Максимум']
    values = [table.index(row, 3).data(Qt.ItemDataRole.UserRole) for row in range(2)]
    assert values == ([D(force)] * 2 if component != 'u' else sorted((D(0), D(force))))


def test_all_extrema_identify_quantity_and_keep_independent_rows(app):
    table = ResponseTableModel(solve(), extrema_only=True)
    assert table.rowCount() == 6
    assert table.columnCount() == 5
    assert [table.index(row, 1).data() for row in range(6)] == ['N, Н'] * 2 + ['σ, Па'] * 2 + ['u, м'] * 2
    assert [table.index(row, 2).data() for row in range(6)] == ['Минимум', 'Максимум'] * 3
    for row in range(6):
        assert (table.index(row, 4).data(Qt.ItemDataRole.BackgroundRole) is not None) == (row in (2, 3))


@pytest.mark.parametrize('extrema', [False, True])
@pytest.mark.parametrize('component', ['N', 'sigma', 'u'])
def test_selected_columns_preserve_precision_and_highlight_only_stress(app, extrema, component):
    limit = '9.99999999999999999999999999999999'
    table = ResponseTableModel(solve(force='10', load='0', fixed=False, limit=limit),
                               extrema_only=extrema, component=component)
    value_column = table.columnCount() - 1
    assert table.headerData(value_column, Qt.Orientation.Horizontal) == table.COMPONENTS[component]
    with localcontext() as context:
        context.prec = 6
        for row in range(table.rowCount()):
            index = table.index(row, value_column)
            assert index.data(Qt.ItemDataRole.UserRole) == table.section(row).value(component)
            assert (index.data(Qt.ItemDataRole.BackgroundRole) is not None) == (component == 'sigma')
            if component == 'sigma':
                assert 'Превышение' in index.data(Qt.ItemDataRole.ToolTipRole)
                assert limit in index.data(Qt.ItemDataRole.ToolTipRole)


def test_quantity_controls_and_row_selection(app):
    source = StructuralModel((Bar(D(1), D(1), D(1), D(1)),) * 2,
                             (D(0), D(0), D(0)), (D(8), D(8)), (True, True, True))
    page = PostprocessorPage()
    try:
        result = AxialPostprocessor().analyze(AxialProcessor().solve(source))
        page.set_result(result)
        page.viewsBar.setCurrentIndex(2)
        page.tableModeCombo.setCurrentIndex(1)
        assert page.tableComponentCombo.currentData() == 'sigma'
        assert page.samplingCombo.isHidden()
        assert page.samplingStack.isHidden()
        page.tableComponentCombo.setCurrentIndex(3)
        model = page.resultsTable.model()
        assert model.rowCount() == 4
        page.resultsTable.selectRow(3)
        assert page.barCombo.currentIndex() == 1
        assert page._selected_x == D('0.5')
        assert page.epures_view.selected_bar == page.graph_view.selected_bar == 1
        assert page.epures_view.selected_x == page.graph_view.selected_x == D('0.5')
        page.tableScopeCombo.setCurrentIndex(1)
        model = page.resultsTable.model()
        assert model.rowCount() == 2
        assert model.index(1, 0).data(Qt.ItemDataRole.UserRole) == 2
        page.resultsTable.selectRow(1)
        assert page._selected_x == D('0.5')
        page.tableComponentCombo.setCurrentIndex(0)
        assert page.resultsTable.model().rowCount() == 6
        page.tableModeCombo.setCurrentIndex(0)
        assert not page.samplingCombo.isHidden()
        assert not page.samplingStack.isHidden()
        assert page.resultsTable.model().columnCount() == 5
        assert page.result is result
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('width', [800, 1440])
def test_extrema_table_starts_directly_below_filters(app, width):
    page = PostprocessorPage()
    try:
        page.resize(width, 1000)
        page.set_result(solve())
        page.viewsBar.setCurrentIndex(2)
        page.tableModeCombo.setCurrentIndex(1)
        page.show()
        app.processEvents()
        combo = page.tableComponentCombo
        filters_bottom = combo.mapTo(page.tablePage, QPoint(0, combo.height())).y()
        table_top = page.resultsTable.mapTo(page.tablePage, QPoint(0, 0)).y()
        assert 0 <= table_top - filters_bottom <= 20
        assert page.resultsTable.height() >= 320
        assert page.width() == width
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
