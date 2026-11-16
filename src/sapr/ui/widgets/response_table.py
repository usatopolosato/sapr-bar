'''Представляет сечения стержней без хранения полной таблицы отсчётов.'''

from bisect import bisect_left, bisect_right
from collections import OrderedDict
from decimal import Context, Decimal, localcontext

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from ...domain.postprocessor import PostprocessorResult
from ..theme import LIGHT_COLORS, ThemeColors
from .linear_system import number_text


class ResponseTableModel(QAbstractTableModel):
    '''Вычисляет только запрошенные строки таблицы результатов.

    Args:
        result: Результаты восстановления компонент НДС.
        subdivisions: Число равномерных интервалов на стержне.
        extrema_only: Признак вывода только концов и экстремумов.
        selected_bar: Индекс стержня или None для всей конструкции.
        compact: Признак краткого представления чисел.
        parent: Родитель модели Qt.
    '''

    HEADERS = ('Стержень', 'x, м', 'N, Н', 'σ, Па', 'u, м')

    def __init__(self, result: PostprocessorResult, subdivisions: int = 10,
                 extrema_only: bool = False, selected_bar: int | None = None,
                 compact: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.result = result
        self.subdivisions = max(1, min(1000, subdivisions))
        self.compact = compact
        self.colors = LIGHT_COLORS
        self._extrema_only = extrema_only
        self._bars = result.bars if selected_bar is None else (result.bars[selected_bar],)
        self._offsets = [0]
        self._extra_positions = []
        self._extra_rows = []
        self._sections = OrderedDict()
        with localcontext(Context(prec=result.precision)):
            for bar in self._bars:
                if extrema_only:
                    positions = {Decimal(0), bar.geometry.length_m}
                    for component in ('N', 'sigma', 'u'):
                        positions.update(section.x_m for section in bar.extrema(component))
                    extras = tuple(sorted(positions))
                    extra_rows = ()
                    count = len(extras)
                else:
                    extras = tuple(x for x in bar.critical_positions()
                                   if self._grid_position(bar, x) is None)
                    extra_rows = tuple(int(x * self.subdivisions / bar.geometry.length_m) + 1 + i
                                       for i, x in enumerate(extras))
                    count = self.subdivisions + 1 + len(extras)
                self._extra_positions.append(extras)
                self._extra_rows.append(extra_rows)
                self._offsets.append(self._offsets[-1] + count)

    def _grid_position(self, bar, x: Decimal) -> int | None:
        '''Определяет совпадение характерной точки с равномерным отсчётом.'''
        candidate = int((x * self.subdivisions / bar.geometry.length_m).to_integral_value())
        return candidate if bar.geometry.length_m * candidate / self.subdivisions == x else None

    def rowCount(self, parent=QModelIndex()) -> int:
        '''Возвращает количество строк без материализации их значений.'''
        return 0 if parent.isValid() else self._offsets[-1]

    def columnCount(self, parent=QModelIndex()) -> int:
        '''Возвращает число отображаемых свойств сечения.'''
        return 0 if parent.isValid() else len(self.HEADERS)

    def section(self, row: int):
        '''Находит стержень и аналитически вычисляет выбранное сечение.

        Args:
            row: Индекс строки таблицы.

        Returns:
            Точные компоненты НДС в соответствующем сечении.
        '''
        if not 0 <= row < self.rowCount():
            raise IndexError('Строка таблицы находится вне диапазона')
        if row in self._sections:
            self._sections.move_to_end(row)
            return self._sections[row]
        position = bisect_right(self._offsets, row) - 1
        bar = self._bars[position]
        local_row = row - self._offsets[position]
        extras = self._extra_positions[position]
        if self._extrema_only:
            x = extras[local_row]
        else:
            extra_rows = self._extra_rows[position]
            extra = bisect_left(extra_rows, local_row)
            if extra < len(extra_rows) and extra_rows[extra] == local_row:
                x = extras[extra]
            else:
                grid_row = local_row - extra
                with localcontext(Context(prec=self.result.precision)):
                    x = bar.geometry.length_m * grid_row / self.subdivisions
        section = bar.at(x)
        self._sections[row] = section
        if len(self._sections) > 256:
            self._sections.popitem(last=False)
        return section

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        '''Отдаёт текст, точный Decimal и оформление превышений допуска.'''
        if not index.isValid() or not 0 <= index.row() < self.rowCount():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.UserRole,
                        Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole):
            return None
        section = self.section(index.row())
        limit = self.result.bars[section.bar_index].geometry.allowable_stress_pa
        exceeded = section.stress_pa.copy_abs() > limit
        if role in (Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole):
            if exceeded and index.column() == 3:
                return QColor(self.colors.error_text if role == Qt.ItemDataRole.ForegroundRole
                              else self.colors.error_background)
            return None
        status = 'Превышение' if exceeded else 'На пределе' if section.stress_pa.copy_abs() == limit else 'В пределах допуска'
        values = (section.bar_index + 1, section.x_m, section.force_n, section.stress_pa, section.displacement_m)
        value = values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return value
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 3:
            return f'{value} Па\nДопуск {limit} Па\n{status}'
        if isinstance(value, Decimal):
            return number_text(value, self.compact if role == Qt.ItemDataRole.DisplayRole else False)
        return str(value)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        '''Подписывает компоненты результата и единицы СИ.'''
        if role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section] if orientation == Qt.Orientation.Horizontal else str(section + 1)
        return None

    def set_theme(self, colors: ThemeColors) -> None:
        '''Обновляет цвета превышений при переключении общей темы.'''
        self.colors = colors
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1),
                                  [Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole])
