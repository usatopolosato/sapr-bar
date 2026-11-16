'''Показывает разреженную систему без создания плотной матрицы в памяти.'''

from decimal import Decimal

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QWidget

from ...domain.processor import LinearSystem, ProcessorResult
from ..formatting import format_quantity
from ..loader import load_form


def number_text(value: Decimal, compact: bool) -> str:
    '''Форматирует только представление, сохраняя полную точность результата.'''
    if not value:
        return '0'
    return format_quantity(value, compact=True) if compact else str(value)


def configure_result_table(view) -> None:
    '''Настраивает доступную с клавиатуры таблицу только для чтения.'''
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setAlternatingRowColors(True)
    view.setWordWrap(False)
    view.setShowGrid(False)
    view.verticalHeader().setDefaultSectionSize(40)
    view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    view.horizontalHeader().setMinimumHeight(38)
    view.horizontalHeader().setDefaultSectionSize(132)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    view.setFont(QFont('Consolas', 10))


class SystemTableModel(QAbstractTableModel):
    '''Отдаёт ячейки матрицы или вектора по запросу видимой области.'''

    def __init__(self, system: LinearSystem, kind: str, compact: bool, parent=None) -> None:
        super().__init__(parent)
        self.system, self.kind, self.compact = system, kind, compact
        self.elimination_row = None

    def rowCount(self, parent=QModelIndex()) -> int:
        '''Возвращает число глобальных узлов.'''
        return 0 if parent.isValid() else len(self.system.diagonal)

    def columnCount(self, parent=QModelIndex()) -> int:
        '''Возвращает число столбцов выбранного операнда.'''
        return 0 if parent.isValid() else (self.rowCount() if self.kind == 'matrix' else 1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        '''Возвращает текст и точное значение без округления исходных данных.'''
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.FontRole and self.kind == 'matrix' and index.row() == self.elimination_row and index.column() == index.row() - 1:
            font = QFont('Consolas', 10)
            font.setBold(True)
            return font
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.UserRole):
            return None
        row, column = index.row(), index.column()
        if self.kind == 'delta':
            return f'Δ{row + 1}'
        value = self.system.coefficient(row, column) if self.kind == 'matrix' else self.system.rhs[row]
        if role == Qt.ItemDataRole.UserRole:
            return value
        return number_text(value, self.compact if role == Qt.ItemDataRole.DisplayRole else False)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        '''Подписывает строки узлами, столбцы неизвестными и единицами.'''
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        return str(section + 1) if self.kind == 'matrix' else ('Δ, м' if self.kind == 'delta' else 'b, Н')


class NodeTableModel(QAbstractTableModel):
    '''Показывает уравнения или итоговый вектор по одному узлу в строке.'''

    def __init__(self, result: ProcessorResult, equations: bool, compact: bool, parent=None) -> None:
        super().__init__(parent)
        self.result, self.equations, self.compact = result, equations, compact

    def rowCount(self, parent=QModelIndex()) -> int:
        '''Возвращает число перемещений.'''
        return 0 if parent.isValid() else len(self.result.displacements)

    def columnCount(self, parent=QModelIndex()) -> int:
        '''Возвращает один столбец вектора или уравнений.'''
        return 0 if parent.isValid() else 1

    def equation(self, row: int, compact: bool) -> str:
        '''Формирует числовую строку системы после граничных условий.'''
        if self.result.model.supports[row]:
            return f'Δ{row + 1} = 0'
        terms = []
        for column, value in self.result.constrained.row_terms(row):
            sign = (' - ' if value < 0 else ' + ') if terms else ('-' if value < 0 else '')
            terms.append(f'{sign}{number_text(value.copy_abs(), compact)} * Δ{column + 1}')
        return ''.join(terms) + ' = ' + number_text(self.result.constrained.rhs[row], compact)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        '''Возвращает уравнение узла или его перемещение в метрах.'''
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.UserRole):
            return None
        row = index.row()
        compact = self.compact if role == Qt.ItemDataRole.DisplayRole else False
        if self.equations:
            return self.equation(row, compact)
        value = self.result.displacements[row]
        return value if role == Qt.ItemDataRole.UserRole else number_text(value, compact)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        '''Показывает номер узла или обозначение перемещения.'''
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return f'Узел {section + 1}' if self.equations else f'Δ{section + 1}'
        return 'Уравнение узла' if self.equations else 'Перемещение, м'


