'''Рисует аналитические эпюры в единой шкале координат конструкции.'''

from bisect import bisect_right
from decimal import Context, Decimal, localcontext

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from ...domain.postprocessor import PostprocessorResult
from ..theme import LIGHT_COLORS, ThemeColors
from .linear_system import number_text


ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)
COMPONENTS = (('N', 'N, Н'), ('sigma', 'σ, Па'), ('u', 'u, м'))


class ResponsePlot(QWidget):
    '''Показывает общие эпюры или локальный график выбранного стержня.

    Args:
        parent: Родитель графического виджета.
        local: Признак графика по локальной координате стержня.
    '''

    sectionSelected = pyqtSignal(int, object)

    def __init__(self, parent=None, *, local: bool = False) -> None:
        super().__init__(parent)
        self.result: PostprocessorResult | None = None
        self.colors = LIGHT_COLORS
        self.local = local
        self.component = 'N'
        self.selected_bar = 0
        self.selected_x = ZERO
        self.show_limits = False
        self._left = ZERO
        self._right = ONE
        self._scales = {}
        self._max_area = ONE
        self._positions = ()
        self._area = QRectF()
        self._background = None
        self.setMinimumHeight(390 if local else 520)
        self.setMinimumWidth(240)
        self.setMouseTracking(True)
        self.setToolTip('Нажмите на сечение для просмотра значений\nCtrl и колесо мыши - масштаб по длине')

    def set_result(self, result: PostprocessorResult) -> None:
        '''Загружает результат и один раз определяет общие масштабы.'''
        self.result = result
        self.selected_bar = 0
        self.selected_x = ZERO
        self._positions = tuple(bar.start_m for bar in result.bars)
        self._max_area = max(bar.geometry.area_m2 for bar in result.bars)
        with localcontext(Context(prec=result.precision)):
            self._scales = {
                component: max((section.value(component).copy_abs() for bar in result.bars
                                for section in bar.extrema(component)), default=ONE)
                for component, _ in COMPONENTS
            }
        self.fit_view()

    def clear(self) -> None:
        '''Освобождает устаревшие данные графика.'''
        self.result = None
        self._positions = ()
        self._scales.clear()
        self._invalidate()

    def set_theme(self, colors: ThemeColors) -> None:
        '''Применяет палитру без изменения расчётных данных.'''
        self.colors = colors
        self._invalidate()

    def set_section(self, index: int, x: Decimal) -> None:
        '''Согласует выбор стержня и вертикальный указатель сечения.'''
        changed = self.selected_bar != index
        self.selected_bar, self.selected_x = index, x
        if changed and self.local:
            self.fit_view()
        self.update()

    def set_component(self, component: str) -> None:
        '''Выбирает величину отдельного локального графика.'''
        self.component = component
        self._invalidate()

    def set_limits_visible(self, visible: bool) -> None:
        '''Включает уровни допуска на эпюре напряжений.'''
        self.show_limits = visible
        self._invalidate()

    def fit_view(self) -> None:
        '''Возвращает полный диапазон длины на экран.'''
        self._left, self._right = ZERO, ONE
        self._invalidate()

    def zoom_by(self, factor: Decimal) -> None:
        '''Меняет горизонтальный масштаб вокруг выбранного сечения.

        Args:
            factor: Отношение прежней ширины диапазона к новой.
        '''
        if self.result is None:
            return
        with localcontext(Context(prec=self.result.precision)):
            span = min(ONE, (self._right - self._left) / factor)
            span = max(Decimal('1e-12'), span)
            total = self._length()
            bar = self.result.bars[self.selected_bar]
            position = self.selected_x if self.local else bar.start_m + self.selected_x
            center = position / total
            if not self._left <= center <= self._right:
                center = (self._left + self._right) / TWO
            self._left = max(ZERO, min(ONE - span, center - span / TWO))
            self._right = self._left + span
        self._invalidate()

    def _invalidate(self) -> None:
        '''Отзывает фон при изменении данных, масштаба или оформления.'''
        self._background = None
        self.update()

    def _length(self) -> Decimal:
        '''Возвращает протяжённость текущей системы координат.'''
        if self.local:
            return self.result.bars[self.selected_bar].geometry.length_m
        last = self.result.bars[-1]
        return last.start_m + last.geometry.length_m

    def _x(self, position: Decimal) -> float:
        '''Переводит нормализованную координату в экранный пиксель.'''
        ratio = (position / self._length() - self._left) / (self._right - self._left)
        return self._area.left() + float(ratio) * self._area.width()

    def _y(self, value: Decimal, scale: Decimal, rect: QRectF) -> float:
        '''Переводит нормализованную ординату в экранный пиксель.'''
        return rect.center().y() - float(value / scale) * rect.height() * .39

    def _bars(self):
        '''Возвращает только стержни внутри видимого диапазона.'''
        if self.local:
            return (self.result.bars[self.selected_bar],)
        length = self._length()
        first = max(0, bisect_right(self._positions, self._left * length) - 1)
        last = min(len(self.result.bars), bisect_right(self._positions, self._right * length) + 1)
        return self.result.bars[first:last]

    def paintEvent(self, event) -> None:
        '''Использует готовый фон при перемещении указателя по стержню.'''
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.result is None:
            painter.fillRect(self.rect(), QColor(self.colors.panel))
            return
        ratio = self.devicePixelRatioF()
        physical_size = self.size() * ratio
        if self._background is None or self._background.size() != physical_size:
            self._background = QPixmap(physical_size)
            self._background.setDevicePixelRatio(ratio)
            self._background.fill(QColor(self.colors.panel))
            background = QPainter(self._background)
            background.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_diagrams(background)
            background.end()
        painter.drawPixmap(0, 0, self._background)
        with localcontext(Context(prec=self.result.precision)):
            bar = self.result.bars[self.selected_bar]
            if not self.local:
                self._draw_selected_bar(painter, bar)
            position = self.selected_x if self.local else bar.start_m + self.selected_x
            x = self._x(position)
            if self._area.left() <= x <= self._area.right():
                painter.setPen(QPen(QColor(self.colors.muted), 1, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(x, 24 if self.local else 100), QPointF(x, self.height() - 32))

    def _paint_diagrams(self, painter: QPainter) -> None:
        '''Строит пути эпюр с раздельными границами соседних стержней.'''
        with localcontext(Context(prec=self.result.precision)):
            self._area = QRectF(78, 12, max(1, self.width() - 100), max(1, self.height() - 42))
            painter.setFont(QFont('Segoe UI', 9))
            components = ((self.component, dict(COMPONENTS)[self.component]),) if self.local else COMPONENTS
            top = 24 if self.local else 100
            if not self.local:
                self._draw_structure(painter)
            height = (self.height() - top - 38) / len(components)
            for i, (component, title) in enumerate(components):
                rect = QRectF(self._area.left(), top + i * height, self._area.width(), height - 12)
                self._draw_component(painter, rect, component, title)
            self._draw_abscissa(painter)

    def _draw_structure(self, painter: QPainter) -> None:
        '''Размещает схему и номера стержней в масштабе общих эпюр.'''
        painter.setPen(QColor(self.colors.muted))
        painter.drawText(QRectF(0, 6, self.width(), 20), Qt.AlignmentFlag.AlignLeft, 'Конструкция')
        bars = self._bars()
        y = 53
        painter.save()
        painter.setClipRect(QRectF(self._area.left() - 2, 28, self._area.width() + 4, 64))
        for bar in bars:
            x1, x2 = self._x(bar.start_m), self._x(bar.start_m + bar.geometry.length_m)
            height = 8 + 18 * float((bar.geometry.area_m2 / self._max_area).sqrt())
            painter.setPen(QPen(QColor(self.colors.bar_border), 1))
            painter.setBrush(QColor(self.colors.bar_fill))
            painter.drawRect(QRectF(x1, y - height / 2, max(.2, x2 - x1), height))
            if x2 - x1 > 38:
                painter.setPen(QColor(self.colors.bar_text))
                painter.drawText(QRectF(x1, y - 10, x2 - x1, 20), Qt.AlignmentFlag.AlignCenter, str(bar.index + 1))
            painter.setPen(QColor(self.colors.muted))
            if x2 - x1 > 70:
                painter.drawText(QRectF(x1, 72, x2 - x1, 18), Qt.AlignmentFlag.AlignCenter,
                                 f'L = {number_text(bar.geometry.length_m, True)} м')
        painter.restore()
        for index, fixed in enumerate(self.result.processor.model.supports):
            if not fixed:
                continue
            position = self._positions[index] if index < len(self._positions) else self._length()
            x = self._x(position)
            if not self._area.left() - 1 <= x <= self._area.right() + 1:
                continue
            painter.setPen(QPen(QColor(self.colors.axis), 1.2))
            painter.drawLine(QPointF(x, y - 23), QPointF(x, y + 23))
            direction = 1 if index == len(self.result.bars) else -1
            for offset in range(-18, 24, 7):
                painter.drawLine(QPointF(x, y + offset), QPointF(x + 9 * direction, y + offset + 6 * direction))

    def _draw_selected_bar(self, painter: QPainter, bar) -> None:
        '''Рисует выделение поверх кэша без перестроения всех эпюр.'''
        x1, x2 = self._x(bar.start_m), self._x(bar.start_m + bar.geometry.length_m)
        height = 8 + 18 * float((bar.geometry.area_m2 / self._max_area).sqrt())
        painter.save()
        painter.setClipRect(QRectF(self._area.left() - 1, 30, self._area.width() + 2, 48))
        painter.setPen(QPen(QColor(self.colors.bar_selected_border), 1))
        painter.setBrush(QColor(self.colors.bar_selected))
        painter.drawRect(QRectF(x1, 53 - height / 2, max(.2, x2 - x1), height))
        if x2 - x1 > 38:
            painter.setFont(QFont('Segoe UI', 9))
            painter.setPen(QColor(self.colors.bar_selected_text))
            painter.drawText(QRectF(x1, 43, x2 - x1, 20), Qt.AlignmentFlag.AlignCenter, str(bar.index + 1))
        painter.restore()

    def _draw_component(self, painter: QPainter, rect: QRectF, component: str, title: str) -> None:
        '''Рисует отдельную величину с нулём, подписями и допусками.'''
        title_top = rect.top()
        rect = rect.adjusted(0, 22, 0, 0)
        bars = self._bars()
        if self.local:
            scale = max(point.value(component).copy_abs() for point in bars[0].extrema(component))
        else:
            scale = self._scales[component]
        if component == 'sigma' and self.show_limits:
            scale = max(scale, max(bar.geometry.allowable_stress_pa for bar in bars))
        scale = scale or ONE
        painter.setPen(QColor(self.colors.text))
        painter.setFont(QFont('Segoe UI', 10, QFont.Weight.DemiBold))
        painter.drawText(QRectF(0, title_top, 74, 22), Qt.AlignmentFlag.AlignLeft, title)
        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QPen(QColor(self.colors.border), 1))
        painter.drawLine(QPointF(rect.left(), rect.center().y()), QPointF(rect.right(), rect.center().y()))
        for sign in (ONE, ZERO, -ONE):
            value = sign * scale
            y = self._y(value, scale, rect)
            painter.setPen(QColor(self.colors.muted))
            painter.drawText(QRectF(0, y - 8, 69, 16), Qt.AlignmentFlag.AlignRight, number_text(value, True))
        painter.save()
        painter.setClipRect(rect.adjusted(-1, -2, 1, 2))
        painter.setPen(QPen(QColor(self.colors.grid), 1, Qt.PenStyle.DotLine))
        for bar in bars:
            start = ZERO if self.local else bar.start_m
            for position in (start, start + bar.geometry.length_m):
                x = self._x(position)
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for bar in bars:
            start = ZERO if self.local else bar.start_m
            points = bar.critical_positions()
            for x1, x2 in zip(points, points[1:]):
                s1, s2 = bar.at(x1), bar.at(x2)
                middle = bar.at((x1 + x2) / TWO)
                y1, y2 = s1.value(component), s2.value(component)
                ym = middle.value(component)
                screen1, screen2 = self._x(start + x1), self._x(start + x2)
                exceeded = component == 'sigma' and ym.copy_abs() > bar.geometry.allowable_stress_pa
                color = self.colors.error_border if exceeded else self.colors.accent if ym >= ZERO else self.colors.distributed
                line = QPainterPath(QPointF(screen1, self._y(y1, scale, rect)))
                if component == 'u':
                    control = TWO * ym - (y1 + y2) / TWO
                    line.quadTo(QPointF((screen1 + screen2) / 2, self._y(control, scale, rect)),
                                QPointF(screen2, self._y(y2, scale, rect)))
                else:
                    line.lineTo(screen2, self._y(y2, scale, rect))
                fill = QPainterPath(line)
                fill.lineTo(screen2, rect.center().y())
                fill.lineTo(screen1, rect.center().y())
                fill.closeSubpath()
                shade = QColor(color)
                shade.setAlpha(30 if not exceeded else 55)
                painter.fillPath(fill, shade)
                painter.setPen(QPen(QColor(color), 1.8))
                painter.drawPath(line)
            if component == 'sigma' and self.show_limits:
                painter.setPen(QPen(QColor(self.colors.error_border), 1, Qt.PenStyle.DashLine))
                for sign in (ONE, -ONE):
                    y = self._y(sign * bar.geometry.allowable_stress_pa, scale, rect)
                    painter.drawLine(QPointF(self._x(start), y), QPointF(self._x(start + bar.geometry.length_m), y))
        painter.restore()
        occupied = []
        for bar in bars:
            start = ZERO if self.local else bar.start_m
            x1, x2 = self._x(start), self._x(start + bar.geometry.length_m)
            if x2 - x1 < 44:
                continue
            positions = {ZERO, bar.geometry.length_m}
            positions.update(section.x_m for section in bar.extrema(component))
            for position in sorted(positions):
                section = bar.at(position)
                value = section.value(component)
                x, y = self._x(start + position), self._y(value, scale, rect)
                if not rect.left() <= x <= rect.right():
                    continue
                text = number_text(value, True)
                width = painter.fontMetrics().horizontalAdvance(text) + 8
                anchor = x + 3 if position == ZERO else x - width - 3 if position == bar.geometry.length_m else x - width / 2
                label = QRectF(max(rect.left(), min(rect.right() - width, anchor)),
                               y - 20 if value >= ZERO else y + 4, width, 16)
                if any(label.intersects(previous.adjusted(-4, -2, 4, 2)) for previous in occupied):
                    continue
                occupied.append(label)
                painter.fillRect(label, QColor(self.colors.panel))
                painter.setPen(QColor(self.colors.error_text if component == 'sigma'
                                     and value.copy_abs() > bar.geometry.allowable_stress_pa else self.colors.text))
                painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
        if self.local:
            painter.setPen(QColor(self.colors.muted))
            painter.drawText(QRectF(rect.left(), title_top, rect.width(), 18), Qt.AlignmentFlag.AlignRight,
                             f'Стержень {bars[0].index + 1}')

    def _draw_abscissa(self, painter: QPainter) -> None:
        '''Подписывает горизонтальную ось в локальных или общих метрах.'''
        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QColor(self.colors.muted))
        length = self._length()
        for index in range(5):
            fraction = Decimal(index) / 4
            value = (self._left + fraction * (self._right - self._left)) * length
            x = self._area.left() + float(fraction) * self._area.width()
            align = Qt.AlignmentFlag.AlignLeft if index == 0 else Qt.AlignmentFlag.AlignRight if index == 4 else Qt.AlignmentFlag.AlignCenter
            rect = QRectF(x if index == 0 else x - 95 if index == 4 else x - 48, self.height() - 25, 95, 20)
            painter.drawText(rect, align, number_text(value, True))
        painter.drawText(QRectF(0, self.height() - 25, 68, 20), Qt.AlignmentFlag.AlignLeft,
                         'x, м' if self.local else 'X, м')

    def mousePressEvent(self, event) -> None:
        '''Выбирает сечение по горизонтальной координате курсора.'''
        if self.result is None or event.button() != Qt.MouseButton.LeftButton or not self._area.contains(event.position()):
            return super().mousePressEvent(event)
        with localcontext(Context(prec=self.result.precision)):
            ratio = Decimal(str((event.position().x() - self._area.left()) / self._area.width()))
            position = (self._left + ratio * (self._right - self._left)) * self._length()
            index = self.selected_bar if self.local else min(len(self.result.bars) - 1,
                                                             max(0, bisect_right(self._positions, position) - 1))
            bar = self.result.bars[index]
            x = position if self.local else position - bar.start_m
            x = min(bar.geometry.length_m, max(ZERO, x))
        self.sectionSelected.emit(index, x)

    def wheelEvent(self, event) -> None:
        '''Увеличивает эпюры с Ctrl, сохраняя обычную прокрутку страницы.'''
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(Decimal('1.5') if event.angleDelta().y() > 0 else Decimal('0.6666666666666666666667'))
            event.accept()
        else:
            event.ignore()
