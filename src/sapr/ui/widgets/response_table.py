'''Представляет сечения стержней без хранения полной таблицы отсчётов.'''

from bisect import bisect_right
from collections import OrderedDict
from decimal import Decimal

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from ...domain.postprocessor import PostprocessorResult
from ...domain.sampling import BarSamples
from ...formatting import format_quantity, format_result
from ..theme import LIGHT_COLORS, ThemeColors
from .linear_system import number_text


class ResponseTableModel(QAbstractTableModel):
    '''Вычисляет только запрошенные строки таблицы результатов.

    Args:
        result: Результаты восстановления компонент НДС.
        subdivisions: Число равномерных интервалов на стержне.
        extrema_only: Выводить подписанные минимум и максимум каждой величины.
        selected_bar: Индекс стержня или None для всей конструкции.
        compact: Признак краткого представления чисел.
        parent: Родитель модели Qt.
        component: N, sigma, u или None для всех величин.
    '''

    HEADERS = ('Стержень', 'x, м', 'N, Н', 'σ, Па', 'u, м')
    COMPONENTS = {'N': 'N, Н', 'sigma': 'σ, Па', 'u': 'u, м'}

    def __init__(self, result: PostprocessorResult, subdivisions: int = 10,
                 extrema_only: bool = False, selected_bar: int | None = None,
                 compact: bool = True, parent=None, *, places: int = 6, step: Decimal | None = None,
                 component: str | None = None) -> None:
        super().__init__(parent)
        if component is not None and component not in self.COMPONENTS:
            raise ValueError('Выберите продольную силу, напряжение или перемещение')
        self.result = result
        self.component = component
        self._components = (component,) if component else tuple(self.COMPONENTS)
        self.subdivisions = max(1, min(1000, subdivisions))
        self.compact = compact
        self.places = places
        self.colors = LIGHT_COLORS
        self._extrema_only = extrema_only
        self.headers = self._column_headers()
        self._bars = result.bars if selected_bar is None else (result.bars[selected_bar],)
        self._offsets = [0]
        self._extra_positions = []
        self._sections = OrderedDict()
        self._samples = []
        for bar in self._bars:
            if extrema_only:
                row_count = 2 * len(self._components)
            else:
                sample = BarSamples(bar, self.subdivisions, step=step)
                self._samples.append(sample)
                self._extra_positions.append(sample.extras)
                row_count = sample.count
            self._offsets.append(self._offsets[-1] + row_count)
        if self._offsets[-1] > BarSamples.MAX_ROWS:
            raise ValueError('Слишком много сечений. Увеличьте шаг или уменьшите число разбиений')

    def _column_headers(self) -> tuple[str, ...]:
        if self._extrema_only:
            if self.component is None:
                return ('Стержень', 'Величина', 'Экстремум', 'x, м', 'Значение')
            return ('Стержень', 'Экстремум', 'x, м', self.COMPONENTS[self.component])
        if self.component is None:
            return self.HEADERS
        return ('Стержень', 'x, м', self.COMPONENTS[self.component])

    def _extremum(self, row: int) -> tuple[str, int]:
        # Для каждой величины первая строка содержит минимум, вторая максимум.
        component_number = (row // 2) % len(self._components)
        return self._components[component_number], row % 2

    def rowCount(self, parent=QModelIndex()) -> int:
        '''Возвращает количество строк без материализации их значений.'''
        return 0 if parent.isValid() else self._offsets[-1]

    def columnCount(self, parent=QModelIndex()) -> int:
        '''Возвращает число отображаемых свойств сечения.'''
        return 0 if parent.isValid() else len(self.headers)

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
        if self._extrema_only:
            component, extremum = self._extremum(row)
            section = bar.extrema(component)[extremum]
        else:
            x = self._samples[position].position(local_row)
            section = bar.at(x)
        self._sections[row] = section
        if len(self._sections) > 256:
            self._sections.popitem(last=False)
        return section

    def _row_values(self, row, section):
        '''Возвращает ячейки строки и номер столбца с напряжением для подсветки.'''
        bar_number = section.bar_index + 1
        if self._extrema_only:
            component, extremum = self._extremum(row)
            kind = ('Минимум', 'Максимум')[extremum]
            value = section.value(component)
            if self.component is None:
                values = (bar_number, self.COMPONENTS[component], kind, section.x_m, value)
            else:
                values = (bar_number, kind, section.x_m, value)
            stress_column = len(values) - 1 if component == 'sigma' else None
            return values, stress_column
        if self.component is not None:
            values = (bar_number, section.x_m, section.value(self.component))
            return values, 2 if self.component == 'sigma' else None
        return (bar_number, section.x_m, section.force_n, section.stress_pa, section.displacement_m), 3

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        '''Отдаёт текст, точный Decimal и оформление превышений допуска.'''
        if (not index.isValid() or not 0 <= index.row() < self.rowCount()
                or not 0 <= index.column() < self.columnCount()):
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.UserRole,
                        Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole):
            return None
        section = self.section(index.row())
        values, stress_column = self._row_values(index.row(), section)
        limit = self.result.bars[section.bar_index].geometry.allowable_stress_pa
        stress = section.stress_pa.copy_abs()
        if role in (Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole):
            if index.column() != stress_column or stress <= limit:
                return None
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor(self.colors.error_text)
            return QColor(self.colors.error_background)
        value = values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return value
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == stress_column:
            if stress > limit:
                status = 'Превышение'
            elif stress == limit:
                status = 'На пределе'
            else:
                status = 'В пределах допуска'
            return f'{value} Па\nДопуск {limit} Па\n{status}'
        if isinstance(value, Decimal):
            if role == Qt.ItemDataRole.DisplayRole:
                return format_result(value, self.places) if self.compact else format_quantity(value)
            return number_text(value, False)
        return str(value)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        '''Подписывает компоненты результата и единицы СИ.'''
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.headers[section] if 0 <= section < len(self.headers) else None
            return str(section + 1)
        return None

    def set_theme(self, colors: ThemeColors) -> None:
        '''Обновляет цвета превышений при переключении общей темы.'''
        self.colors = colors
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1),
                                  [Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole])
