'''Проверяет навигацию мышью, независимые оси и читаемость допуска.'''

from decimal import Decimal as D, localcontext
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from src.sapr.domain import Bar, StructuralModel, demo_model
from src.sapr.domain.postprocessor import AxialPostprocessor
from src.sapr.domain.processor import AxialProcessor
from src.sapr.ui.pages.postprocessor import PostprocessorPage
from src.sapr.ui.widgets.response_plot import ResponsePlot


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=[False, True], ids=['epures', 'local'])
def view(app, request):
    plot = ResponsePlot(local=request.param)
    plot.set_result(AxialPostprocessor().analyze(AxialProcessor().solve(demo_model())))
    plot.resize(1000, 650)
    plot.show()
    app.processEvents()
    yield plot
    plot.close()
    plot.deleteLater()
    app.processEvents()


def wheel(view, point, delta=120, modifiers=Qt.KeyboardModifier.NoModifier, pixels=0):
    event = QWheelEvent(point, view.mapToGlobal(point), QPoint(0, pixels), QPoint(0, delta),
                        Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view, event)
    return event


def move(view, point, buttons=Qt.MouseButton.NoButton):
    event = QMouseEvent(QMouseEvent.Type.MouseMove, point, view.mapToGlobal(point),
                       Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view, event)


def coordinate(view, point):
    with localcontext() as context:
        context.prec = view.result.precision
        rect = view._component_rects['N']
        x = view._left + view._screen_fraction(point.x()) * (view._right - view._left)
        y = view._vertical_center['N'] + D(str((rect.center().y() - point.y()) / (rect.height() * .39))) / view._vertical_zoom['N']
        return x, y


def test_wheel_anchors_both_coordinates_without_ctrl(view):
    rect = view._component_rects['N']
    point = QPointF(rect.left() + rect.width() * .7, rect.center().y() - 10)
    selected = (view.selected_bar, view.selected_x)
    before = coordinate(view, point)
    assert wheel(view, point).isAccepted()
    after = coordinate(view, point)
    assert all(abs(a - b) < D('1e-25') for a, b in zip(before, after))
    assert view._right - view._left < 1
    assert view._vertical_zoom['N'] > 1
    assert (view.selected_bar, view.selected_x) == selected


def test_modifiers_and_trackpad_keep_axes_independent(view):
    point = view._component_rects['N'].center()
    wheel(view, point, modifiers=Qt.KeyboardModifier.ControlModifier)
    assert set(view._vertical_zoom.values()) == {D(1)}
    horizontal = (view._left, view._right)
    wheel(view, point, modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert (view._left, view._right) == horizontal
    assert view._vertical_zoom['N'] > 1
    assert view._vertical_zoom['sigma'] == view._vertical_zoom['u'] == 1
    before = coordinate(view, point), view._vertical_zoom.copy()
    assert not wheel(view, point, delta=0).isAccepted()
    assert (coordinate(view, point), view._vertical_zoom) == before
    wheel(view, point, delta=0, pixels=10)
    assert view._right - view._left < horizontal[1] - horizontal[0]


def test_drag_moves_plot_without_selecting_section(view):
    view.zoom_by(D(3))
    view.grab()
    point = view._component_rects['N'].center()
    chosen = QSignalSpy(view.sectionSelected)
    before_left = view._left
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=point.toPoint())
    move(view, point + QPointF(60, 15), Qt.MouseButton.LeftButton)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=(point + QPointF(60, 15)).toPoint())
    assert not chosen
    assert view._left < before_left
    assert view._vertical_center['N'] > 0
    assert view._vertical_center['sigma'] == view._vertical_center['u'] == 0
    assert view.cursor().shape() == Qt.CursorShape.OpenHandCursor
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert len(chosen) == 1
    section = view._section_at(QPointF(point.toPoint()))
    assert chosen[0] == [section.bar_index, section.x_m]


def test_hover_does_not_change_section_or_rebuild_background(view):
    view.grab()
    cached = view._background.cacheKey()
    selected = (view.selected_bar, view.selected_x)
    hovered = QSignalSpy(view.sectionHovered)
    move(view, view._component_rects['N'].center())
    assert len(hovered) == 1
    assert view._hover_section is not None
    view.grab()
    assert view._background.cacheKey() == cached
    assert (view.selected_bar, view.selected_x) == selected


def test_reset_pan_limits_and_empty_input(view):
    view.zoom_by(D(4))
    view.grab()
    point = view._component_rects['N'].center()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=point.toPoint())
    move(view, point + QPointF(-100000, 0), Qt.MouseButton.LeftButton)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert view._right == 1
    assert view._left == D('.75')
    QTest.mouseDClick(view, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert (view._left, view._right) == (0, 1)
    assert set(view._vertical_zoom.values()) == {D(1)}
    view.zoom_by(D(2))
    QTest.keyClick(view, Qt.Key.Key_Home)
    assert (view._left, view._right) == (0, 1)
    for factor in (D(0), D(-1), D('NaN'), D('Infinity')):
        view.zoom_by(factor)
    assert (view._left, view._right) == (0, 1)
    view.clear()
    assert not wheel(view, point).isAccepted()


@pytest.mark.parametrize('force', ['1000000', '1e800', '-1e800'])
def test_limit_view_stays_readable_with_extreme_exceedance(app, force):
    source = StructuralModel((Bar(D(1), D(1), D(1), D(1)),),
                             (D(0), D(force)), (D(0),), (True, False))
    result = AxialPostprocessor().analyze(AxialProcessor().solve(source))
    view = ResponsePlot(local=True)
    view.resize(900, 550)
    view.set_result(result)
    view.set_component('sigma')
    view.fit_limits()
    assert not view.grab().isNull()
    scale, center = view._component_scales['sigma']
    assert scale == 1 and center == 0
    assert view._label_boxes, 'Подпись допуска должна быть видна даже при σ/[σ] = 1e800'
    assert result.at(0, D('.5')).stress_pa == D(force)
    view.fit_view()
    assert view._limit_scale is None
    view.deleteLater()


def test_page_controls_and_view_switch_preserve_navigation(app):
    page = PostprocessorPage()
    page.resize(1200, 900)
    page.set_result(AxialPostprocessor().analyze(AxialProcessor().solve(demo_model())))
    page.show()
    app.processEvents()
    page.zoomInButton.click()
    horizontal = (page.epures_view._left, page.epures_view._right)
    assert horizontal != (0, 1)
    assert page.epures_view._vertical_zoom['N'] > 1
    page.viewsBar.setCurrentIndex(1)
    page.componentCombo.setCurrentIndex(1)
    page.fitLimitsButton.click()
    assert page.graph_view._limit_scale is not None
    assert page.epures_view._limit_scale is None
    page.viewsBar.setCurrentIndex(0)
    assert (page.epures_view._left, page.epures_view._right) == horizontal
    assert page.limitsCheck.isChecked()
    page.fitButton.click()
    assert (page.epures_view._left, page.epures_view._right) == (0, 1)
    page.viewsBar.setCurrentIndex(2)
    assert page.plotHintLabel.isHidden() and page.hoverValuesLabel.isHidden()
    page.close()
    page.deleteLater()
