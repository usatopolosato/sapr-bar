'''Показывает обратный ход по коэффициентам завершённого расчёта.'''

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...domain.processor import ProcessorResult
from ..math_notation import formula_html
from .linear_system import number_text


class BackSubstitutionModel(QAbstractTableModel):
    '''Выдаёт подстановки от последнего узла к первому без повторного решения.

    Args:
        result: Сохранённая система после прямого хода и её решение.
        compact: Признак округления только отображаемых чисел.
        parent: Родитель модели Qt.
    '''

    def __init__(self, result: ProcessorResult, compact: bool, parent=None) -> None:
        super().__init__(parent)
        self.result = result
        self.compact = compact

    def rowCount(self, parent=QModelIndex()) -> int:
        '''Возвращает число узлов в порядке обратного хода.'''
        return 0 if parent.isValid() else len(self.result.displacements)

    def columnCount(self, parent=QModelIndex()) -> int:
        '''Возвращает столбцы подстановки и результата.'''
        return 0 if parent.isValid() else 2

    def node_index(self, row: int) -> int:
        '''Переводит строку таблицы в индекс узла исходной системы.'''
        return len(self.result.displacements) - 1 - row

    def formula(self, row: int) -> str:
        '''Выражает перемещение через коэффициенты после прямого хода.'''
        index = self.node_index(row)
        node = index + 1
        system = self.result.eliminated
        if index == len(system.diagonal) - 1 or not system.upper[index]:
            return f'Δ{node} = b{node} / A{node},{node}'
        return f'Δ{node} = (b{node} - A{node},{node + 1} * Δ{node + 1}) / A{node},{node}'

    def substitution(self, row: int, compact: bool) -> str:
        '''Подставляет сохранённые коэффициенты и уже найденное перемещение.

        Args:
            row: Строка таблицы, нумерация с последнего узла.
            compact: Признак краткого отображения десятичных значений.

        Returns:
            Выражение для выбранного узла без повторного округления расчёта.
        '''
        index = self.node_index(row)
        system = self.result.eliminated
        rhs = number_text(system.rhs[index], compact)
        diagonal = number_text(system.diagonal[index], compact)
        if index == len(system.diagonal) - 1 or not system.upper[index]:
            return f'Δ{index + 1} = {rhs} / {diagonal}'
        upper = number_text(system.upper[index], compact)
        following = number_text(self.result.displacements[index + 1], compact)
        return f'Δ{index + 1} = ({rhs} - ({upper}) * ({following})) / {diagonal}'

    def details(self, row: int) -> str:
        '''Показывает формулу, известное перемещение, подстановку и результат.'''
        index = self.node_index(row)
        lines = [self.formula(row)]
        system = self.result.eliminated
        if index < len(system.upper) and system.upper[index]:
            following = number_text(self.result.displacements[index + 1], self.compact)
            lines.append(f'Найдено ранее   Δ{index + 2} = {following} м')
        lines.append(self.substitution(row, self.compact))
        value = number_text(self.result.displacements[index], self.compact)
        lines.append(f'Δ{index + 1} = {value} м')
        if self.result.model.supports[index]:
            lines.append('Узел закреплён')
        return '\n'.join(lines)

    def details_html(self, row: int) -> str:
        '''Оформляет формулу и подстановку с привычными нижними индексами.'''
        return formula_html(self.details(row))

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        '''Возвращает текст подстановки или точное Decimal перемещения.'''
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.UserRole):
            return None
        row = index.row()
        compact = self.compact if role == Qt.ItemDataRole.DisplayRole else False
        if index.column() == 0:
            return self.substitution(row, compact)
        value = self.result.displacements[self.node_index(row)]
        return value if role == Qt.ItemDataRole.UserRole else number_text(value, compact)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        '''Показывает номера узлов в порядке фактического вычисления.'''
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return f'Узел {self.node_index(section) + 1}'
        return ('Подстановка', 'Δ, м')[section]
