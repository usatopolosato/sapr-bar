'''Рисует аналитические эпюры в единой шкале координат конструкции.'''

from bisect import bisect_right
from decimal import Context, Decimal, localcontext

from PyQt6.QtCore import QBuffer, QIODevice, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtSvg import QSvgGenerator
from PyQt6.QtWidgets import QApplication, QWidget

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
    sectionHovered = pyqtSignal(int, object)
    hoverLeft = pyqtSignal()
    viewChanged = pyqtSignal()

    def __init__(self, parent=None, *, local: bool = False) -> None:
        super().__init__(parent)
        self.result: PostprocessorResult | None = None
        self.colors = LIGHT_COLORS
        self.local = local
        self.component = 'N'
        self.components = tuple(key for key, _ in COMPONENTS)
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
        self._label_boxes = []
        self._vertical_zoom = {key: ONE for key, _ in COMPONENTS}
        self._vertical_center = {key: ZERO for key, _ in COMPONENTS}
        self._limit_scale = None
        self._component_rects = {}
        self._component_scales = {}
        self._press_position = None
        self._dragging = False
        self._hover_section = None
        self.setMinimumHeight(390 if local else 520)
        self.setMinimumWidth(240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName('График стержня' if local else 'Эпюры конструкции')
        self.setToolTip('Колесо - масштаб под курсором; перетаскивание - перемещение\n'
                        'Ctrl + колесо - длина; Shift + колесо - высота выбранной эпюры\n'
                        'Щелчок - сечение; двойной щелчок или Home - вписать')

    def set_result(self, result: PostprocessorResult) -> None:
        '''Загружает результат и один раз определяет общие масштабы.'''
        self.result = result
        self.selected_bar = 0
        self.selected_x = ZERO
        self._positions = tuple(bar.start_m for bar in result.bars)
        self._max_area = max(bar.geometry.area_m2 for bar in result.bars)
        self._max_limit = max(bar.geometry.allowable_stress_pa for bar in result.bars)
        self._scales = {}
        for component, _ in COMPONENTS:
            largest = ZERO
            for bar in result.bars:
                minimum, maximum = bar.extrema(component)
                largest = max(largest, minimum.value(component).copy_abs(), maximum.value(component).copy_abs())
            self._scales[component] = largest
        self.fit_view()

    def clear(self) -> None:
        '''Освобождает устаревшие данные графика.'''
        self.result = None
        self._positions = ()
        self._scales.clear()
        self.fit_view()

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
        self._view_changed()

    def set_components(self, components: tuple[str, ...]) -> None:
        '''Показывает выбранные эпюры, включая отсутствие всех компонент.'''
        self.components = tuple(key for key, _ in COMPONENTS if key in components)
        self._view_changed()

    @classmethod
    def report_svg(cls, result: PostprocessorResult) -> str:
        '''Рисует автономную схему и все эпюры для светлого отчёта.'''
        view = cls()
        view.resize(1100, 780)
        view.set_result(result)
        view.set_limits_visible(True)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        generator = QSvgGenerator()
        generator.setOutputDevice(buffer)
        generator.setSize(QSize(1100, 780))
        generator.setViewBox(QRect(0, 0, 1100, 780))
        generator.setResolution(96)
        painter = QPainter(generator)
        view._paint_diagrams(painter)
        painter.end()
        svg = bytes(buffer.data()).decode('utf-8')
        buffer.close()
        view.deleteLater()
        return svg[svg.index('<svg'):]

    def set_limits_visible(self, visible: bool) -> None:
        '''Включает уровни допуска на эпюре напряжений.'''
        self.show_limits = visible
        self._invalidate()

    def fit_view(self) -> None:
        '''Вписывает длину и все ординаты, сбрасывая перемещение.'''
        self._left, self._right = ZERO, ONE
        self._vertical_zoom = {key: ONE for key, _ in COMPONENTS}
        self._vertical_center = {key: ZERO for key, _ in COMPONENTS}
        self._limit_scale = None
        self._press_position = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._view_changed()

    def fit_limits(self) -> None:
        '''Приближает допуск выбранного стержня без потери масштаба длины.'''
        if self.result is None:
            return
        self.show_limits = True
        self._limit_scale = self.result.bars[self.selected_bar].geometry.allowable_stress_pa
        self._vertical_zoom['sigma'] = ONE
        self._vertical_center['sigma'] = ZERO
        self._view_changed()

    def zoom_by(self, factor: Decimal, *, anchor: QPointF | None = None,
                axes: str | None = None, component: str | None = None) -> None:
        '''Масштабирует вокруг курсора, а с кнопок - вокруг центра окна.

        Args:
            factor: Отношение прежней ширины диапазона к новой.
            anchor: Экранная точка, сохраняющая координаты при увеличении.
            axes: both, x или y; по умолчанию меняются обе оси.
            component: Отдельная эпюра для изменения только её высоты.
        '''
        if self.result is None or not factor.is_finite() or factor <= ZERO:
            return
        axes = axes or 'both'
        with localcontext(Context(prec=self.result.precision)):
            if axes in ('both', 'x'):
                fraction = self._screen_fraction(anchor.x()) if anchor is not None else ONE / TWO
                old_span = self._right - self._left
                span = max(Decimal('1e-12'), min(ONE, old_span / factor))
                position = self._left + fraction * old_span
                self._set_range(position - fraction * span, span)
            if axes in ('both', 'y'):
                keys = self.components
                if component:
                    keys = (component,)
                elif self.local:
                    keys = (self.component,)
                for key in keys:
                    old = self._vertical_zoom[key]
                    new = max(Decimal('0.1'), min(Decimal('10000'), old * factor))
                    rect = self._component_rects.get(key)
                    if anchor is not None and rect is not None and rect.contains(anchor):
                        fraction = Decimal(str((rect.center().y() - anchor.y()) / (rect.height() * .39)))
                        self._vertical_center[key] += fraction * (ONE / old - ONE / new)
                    self._vertical_zoom[key] = new
        self._view_changed()

    def _screen_fraction(self, x: float) -> Decimal:
        '''Возвращает долю видимой ширины без выхода за область графика.'''
        return Decimal(str(max(0, min(1, (x - self._area.left()) / max(1, self._area.width())))))

    def _set_range(self, left: Decimal, span: Decimal) -> None:
        '''Ограничивает перемещение концами конструкции.'''
        self._left = max(ZERO, min(ONE - span, left))
        self._right = self._left + span

    def _view_changed(self) -> None:
        '''Обновляет изображение и доступные действия после навигации.'''
        self._hover_section = None
        self.hoverLeft.emit()
        self._invalidate()
        self.viewChanged.emit()

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
        ratio = max(Decimal('-1e6'), min(Decimal('1e6'), value / scale))
        return rect.center().y() - float(ratio) * rect.height() * .39

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
                painter.drawLine(QPointF(x, 24 if self.local else 140), QPointF(x, self.height() - 32))
            if self._hover_section is not None:
                section = self._hover_section
                start = ZERO if self.local else self.result.bars[section.bar_index].start_m
                x = self._x(start + section.x_m)
                painter.setPen(QPen(QColor(self.colors.accent), 1, Qt.PenStyle.DotLine))
                painter.drawLine(QPointF(x, 24 if self.local else 140), QPointF(x, self.height() - 32))
                for key, rect in self._component_rects.items():
                    scale, center = self._component_scales[key]
                    y = self._y(section.value(key) - center, scale, rect)
                    if rect.contains(QPointF(x, y)):
                        painter.setBrush(QColor(self.colors.panel))
                        painter.setPen(QPen(QColor(self.colors.accent), 1.5))
                        painter.drawEllipse(QPointF(x, y), 3.5, 3.5)

    def _paint_diagrams(self, painter: QPainter) -> None:
        '''Строит пути эпюр с раздельными границами соседних стержней.'''
        with localcontext(Context(prec=self.result.precision)):
            painter.setFont(QFont('Segoe UI', 9))
            widest = max((painter.fontMetrics().horizontalAdvance(number_text(value, True))
                          for value in self._scales.values()), default=60)
            margin = max(105, widest + 20)
            self._area = QRectF(margin, 12, max(1, self.width() - margin - 65), max(1, self.height() - 42))
            self._label_boxes = []
            self._component_rects = {}
            self._component_scales = {}
            components = ((self.component, dict(COMPONENTS)[self.component]),) if self.local else tuple(
                pair for pair in COMPONENTS if pair[0] in self.components)
            top = 24 if self.local else 140
            if not self.local:
                self._draw_structure(painter)
            height = (self.height() - top - 38) / max(1, len(components))
            for i, (component, title) in enumerate(components):
                rect = QRectF(self._area.left(), top + i * height, self._area.width(), height - 12)
                self._draw_component(painter, rect, component, title)
            self._draw_abscissa(painter)

    def _draw_structure(self, painter: QPainter) -> None:
        '''Размещает схему и номера стержней в масштабе общих эпюр.'''
        painter.setPen(QColor(self.colors.muted))
        painter.drawText(QRectF(0, 6, self._area.left() - 4, 20), Qt.AlignmentFlag.AlignLeft, 'Конструкция')
        bars = self._bars()
        y = 64
        painter.save()
        painter.setClipRect(QRectF(self._area.left() - 1, 4, self._area.width() + 2, 124))
        for bar in bars:
            x1, x2 = self._x(bar.start_m), self._x(bar.start_m + bar.geometry.length_m)
            x1, x2 = max(self._area.left(), x1), min(self._area.right(), x2)
            height = 8 + 18 * float((bar.geometry.area_m2 / self._max_area).sqrt())
            painter.setPen(QPen(QColor(self.colors.bar_border), 1))
            painter.setBrush(QColor(self.colors.bar_fill))
            painter.drawRect(QRectF(x1, y - height / 2, max(.2, x2 - x1), height))
            if x2 - x1 > 38:
                painter.setPen(QColor(self.colors.bar_text))
                painter.drawText(QRectF(x1, 84, x2 - x1, 20), Qt.AlignmentFlag.AlignCenter, str(bar.index + 1))
            painter.setPen(QColor(self.colors.muted))
            if x2 - x1 > 70:
                painter.drawText(QRectF(x1, 106, x2 - x1, 18), Qt.AlignmentFlag.AlignCenter,
                                 f'L = {number_text(bar.geometry.length_m, True)} м')
            self._draw_bar_load(painter, bar, x1, x2, y)
        painter.restore()
        self._draw_node_loads(painter, y)
        for index, fixed in enumerate(self.result.processor.model.supports):
            if not fixed:
                continue
            position = self._positions[index] if index < len(self._positions) else self._length()
            x = self._x(position)
            if not self._area.left() - 1 <= x <= self._area.right() + 1:
                continue
            painter.setPen(QPen(QColor(self.colors.axis), 1.2))
            painter.drawLine(QPointF(x, y - 23), QPointF(x, y + 23))
            for offset in range(-18, 24, 7):
                if index == len(self.result.bars):
                    painter.drawLine(QPointF(x, y + offset), QPointF(x + 9, y + offset - 6))
                else:
                    painter.drawLine(QPointF(x - 9, y + offset), QPointF(x, y + offset - 6))

    def _arrow(self, painter: QPainter, start: float, end: float, y: float, color: str) -> None:
        '''Рисует нагрузку вдоль оси конструкции.'''
        direction = 1 if end > start else -1
        size = min(7, abs(end - start) * .35)
        painter.setPen(QPen(QColor(color), 1.4))
        painter.setBrush(QColor(color))
        painter.drawLine(QPointF(start, y), QPointF(end, y))
        painter.drawPolygon(QPolygonF([QPointF(end, y), QPointF(end - direction * size, y - size / 2),
                                       QPointF(end - direction * size, y + size / 2)]))

    def _draw_bar_load(self, painter, bar, left: float, right: float, y: float) -> None:
        '''Показывает q по модулю, сохраняя направление стрелок.'''
        value = bar.q_n_per_m
        if not value or right - left < 12:
            return
        forces = self.result.processor.model.nodal_forces
        reserve = min(48, (right - left) * .3) + 8
        first = max(self._area.left(), left + (reserve if forces[bar.index] > 0 else 5))
        last = min(self._area.right(), right - (reserve if forces[bar.index + 1] < 0 else 5))
        if last <= first:
            return
        count = max(2, int((last - first) / 36))
        step = (last - first) / count
        for i in range(count):
            start, end = first + i * step, first + (i + .7) * step
            self._arrow(painter, start if value > 0 else end, end if value > 0 else start, y, self.colors.distributed)
        text = f'q = {number_text(value.copy_abs(), True)} Н/м'
        if painter.fontMetrics().horizontalAdvance(text) + 8 < last - first:
            painter.setPen(QColor(self.colors.distributed))
            painter.drawText(QRectF(first, 8, last - first, 18), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_node_loads(self, painter, y: float) -> None:
        '''Рисует силы из узлов, включая внешние концы конструкции.'''
        for index, value in enumerate(self.result.processor.model.nodal_forces):
            if not value:
                continue
            position = self._positions[index] if index < len(self._positions) else self._length()
            start = self._x(position)
            if not self._area.left() - 1 <= start <= self._area.right() + 1:
                continue
            direction = 1 if value > 0 else -1
            neighbour = index if direction > 0 else index - 1
            width = 160.0
            if 0 <= neighbour < len(self.result.bars):
                bar = self.result.bars[neighbour]
                width = self._x(bar.start_m + bar.geometry.length_m) - self._x(bar.start_m)
            end = start + direction * min(48, width * .3)
            self._arrow(painter, start, end, y, self.colors.force)
            text = f'F = {number_text(value.copy_abs(), True)} Н'
            size = painter.fontMetrics().horizontalAdvance(text) + 4
            if width > size:
                painter.setPen(QColor(self.colors.force))
                label_x = max(2, min(self.width() - size - 2, (start + end - size) / 2))
                painter.drawText(QRectF(label_x, 29, size, 18), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_selected_bar(self, painter: QPainter, bar) -> None:
        '''Рисует выделение поверх кэша без перестроения всех эпюр.'''
        x1, x2 = self._x(bar.start_m), self._x(bar.start_m + bar.geometry.length_m)
        if x2 < self._area.left() or x1 > self._area.right():
            return
        x1, x2 = max(self._area.left(), x1), min(self._area.right(), x2)
        height = 8 + 18 * float((bar.geometry.area_m2 / self._max_area).sqrt())
        painter.save()
        painter.setClipRect(QRectF(self._area.left() - 1, 42, self._area.width() + 2, 42))
        painter.setPen(QPen(QColor(self.colors.bar_selected_border), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(x1, 64 - height / 2, max(.2, x2 - x1), height))
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
            scale = max(scale, self.result.bars[self.selected_bar].geometry.allowable_stress_pa if self.local
                        else self._max_limit)
        if component == 'sigma' and self._limit_scale is not None:
            scale = self._limit_scale
        scale = scale or ONE
        center = self._vertical_center[component] * scale
        scale /= self._vertical_zoom[component]
        self._component_rects[component] = rect
        self._component_scales[component] = (scale, center)
        def ordinate(value: Decimal) -> float:
            offset = value - center
            if component != 'u':
                offset = max(-3 * scale, min(3 * scale, offset))
            return self._y(offset, scale, rect)

        baseline = ordinate(ZERO)
        painter.setPen(QColor(self.colors.text))
        painter.setFont(QFont('Segoe UI', 10, QFont.Weight.DemiBold))
        painter.drawText(QRectF(0, title_top, self._area.left() - 8, 22), Qt.AlignmentFlag.AlignLeft, title)
        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QPen(QColor(self.colors.border), 1))
        for sign in (ONE, ZERO, -ONE):
            value = center + sign * scale
            y = ordinate(value)
            painter.setPen(QColor(self.colors.muted))
            painter.drawText(QRectF(0, y - 8, self._area.left() - 10, 16), Qt.AlignmentFlag.AlignRight, number_text(value, True))
            painter.setPen(QPen(QColor(self.colors.grid), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.save()
        painter.setClipRect(rect.adjusted(-1, -2, 1, 2))
        painter.setPen(QPen(QColor(self.colors.axis), 1))
        painter.drawLine(QPointF(rect.left(), baseline), QPointF(rect.right(), baseline))
        painter.setPen(QPen(QColor(self.colors.grid), 1, Qt.PenStyle.DotLine))
        for bar in bars:
            start = ZERO if self.local else bar.start_m
            for position in (start, start + bar.geometry.length_m):
                x = self._x(position)
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for bar in bars:
            start = ZERO if self.local else bar.start_m
            left = max(ZERO, self._left * self._length() - start)
            right = min(bar.geometry.length_m, self._right * self._length() - start)
            if right <= left:
                continue
            points = self._curve_positions(bar, component, left, right, center, scale)
            for x1, x2 in zip(points, points[1:]):
                s1, s2 = bar.at(x1), bar.at(x2)
                middle = bar.at((x1 + x2) / TWO)
                y1, y2 = s1.value(component), s2.value(component)
                ym = middle.value(component)
                screen1, screen2 = self._x(start + x1), self._x(start + x2)
                exceeded = component == 'sigma' and ym.copy_abs() > bar.geometry.allowable_stress_pa
                if exceeded:
                    color = self.colors.error_border
                elif ym >= ZERO:
                    color = self.colors.accent
                else:
                    color = self.colors.compression
                line = QPainterPath(QPointF(screen1, ordinate(y1)))
                if component == 'u':
                    control = TWO * ym - (y1 + y2) / TWO
                    line.quadTo(QPointF((screen1 + screen2) / 2, ordinate(control)),
                                QPointF(screen2, ordinate(y2)))
                else:
                    line.lineTo(screen2, ordinate(y2))
                if not self.local:
                    self._fill_curve(painter, line, rect, baseline, ordinate(ym), color, exceeded)
                painter.strokePath(line, QPen(QColor(color), 1.8))
            if component == 'sigma' and self.show_limits:
                tint = QColor(self.colors.error_border)
                tint.setAlpha(24)
                upper = ordinate(bar.geometry.allowable_stress_pa)
                lower = ordinate(-bar.geometry.allowable_stress_pa)
                painter.fillRect(QRectF(self._x(start + left), upper,
                                       self._x(start + right) - self._x(start + left), lower - upper), tint)
                painter.setPen(QPen(QColor(self.colors.error_border), 1.5, Qt.PenStyle.DashLine))
                for sign in (ONE, -ONE):
                    y = ordinate(sign * bar.geometry.allowable_stress_pa)
                    painter.drawLine(QPointF(self._x(start + left), y), QPointF(self._x(start + right), y))
        painter.restore()
        self._draw_extrema_labels(painter, bars, rect, component, ordinate)
        if self.local:
            painter.setPen(QColor(self.colors.muted))
            painter.drawText(QRectF(rect.left(), title_top, rect.width(), 18), Qt.AlignmentFlag.AlignRight,
                             f'Стержень {bars[0].index + 1}')
        self._draw_overflow(painter, rect, component, scale, center)
        if component == 'sigma' and self.show_limits:
            self._draw_limit_labels(painter, rect, scale, center)

    @staticmethod
    def _curve_positions(bar, component, left, right, center, scale):
        '''Разбивает видимую часть стержня в характерных точках и на краях окна.'''
        points = {left, right}
        for position in bar.critical_positions():
            if left < position < right:
                points.add(position)
        if component != 'u' and bar.q_n_per_m:
            area = bar.geometry.area_m2 if component == 'sigma' else ONE
            for value in (center - scale / Decimal('.78'), center + scale / Decimal('.78')):
                crossing = (bar.force_origin_n - value * area) / bar.q_n_per_m
                if left < crossing < right:
                    points.add(crossing)
        return sorted(points)

    @staticmethod
    def _fill_curve(painter, line, rect, baseline, middle_y, color, exceeded):
        '''Замыкает кривую на ось и проводит штрихи до её ординат.'''
        first = line.elementAt(0)
        last = line.currentPosition()
        x1, y1 = first.x, first.y
        x2, y2 = last.x(), last.y()
        fill = QPainterPath(line)
        fill.lineTo(x2, baseline)
        fill.lineTo(x1, baseline)
        fill.closeSubpath()
        shade = QColor(color)
        shade.setAlpha(55 if exceeded else 30)
        painter.fillPath(fill, shade)
        painter.setPen(QPen(QColor(color), .7))
        # Поправка к прямому отрезку учитывает кривизну параболы перемещений.
        bend = 4 * (middle_y - (y1 + y2) / 2)
        start = int(max(rect.left(), x1))
        end = int(min(rect.right(), x2))
        for x in range(start, end + 1, 9):
            fraction = 0
            if x2 > x1:
                fraction = max(0, min(1, (x - x1) / (x2 - x1)))
            top = y1 * (1 - fraction) + y2 * fraction + bend * fraction * (1 - fraction)
            painter.drawLine(QPointF(x, baseline), QPointF(x, top))

    def _draw_extrema_labels(self, painter, bars, rect, component, ordinate):
        '''Подписывает видимые экстремумы, пропуская пересекающиеся подписи.'''
        occupied = []
        for bar in bars:
            start = ZERO if self.local else bar.start_m
            x1, x2 = self._x(start), self._x(start + bar.geometry.length_m)
            if x2 - x1 < 44:
                continue
            positions = {section.x_m for section in bar.extrema(component)}
            for position in sorted(positions):
                section = bar.at(position)
                value = section.value(component)
                x, y = self._x(start + position), ordinate(value)
                if not rect.contains(QPointF(x, y)):
                    continue
                text = number_text(value, True)
                width = painter.fontMetrics().horizontalAdvance(text) + 8
                if position == ZERO:
                    anchor = x + 3
                elif position == bar.geometry.length_m:
                    anchor = x - width - 3
                else:
                    anchor = x - width / 2
                if width > rect.width():
                    continue
                label = QRectF(max(rect.left(), min(rect.right() - width, anchor)),
                               max(rect.top(), min(rect.bottom() - 16, y - 20 if value >= ZERO else y + 4)), width, 16)
                if any(label.intersects(previous.adjusted(-4, -2, 4, 2)) for previous in occupied):
                    continue
                occupied.append(label)
                self._label_boxes.append(label)
                painter.fillRect(label, QColor(self.colors.panel))
                painter.setPen(QColor(self.colors.error_text if component == 'sigma'
                                     and value.copy_abs() > bar.geometry.allowable_stress_pa else self.colors.text))
                painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_limit_labels(self, painter: QPainter, rect: QRectF, scale: Decimal, center: Decimal) -> None:
        '''Оставляет допуск читаемым, даже когда обе линии сливаются у нуля.'''
        for bar in self._bars():
            start = ZERO if self.local else bar.start_m
            left = max(rect.left(), self._x(start))
            right = min(rect.right(), self._x(start + bar.geometry.length_m))
            limit = bar.geometry.allowable_stress_pa
            y = self._y(limit - center, scale, rect)
            text = f'Допуск ±{number_text(limit, True)} Па'
            width = painter.fontMetrics().horizontalAdvance(text) + 8
            if right - left < width + 8:
                continue
            # Отдельная подпись рядом с реальной линией, без изменения её координаты.
            top = max(rect.top() + 2, min(rect.bottom() - 18, y - 20))
            label = QRectF((left + right - width) / 2, top, width, 16)
            if any(label.intersects(box) for box in self._label_boxes):
                label.moveTop(max(rect.top() + 2, min(rect.bottom() - 18, y + 5)))
            if any(label.intersects(box) for box in self._label_boxes):
                continue
            self._label_boxes.append(label)
            painter.fillRect(label, QColor(self.colors.panel))
            painter.setPen(QColor(self.colors.error_text))
            painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_overflow(self, painter: QPainter, rect: QRectF, component: str,
                       scale: Decimal, center: Decimal) -> None:
        '''Помечает отсечённые значения, чтобы приближение не скрывало превышение.'''
        for bar in self._bars():
            start = ZERO if self.local else bar.start_m
            left = max(ZERO, self._left * self._length() - start)
            right = min(bar.geometry.length_m, self._right * self._length() - start)
            if right <= left:
                continue
            sections = [bar.at(left), bar.at(right)] + [point for point in bar.extrema(component) if left <= point.x_m <= right]
            for section in (min(sections, key=lambda point: point.value(component)),
                            max(sections, key=lambda point: point.value(component))):
                y = self._y(section.value(component) - center, scale, rect)
                if rect.top() <= y <= rect.bottom():
                    continue
                x = max(rect.left() + 5, min(rect.right() - 5, self._x(start + section.x_m)))
                top = y < rect.top()
                edge, inward = (rect.top() + 1, 7) if top else (rect.bottom() - 1, -7)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.colors.error_border if component == 'sigma'
                                        and section.stress_pa.copy_abs() > bar.geometry.allowable_stress_pa else self.colors.accent))
                painter.drawPolygon(QPolygonF([QPointF(x, edge), QPointF(x - 4, edge + inward),
                                               QPointF(x + 4, edge + inward)]))

    def _draw_abscissa(self, painter: QPainter) -> None:
        '''Подписывает горизонтальную ось в локальных или общих метрах.'''
        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QColor(self.colors.muted))
        length = self._length()
        ticks = max(1, min(4, int(self._area.width() / 100)))
        for index in range(ticks + 1):
            fraction = Decimal(index) / ticks
            value = (self._left + fraction * (self._right - self._left)) * length
            x = self._area.left() + float(fraction) * self._area.width()
            if index == 0:
                align, left = Qt.AlignmentFlag.AlignLeft, x
            elif index == ticks:
                align, left = Qt.AlignmentFlag.AlignRight, x - 95
            else:
                align, left = Qt.AlignmentFlag.AlignCenter, x - 48
            rect = QRectF(left, self.height() - 25, 95, 20)
            painter.drawText(rect, align, number_text(value, True))
        painter.drawText(QRectF(0, self.height() - 25, 68, 20), Qt.AlignmentFlag.AlignLeft,
                         'x, м' if self.local else 'X, м')

    def _section_at(self, position: QPointF):
        '''Вычисляет аналитическое сечение под курсором.'''
        with localcontext(Context(prec=self.result.precision)):
            ratio = self._screen_fraction(position.x())
            position = (self._left + ratio * (self._right - self._left)) * self._length()
            index = self.selected_bar if self.local else min(len(self.result.bars) - 1,
                                                             max(0, bisect_right(self._positions, position) - 1))
            bar = self.result.bars[index]
            x = position if self.local else position - bar.start_m
            x = min(bar.geometry.length_m, max(ZERO, x))
        return bar.at(x)

    def _component_at(self, position: QPointF) -> str | None:
        '''Находит эпюру для независимого перемещения или масштаба высоты.'''
        return next((key for key, rect in self._component_rects.items() if rect.contains(position)), None)

    def mousePressEvent(self, event) -> None:
        '''Начинает захват мыши; выбор сечения выполняется только при щелчке.'''
        if (self.result is None or event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton)
                or not self._area.contains(event.position())):
            return super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._press_position = event.position()
        self._press_button = event.button()
        self._dragging = False
        self._drag_range = (self._left, self._right)
        self._drag_component = self._component_at(event.position())
        self._drag_centers = self._vertical_center.copy()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        '''Перемещает выбранную эпюру или показывает значения под курсором.'''
        if self.result is None:
            return super().mouseMoveEvent(event)
        if self._press_position is not None:
            delta = event.position() - self._press_position
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
            if self._dragging:
                with localcontext(Context(prec=self.result.precision)):
                    left, right = self._drag_range
                    shift = Decimal(str(delta.x() / max(1, self._area.width()))) * (right - left)
                    self._set_range(left - shift, right - left)
                    key = self._drag_component
                    if key is not None:
                        rect = self._component_rects[key]
                        shift = Decimal(str(delta.y() / (rect.height() * .39))) / self._vertical_zoom[key]
                        self._vertical_center[key] = max(-Decimal('100'), min(Decimal('100'), self._drag_centers[key] + shift))
                self._view_changed()
            event.accept()
        elif self._area.contains(event.position()):
            self._hover_section = self._section_at(event.position())
            self.sectionHovered.emit(self._hover_section.bar_index, self._hover_section.x_m)
            self.update()
            event.accept()
        else:
            self._clear_hover()
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        '''Отличает выбор сечения от перетаскивания, сохраняя прежний выбор.'''
        if self._press_position is None or event.button() != self._press_button:
            return super().mouseReleaseEvent(event)
        click = not self._dragging and (event.position() - self._press_position).manhattanLength() < QApplication.startDragDistance()
        self._press_position = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if click and event.button() == Qt.MouseButton.LeftButton and self._area.contains(event.position()):
            section = self._section_at(event.position())
            self.sectionSelected.emit(section.bar_index, section.x_m)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        '''Возвращает полный вид тем же жестом на обеих вкладках.'''
        if self.result is not None and event.button() == Qt.MouseButton.LeftButton:
            self.fit_view()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def _clear_hover(self) -> None:
        '''Убирает временное сечение, не меняя закреплённое щелчком.'''
        if self._hover_section is not None:
            self._hover_section = None
            self.hoverLeft.emit()
            self.update()

    def leaveEvent(self, event) -> None:
        '''Скрывает указатель после выхода за область графика.'''
        self._clear_hover()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        '''Повторяет мягкое увеличение препроцессора без обязательного Ctrl.'''
        if self.result is None or not self._area.contains(event.position()):
            event.ignore()
            return
        delta = event.pixelDelta().y() / 40 if not event.pixelDelta().isNull() else event.angleDelta().y() / 120
        if not delta:
            event.ignore()
            return
        axes, component = 'both', None
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            axes, component = 'y', self._component_at(event.position())
            if component is None:
                event.ignore()
                return
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            axes = 'x'
        factor = Decimal(str(1.12 ** max(-20, min(20, delta))))
        self.zoom_by(factor, anchor=event.position(), axes=axes, component=component)
        event.accept()

    def keyPressEvent(self, event) -> None:
        '''Даёт доступ к масштабу и перемещению с клавиатуры.'''
        if self.result is None:
            return super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Home, Qt.Key.Key_0):
            self.fit_view()
        elif event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus):
            self.zoom_by(Decimal('1.2') if event.key() != Qt.Key.Key_Minus else ONE / Decimal('1.2'))
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            with localcontext(Context(prec=self.result.precision)):
                span = self._right - self._left
                self._set_range(self._left + span * (Decimal('0.1') if event.key() == Qt.Key.Key_Right else Decimal('-0.1')), span)
            self._view_changed()
        else:
            return super().keyPressEvent(event)
        event.accept()