class LinearSystemView(QWidget):
    '''Согласует прокрутку трёх операндов A * delta = b.'''

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        load_form('linear_system.ui', self)
        self._models = []
        self._views = (self.matrixView, self.deltaView, self.rhsView)
        self.systemLayout.setStretch(0, 1)
        self._sizing = False
        for view in self._views:
            configure_result_table(view)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            view.verticalScrollBar().valueChanged.connect(self._scroll_rows)
        self.matrixView.horizontalScrollBar().rangeChanged.connect(self._sync_viewports)
        self.matrixView.verticalScrollBar().rangeChanged.connect(self._sync_viewports)
        for view in self._views[1:]:
            view.verticalHeader().hide()
            view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def set_system(self, system: LinearSystem, compact: bool) -> None:
        '''Заменяет шаг системы, сохраняя положение просмотра.'''
        position = self.matrixView.verticalScrollBar().value()
        selected = self.matrixView.currentIndex().row()
        for model in self._models:
            model.deleteLater()
        self._models = []
        for view, kind in zip(self._views, ('matrix', 'delta', 'rhs')):
            model = SystemTableModel(system, kind, compact, self)
            self._models.append(model)
            view.setModel(model)
            view.selectionModel().currentRowChanged.connect(self._select_row)
        if 0 <= selected < len(system.diagonal):
            self.matrixView.selectRow(selected)
        self.matrixView.verticalScrollBar().setValue(position)
        self.setMaximumHeight(40 * len(system.diagonal) + 54)
        self._size_columns()
        QTimer.singleShot(0, self._size_columns)
        QTimer.singleShot(0, self._sync_viewports)

    def _size_columns(self) -> None:
        '''Растягивает небольшую матрицу, оставляя большим горизонтальную прокрутку.'''
        model = self.matrixView.model()
        if model is None:
            return
        fits = model.columnCount() * 95 <= self.matrixView.viewport().width()
        mode = QHeaderView.ResizeMode.Stretch if fits else QHeaderView.ResizeMode.Interactive
        self.matrixView.horizontalHeader().setSectionResizeMode(mode)

    def focus_elimination(self, row: int) -> None:
        '''Выделяет изменяемую строку и делает исключаемый коэффициент заметным.'''
        model = self.matrixView.model()
        model.elimination_row = row
        target = model.index(row, row - 1)
        model.dataChanged.emit(target, target, [Qt.ItemDataRole.FontRole])
        self.matrixView.setCurrentIndex(target)
        self.matrixView.scrollTo(target)

    def _sync_viewports(self, *args) -> None:
        '''Выравнивает высоту областей при появлении полосы прокрутки у матрицы.'''
        if self._sizing:
            return
        self._sizing = True
        horizontal = self.matrixView.horizontalScrollBar().maximum() > 0
        vertical = self.matrixView.verticalScrollBar().maximum() > 0
        for view in self._views[1:]:
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn if horizontal else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn if vertical else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._sizing = False

    def resizeEvent(self, event) -> None:
        '''Пересчитывает ширину столбцов при изменении доступного места.'''
        super().resizeEvent(event)
        self._size_columns()
        QTimer.singleShot(0, self._size_columns)
        self._sync_viewports()

    def _scroll_rows(self, value: int) -> None:
        '''Удерживает узлы трёх операндов на одной горизонтали.'''
        for view in self._views:
            view.verticalScrollBar().setValue(value)

    def _select_row(self, current, previous) -> None:
        '''Выделяет один и тот же узел во всех операндах.'''
        if current.isValid():
            for view in self._views:
                if view.currentIndex().row() != current.row():
                    view.selectRow(current.row())
