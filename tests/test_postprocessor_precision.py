'''Проверяет согласованность точности, режима показа и панели сечения.'''

from decimal import Decimal as D
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.sapr.app import create_application
from src.sapr.domain import Bar, StructuralModel
from src.sapr.domain.postprocessor import AxialPostprocessor
from src.sapr.domain.processor import AxialProcessor
from src.sapr.formatting import format_quantity, format_result
from src.sapr.ui.pages.postprocessor import PostprocessorPage


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or create_application([], persist_theme=False)


@pytest.fixture
def page(app):
    source = StructuralModel((Bar(D(3), D(2), D(1), D(1)),),
                             (D(0), D('3.5')), (D(0),), (True, False))
    widget = PostprocessorPage()
    widget.resize(1200, 900)
    widget.set_result(AxialPostprocessor().analyze(AxialProcessor().solve(source)))
    widget.show()
    app.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('view', [0, 1, 2])
@pytest.mark.parametrize('places', [0, 2, 9, 12])
def test_precision_in_rounded_mode_does_not_change_result(page, view, places):
    page.viewsBar.setCurrentIndex(view)
    assert page.numberFormatCombo.isEnabled()
    page.numberFormatCombo.setCurrentText('Точно')
    assert page.precisionSpin.isHidden()
    assert page.precisionLabel.isHidden()
    page.numberFormatCombo.setCurrentText('Округлять')
    assert not page.precisionSpin.isHidden()
    assert not page.precisionLabel.isHidden()
    result = page.result
    section = result.at(0, D(0))
    page.precisionSpin.setValue(places)
    assert page.numberFormatCombo.currentText() == 'Округлять'
    for field, value in ((page.forceValue, section.force_n), (page.stressValue, section.stress_pa),
                         (page.displacementValue, section.displacement_m)):
        assert field.text() == format_result(value, places)
        assert field.toolTip() == str(value)
    table = page.resultsTable.model()
    assert table.index(0, 2).data() == page.forceValue.text()
    assert table.index(0, 3).data() == page.stressValue.text()
    assert format_result(section.force_n, places) in page.formulasView.toPlainText()
    assert page.result is result
    assert page._selected_x == D(0)
    assert page.strengthLabel.text() == 'Превышение в стержне'


def test_typing_nine_applies_without_leaving_precision_field(page):
    page.numberFormatCombo.setCurrentText('Округлять')
    editor = page.precisionSpin.lineEdit()
    editor.setFocus()
    editor.selectAll()
    QTest.keyClicks(editor, '9')
    assert page.precisionSpin.value() == 9
    assert page.numberFormatCombo.currentText() == 'Округлять'
    assert page.forceValue.text() == '3.500000000'
    assert page.stressValue.text() == '1.750000000'


def test_exact_mode_hides_focused_precision_and_preserves_last_value(page, app):
    page.precisionSpin.setValue(9)
    editor = page.precisionSpin.lineEdit()
    editor.setFocus()
    app.processEvents()
    page.numberFormatCombo.setCurrentText('Точно')
    app.processEvents()
    assert page.numberFormatCombo.currentText() == 'Точно'
    assert page.precisionSpin.isHidden()
    assert page.precisionLabel.isHidden()
    assert page.forceValue.text() == '3.5'
    page.numberFormatCombo.setCurrentText('Округлять')
    assert page.precisionSpin.value() == 9
    assert not page.precisionSpin.isHidden()
    assert not page.precisionLabel.isHidden()
    assert page.numberFormatCombo.currentText() == 'Округлять'
    assert page.forceValue.text() == '3.500000000'


def test_exact_mode_drops_padding_zeros_and_values_remain_read_only(page):
    page.numberFormatCombo.setCurrentText('Точно')
    assert page.forceValue.text() == '3.5'
    assert page.stressValue.text() == '1.75'
    assert page.resultsTable.model().index(0, 2).data() == '3.5'
    for field in (page.forceValue, page.stressValue, page.displacementValue):
        before = field.text()
        assert field.isReadOnly()
        field.setFocus()
        field.selectAll()
        assert field.selectedText() == before
        QTest.keyClicks(field, '123')
        assert field.text() == before


def test_long_exact_values_fit_panel_and_can_be_selected_in_full(page, app):
    source = StructuralModel((Bar(D(1), D(3), D(3), D(1)),),
                             (D(0), D(1)), (D(0),), (True, False))
    result = AxialPostprocessor().analyze(AxialProcessor().solve(source))
    page.set_result(result)
    page.numberFormatCombo.setCurrentText('Точно')
    page._select_section(0, D(1))
    app.processEvents()
    field = page.displacementValue
    exact = result.at(0, D(1)).displacement_m
    assert field.text() == format_quantity(exact)
    assert len(field.text()) > 50
    field.setFocus()
    field.selectAll()
    assert D(field.selectedText()) == exact
    QTest.keyClick(field, Qt.Key.Key_End)
    assert field.cursorPosition() == len(field.text())
    assert page.sectionCard.width() <= 320
    assert page.width() == 1200
    assert str(result.bars[0].max_abs_stress_pa) in page.strengthDetailsLabel.toolTip()
    assert max(map(len, page.strengthDetailsLabel.text().splitlines())) < 50
    for value_field in (page.forceValue, page.stressValue, page.displacementValue):
        assert value_field.geometry().right() <= page.sectionCard.width()
    assert page.result is result
