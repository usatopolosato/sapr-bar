'''Отрисовывает расчётную схему из исходных данных в системе СИ.'''

from math import ceil, floor
from decimal import Decimal

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from ...domain import StructuralModel, demo_model
from ..formatting import format_quantity
from ..theme import DARK_COLORS, ThemeColors


class BarItem(QGraphicsRectItem):
    '''Представляет выбираемый стержень в графической сцене.

    Args:
        rect: Границы изображения стержня.
        index: Индекс стержня в модели.
        colors: Цвета текущей темы интерфейса.
    '''

    def __init__(self, rect: QRectF, index: int, colors: ThemeColors = DARK_COLORS) -> None:
        super().__init__(rect)
        self.setData(0, index)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f'Стержень {index + 1:02d}')
        self.colors = colors
        self._hovered = False

    def paint(self, painter: QPainter, option, widget=None) -> None:
        '''Рисует стержень с выделением текущего выбора.

        Args:
            painter: Контекст отрисовки Qt.
            option: Параметры состояния графического элемента.
            widget: Виджет, отображающий сцену.
        '''
        rect = self.rect()
        active = self.isSelected() or self._hovered
        painter.setBrush(QColor(self.colors.bar_selected if active else self.colors.bar_fill))
        painter.setPen(QPen(QColor(self.colors.bar_selected_border if active else self.colors.bar_border), 1.6))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QColor(self.colors.bar_selected_text if active else self.colors.bar_text))
        painter.setFont(QFont('Segoe UI', 12, QFont.Weight.DemiBold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f'{self.data(0) + 1:02d}')

    def hoverEnterEvent(self, event) -> None:
        '''Подсвечивает стержень при наведении курсора.

        Args:
            event: Событие входа курсора в графический элемент.
        '''
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        '''Снимает подсветку наведения.

        Args:
            event: Событие выхода курсора из графического элемента.
        '''
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)


