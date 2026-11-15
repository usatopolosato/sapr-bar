'''Отрисовывает интерактивную демонстрационную стержневую систему.'''

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

from ..preview_data import PREVIEW_BARS, PREVIEW_LOADS
from ..formatting import format_quantity
from ..theme import DARK_COLORS, ThemeColors


class BarItem(QGraphicsRectItem):
    '''Представляет выбираемый стержень в графической сцене.

    Args:
        rect: Границы изображения стержня.
        index: Индекс стержня в демонстрационном наборе.
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
        self.setAccessibleDescription('Три стержня - выбор также доступен в таблице стержней')
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(0, 0, 900, 290)
        self._build_scene()
        self.scene().selectionChanged.connect(self._selection_changed)
        self.select_bar(1)

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
        '''Формирует демонстрационную схему без выполнения расчётов.'''
        axis = self._line(60, 150, 845, 150, 'axis')
        pen = axis.pen()
        pen.setStyle(Qt.PenStyle.DashLine)
        axis.setPen(pen)
        self._text(846, 136, 'x', 'muted')
        positions = [100.0]
        total_length = sum((bar.length_m for bar in PREVIEW_BARS), Decimal('0'))
        for bar in PREVIEW_BARS:
            positions.append(positions[-1] + float(bar.length_m / total_length * Decimal('640')))
        heights = [44, 64, 50]
        for index, (left, right, height) in enumerate(zip(positions, positions[1:], heights)):
            bar = BarItem(QRectF(left, 150 - height / 2, right - left, height), index, self._colors)
            self.scene().addItem(bar)
            self._bars.append(bar)
            self._line(left, 190, left, 218, 'dimension')
            self._line(right, 190, right, 218, 'dimension')
            self._line(left, 210, right, 210, 'dimension')
            self._line(left - 4, 215, left + 4, 205, 'dimension')
            self._line(right - 4, 215, right + 4, 205, 'dimension')
            self._quantity_text(0, 222, PREVIEW_BARS[index].length_m, 'м', center=(left + right) / 2)
        self._line(98, 108, 98, 192, 'bar_border', 3)
        for y in range(116, 201, 12):
            self._line(81, y, 98, y - 12, 'dimension', 1.4)
        for index, x in enumerate(positions):
            self._line(x, 101, x, 114, 'dimension')
            node = self.scene().addEllipse(x - 13, 75, 26, 26, QPen(QColor(self._colors.node_border)), QColor(self._colors.node_fill))
            self._theme_bindings.extend([(node, 'pen', 'node_border'), (node, 'brush', 'node_fill')])
            label = self._text(x - 5, 75, str(index + 1), 'text', 10)
            label.setZValue(1)
        if not self._compact:
            self._load_items.extend(self._arrow(positions[1] - 3, positions[1] - 92, 150, 'force'))
            self._load_items.extend(self._arrow(positions[-1] + 6, positions[-1] + 95, 150, 'force'))
            self._load_items.append(self._quantity_text(positions[1] - 88, 180, PREVIEW_LOADS[0].value_si, 'Н', 'F', 'force'))
            self._load_items.append(self._quantity_text(positions[-1] + 9, 180, PREVIEW_LOADS[1].value_si, 'Н', 'F', 'force'))
            for x in range(int(positions[1]) + 9, int(positions[2]) - 20, 40):
                self._load_items.extend(self._arrow(x, x + 28, 50, 'distributed'))
            self._load_items.append(self._quantity_text(positions[1] + 60, 15, PREVIEW_LOADS[2].value_si, 'Н на м', 'q', 'distributed'))
        self._quantity_text(100, 258, total_length, 'м', 'L')

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
        text = f'{prefix} {format_quantity(value, self._compact_numbers)} {unit}'.strip()
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
            item.setText(f'{prefix} {format_quantity(value, compact)} {unit}'.strip())
            if center is not None:
                item.setX(center - item.boundingRect().width() / 2)

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
            index: Индекс существующего демонстрационного стержня.
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
        '''Меняет видимость демонстрационных нагрузок.

        Args:
            visible: Требуемое состояние изображения нагрузок.
        '''
        self._loads_visible = visible
        for item in self._load_items:
            item.setVisible(visible)
        self.fit_model()

    def fit_model(self) -> None:
        '''Вписывает модель в доступный размер графического вида.'''
        bounds = QRectF(55, 8, 815, 270) if self._loads_visible else QRectF(55, 68, 815, 210)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0

    def zoom_by(self, factor: float) -> None:
        '''Изменяет масштаб в пределах читаемого диапазона.

        Args:
            factor: Множитель текущего масштаба.
        '''
        next_zoom = self._zoom * factor
        if 0.55 <= next_zoom <= 3.5:
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
        self.fit_model()

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
        step = 28
        for x in range(floor(rect.left() / step) * step, ceil(rect.right()), step):
            for y in range(floor(rect.top() / step) * step, ceil(rect.bottom()), step):
                painter.drawPoint(QPointF(x, y))