class StructureView(QGraphicsView):
    '''Показывает схему с масштабированием, сеткой и выбором стержней.

    Args:
        parent: Родительский виджет.
        compact: Признак упрощённой схемы для стартового экрана.
    '''

    barSelected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None, compact: bool = False) -> None:
        super().__init__(parent)
        self._compact = compact
        self._model = demo_model() if compact else StructuralModel()
        self._grid_visible = True
        self._loads_visible = not compact
        self._zoom = 1.0
        self._bars: list[BarItem] = []
        self._load_items: list[QGraphicsItem] = []
        self._quantity_labels = []
        self._compact_numbers = True
        self._colors = DARK_COLORS
        self._theme_bindings: list[tuple[QGraphicsItem, str, str]] = []
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QColor(self._colors.canvas))
        self.setAccessibleName('Интерактивная схема стержневой конструкции')
        self.setAccessibleDescription('Выбор стержня также доступен в таблице')
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(0, 0, 900, 310)
        self._build_scene()
        self.scene().selectionChanged.connect(self._selection_changed)
        self.select_bar(1)

    def set_model(self, model: StructuralModel) -> None:
        '''Обновляет схему по текущим исходным данным.

        Args:
            model: Стержни, нагрузки и опоры в системе СИ.
        '''
        selected = next((index for index, bar in enumerate(self._bars) if bar.isSelected()), 0)
        self._model = model
        self.scene().blockSignals(True)
        self.scene().clear()
        self._bars.clear()
        self._load_items.clear()
        self._quantity_labels.clear()
        self._theme_bindings.clear()
        self._build_scene()
        if self._bars:
            self._bars[min(selected, len(self._bars) - 1)].setSelected(True)
        self.scene().blockSignals(False)
        self.fit_model()

    @classmethod
    def replace(cls, original: QGraphicsView, compact: bool = False) -> 'StructureView':
        '''Заменяет стандартный вид формы на специализированный.

        Args:
            original: Виджет, созданный загрузчиком формы Qt Designer.
            compact: Признак стартовой иллюстрации.

        Returns:
            Новый графический вид в том же месте компоновки.
        '''
        parent = original.parentWidget()
        view = cls(parent, compact)
        view.setObjectName(original.objectName())
        view.setMinimumSize(original.minimumSize())
        view.setSizePolicy(original.sizePolicy())
        parent.layout().replaceWidget(original, view)
        original.hide()
        original.deleteLater()
        return view

    def _text(self, x: float, y: float, text: str, color: str = 'muted', size: int = 11):
        '''Добавляет надпись в координатах сцены.

        Args:
            x: Горизонтальная координата.
            y: Вертикальная координата.
            text: Содержимое надписи.
            color: Имя цвета текста в палитре темы.
            size: Размер шрифта в пунктах.

        Returns:
            Созданный текстовый элемент сцены.
        '''
        item = self.scene().addSimpleText(text, QFont('Segoe UI', size))
        item.setBrush(QColor(getattr(self._colors, color)))
        self._theme_bindings.append((item, 'brush', color))
        item.setPos(x, y)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return item

    def _line(self, x1: float, y1: float, x2: float, y2: float, color: str, width: float = 1):
        '''Добавляет отрезок в сцену.

        Args:
            x1: Начальная горизонтальная координата.
            y1: Начальная вертикальная координата.
            x2: Конечная горизонтальная координата.
            y2: Конечная вертикальная координата.
            color: Имя цвета линии в палитре темы.
            width: Толщина линии.

        Returns:
            Созданный графический элемент.
        '''
        item = self.scene().addLine(x1, y1, x2, y2, QPen(QColor(getattr(self._colors, color)), width))
        self._theme_bindings.append((item, 'pen', color))
        return item

    def _arrow(self, start: float, end: float, y: float, color: str) -> list[QGraphicsItem]:
        '''Добавляет горизонтальную стрелку нагрузки.

        Args:
            start: Координата начала стрелки.
            end: Координата острия.
            y: Высота стрелки.
            color: Имя цвета стрелки в палитре темы.

        Returns:
            Элементы линии и наконечника.
        '''
        sign = 1 if end > start else -1
        line = self._line(start, y, end, y, color, 2)
        head = QPolygonF([QPointF(end, y), QPointF(end - sign * 9, y - 4), QPointF(end - sign * 9, y + 4)])
        tint = QColor(getattr(self._colors, color))
        triangle = self.scene().addPolygon(head, QPen(tint), tint)
        self._theme_bindings.extend([(triangle, 'pen', color), (triangle, 'brush', color)])
        return [line, triangle]

    def _build_scene(self) -> None:
        '''Формирует геометрию и обозначения текущей расчётной модели.'''
        if not self._model.bars:
            self._text(100, 135, 'Добавьте стержень', 'muted', 12)
            return
        positions, heights = self._geometry()
        axis = self._line(positions[0] - 45, 150, positions[-1] + 115, 150, 'axis')
        pen = axis.pen()
        pen.setStyle(Qt.PenStyle.DashLine)
        axis.setPen(pen)
        self._text(positions[-1] + 120, 136, 'x', 'muted')
        for index, (left, right, height) in enumerate(zip(positions, positions[1:], heights)):
            bar = BarItem(QRectF(left, 150 - height / 2, right - left, height), index, self._colors)
            self.scene().addItem(bar)
            self._bars.append(bar)
            self._line(left, 250, right, 250, 'dimension')
            self._quantity_text(0, 260, self._model.bars[index].length_m, 'м', 'L', center=(left + right) / 2)
        for index, x in enumerate(positions):
            self._line(x, 230, x, 258, 'dimension')
            tick = self._line(x - 4, 255, x + 4, 245, 'dimension')
            tick.setData(0, 'dimension_tick')
            adjacent = heights[max(0, index - 1):min(len(heights), index + 1)]
            top = 150 - max(adjacent) / 2
            self._line(x, 98, x, top - 4, 'dimension')
            node = self.scene().addEllipse(x - 13, 72, 26, 26, QPen(QColor(self._colors.node_border)), QColor(self._colors.node_fill))
            self._theme_bindings.extend([(node, 'pen', 'node_border'), (node, 'brush', 'node_fill')])
            label = self._text(0, 72, str(index + 1), 'text', 10)
            label.setX(x - label.boundingRect().width() / 2)
            label.setZValue(1)
            if index < len(self._model.supports) and self._model.supports[index]:
                self._support(x, max(adjacent), index == len(positions) - 1)
        if not self._compact:
            self._draw_loads(positions)
        for item in self._load_items:
            item.setVisible(self._loads_visible)

    def _geometry(self) -> tuple[list[float], list[float]]:
        '''Вычисляет размеры изображения без изменения физических величин.

        Returns:
            Координаты узлов и высоты стержней в координатах сцены.
        '''
        bars = self._model.bars
        total = self._model.total_length_m
        maximum_area = max(bar.area_m2 for bar in bars)
        target_width = max(640, len(bars) * 135)
        positions = [100.0]
        heights = []
        conditional_scale = False
        for bar in bars:
            ratio = min(Decimal('1'), max(Decimal('0'), bar.length_m / total)) if total > 0 else Decimal('0')
            width = float(ratio) * target_width
            height = float(bar.area_m2 / maximum_area) * 72 if maximum_area > 0 else 32
            conditional_scale = conditional_scale or width < 120 or height < 18
            positions.append(positions[-1] + max(120, width))
            heights.append(max(18, height))
        self.setToolTip('Масштаб схемы условный' if conditional_scale else '')
        return positions, heights

    def _support(self, x: float, height: float, closing: bool) -> None:
        '''Рисует заделку с одинаковым наклоном всех штрихов.

        Args:
            x: Координата закреплённого узла.
            height: Высота соседнего стержня.
            closing: Признак правой концевой заделки.
        '''
        top = 150 - height / 2 - 12
        bottom = 150 + height / 2 + 12
        edge = self._line(x, top, x, bottom, 'bar_border', 3)
        edge.setZValue(2)
        for y in range(ceil(top + 12), floor(bottom) + 1, 12):
            if closing:
                hatch = self._line(x, y, x + 17, y - 12, 'dimension', 1.4)
            else:
                hatch = self._line(x - 17, y, x, y - 12, 'dimension', 1.4)
            hatch.setData(0, 'support_hatch')
            hatch.setZValue(2)

    def _draw_loads(self, positions: list[float]) -> None:
        '''Добавляет направленные узловые и погонные нагрузки.

        Args:
            positions: Горизонтальные координаты узлов схемы.
        '''
        for index, (position, value) in enumerate(zip(positions, self._model.nodal_forces)):
            if not value:
                continue
            direction = 1 if value > 0 else -1
            neighbour = index if direction > 0 else index - 1
            available = positions[neighbour + 1] - positions[neighbour] if 0 <= neighbour < len(positions) - 1 else 180
            length = min(78, available * 0.36)
            start = position + direction * 5
            end = start + direction * length
            self._load_items.extend(self._arrow(start, end, 150, 'force'))
            self._load_items.append(self._quantity_text(
                0, 192 + 20 * (index % 2), value, 'Н', 'F', 'force', center=(start + end) / 2,
            ))
        for left, right, value in zip(positions, positions[1:], self._model.distributed_loads):
            if not value:
                continue
            count = max(2, int((right - left) / 42))
            step = (right - left - 20) / count
            for index in range(count):
                start = left + 10 + index * step
                end = start + min(28, step - 7)
                if value < 0:
                    start, end = end, start
                self._load_items.extend(self._arrow(start, end, 44, 'distributed'))
            self._load_items.append(self._quantity_text(
                0, 10, value, 'Н/м', 'q', 'distributed', center=(left + right) / 2,
            ))

    def _quantity_text(self, x: float, y: float, value: Decimal, unit: str, prefix: str = '', color: str = 'muted', center: float | None = None):
        '''Добавляет подпись физической величины в СИ.

        Args:
            x: Горизонтальная координата подписи.
            y: Вертикальная координата подписи.
            value: Точное значение в СИ.
            unit: Подпись единицы измерения.
            prefix: Текст перед числом.
            color: Имя цвета подписи в палитре темы.
            center: Центр размерной линии для выравнивания подписи.

        Returns:
            Созданная подпись величины.
        '''
        text = f'{prefix} = {format_quantity(value, self._compact_numbers)} {unit}'
        item = self._text(x, y, text, color, 10)
        self._quantity_labels.append((item, prefix, value, unit, center))
        if center is not None:
            item.setX(center - item.boundingRect().width() / 2)
        return item

    def set_number_format(self, compact: bool) -> None:
        '''Меняет запись чисел в подписях без изменения величин СИ.

        Args:
            compact: Признак краткой автоматической записи чисел.
        '''
        self._compact_numbers = compact
        for item, prefix, value, unit, center in self._quantity_labels:
            item.setText(f'{prefix} = {format_quantity(value, compact)} {unit}')
            if center is not None:
                item.setX(center - item.boundingRect().width() / 2)
        self.fit_model()

    def set_theme(self, colors: ThemeColors) -> None:
        '''Применяет палитру к схеме без изменения масштаба и выбора.

        Args:
            colors: Цвета светлой или тёмной темы.
        '''
        self._colors = colors
        self.setBackgroundBrush(QColor(colors.canvas))
        for item, channel, role in self._theme_bindings:
            color = QColor(getattr(colors, role))
            if channel == 'pen':
                pen = item.pen()
                pen.setColor(color)
                item.setPen(pen)
            else:
                item.setBrush(color)
        for bar in self._bars:
            bar.colors = colors
            bar.update()
        self.viewport().update()

    def select_bar(self, index: int) -> None:
        '''Выделяет стержень по индексу.

        Args:
            index: Индекс существующего стержня.
        '''
        if not 0 <= index < len(self._bars):
            return
        if self._bars[index].isSelected():
            return
        self.scene().blockSignals(True)
        self.scene().clearSelection()
        self._bars[index].setSelected(True)
        self.scene().blockSignals(False)
        self.barSelected.emit(index)

    def _selection_changed(self) -> None:
        '''Сообщает странице об изменении выделенного стержня.'''
        selected = self.scene().selectedItems()
        if selected and isinstance(selected[0], BarItem):
            self.barSelected.emit(selected[0].data(0))

    def set_grid_visible(self, visible: bool) -> None:
        '''Меняет видимость координатной сетки.

        Args:
            visible: Требуемое состояние сетки.
        '''
        self._grid_visible = visible
        self.viewport().update()

    def set_loads_visible(self, visible: bool) -> None:
        '''Меняет видимость обозначений нагрузок.

        Args:
            visible: Требуемое состояние изображения нагрузок.
        '''
        self._loads_visible = visible
        for item in self._load_items:
            item.setVisible(visible)
        self.fit_model()

    def fit_model(self) -> None:
        '''Вписывает модель в доступный размер графического вида.'''
        if not self._bars:
            bounds = QRectF(50, 65, 440, 180)
        else:
            bounds = QRectF()
            for item in self.scene().items():
                if item.isVisible():
                    bounds = bounds.united(item.sceneBoundingRect())
            bounds = bounds.adjusted(-22, -18, 22, 18)
        self.scene().setSceneRect(bounds)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0

    def zoom_by(self, factor: float) -> None:
        '''Изменяет масштаб в пределах читаемого диапазона.

        Args:
            factor: Множитель текущего масштаба.
        '''
        next_zoom = self._zoom * factor
        if 0.55 <= next_zoom <= 24:
            self.scale(factor, factor)
            self._zoom = next_zoom

    def wheelEvent(self, event) -> None:
        '''Масштабирует схему колесом мыши.

        Args:
            event: Событие прокрутки колеса мыши.
        '''
        self.zoom_by(1.12 if event.angleDelta().y() > 0 else 1 / 1.12)
        event.accept()

    def resizeEvent(self, event) -> None:
        '''Вписывает схему после изменения размеров панели.

        Args:
            event: Событие изменения геометрии виджета.
        '''
        super().resizeEvent(event)
        zoom = self._zoom
        self.fit_model()
        if zoom != 1.0:
            self.zoom_by(zoom)

    def showEvent(self, event) -> None:
        '''Обновляет масштаб после первого отображения страницы.

        Args:
            event: Событие показа виджета.
        '''
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_model)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        '''Рисует ненавязчивую координатную сетку.

        Args:
            painter: Контекст отрисовки.
            rect: Видимая область сцены.
        '''
        painter.fillRect(rect, QColor(self._colors.canvas))
        if not self._grid_visible:
            return
        painter.setPen(QPen(QColor(self._colors.grid), 0.6))
        scale = max(self.transform().m11(), 0.0001)
        step = max(28, ceil(18 / scale / 28) * 28)
        for x in range(floor(rect.left() / step) * step, ceil(rect.right()), step):
            for y in range(floor(rect.top() / step) * step, ceil(rect.bottom()), step):
                painter.drawPoint(QPointF(x, y))
