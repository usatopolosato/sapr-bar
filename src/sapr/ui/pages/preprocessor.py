'''Связывает форму препроцессора с демонстрационными данными.'''

from decimal import Decimal

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHeaderView,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ..loader import load_form
from ..formatting import format_quantity
from ..preview_data import PREVIEW_BARS, PREVIEW_LOADS
from ..widgets.structure_view import StructureView


class PreprocessorPage(QWidget):
    '''Управляет просмотром схемы, исходных данных и свойств стержней.

    Args:
        parent: Родительский виджет страницы.
    '''

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        load_form('preprocessor.ui', self)
        self._selected_bar = 1
        self.structure_view = StructureView.replace(self.structureView)
        self.workspaceSplitter.setChildrenCollapsible(False)
        self.workspaceSplitter.setSizes([830, 260])
        self.workspaceSplitter.setStretchFactor(0, 1)
        self.workspaceSplitter.setStretchFactor(1, 0)
        self.modelSplitter.setChildrenCollapsible(False)
        self.modelSplitter.setSizes([300, 300])
        self.modelSplitter.setStretchFactor(0, 1)
        self.modelSplitter.setStretchFactor(1, 1)
        self.dataTabs.tabBar().setDrawBase(False)
        self._modes = QButtonGroup(self)
        for button in (self.constructionButton, self.loadsButton, self.dataButton, self.tablesButton):
            self._modes.addButton(button)
            button.setCheckable(True)
        self._modes.setExclusive(True)
        self.constructionButton.setChecked(True)
        self.constructionButton.clicked.connect(self._show_construction)
        self.loadsButton.clicked.connect(self._show_loads)
        self.dataButton.clicked.connect(self._show_data)
        self.tablesButton.clicked.connect(self._show_tables)
        self.fitButton.clicked.connect(self.structure_view.fit_model)
        self.zoomInButton.clicked.connect(lambda: self.structure_view.zoom_by(1.2))
        self.zoomOutButton.clicked.connect(lambda: self.structure_view.zoom_by(1 / 1.2))
        self.gridButton.toggled.connect(self.structure_view.set_grid_visible)
        self.saveProjectButton.clicked.connect(self._show_project_notice)
        self.numberFormatCombo.currentIndexChanged.connect(self._refresh_numbers)
        self._fill_tables()
        self.barsTable.currentCellChanged.connect(self._table_bar_selected)
        self.structure_view.barSelected.connect(self._select_bar)
        self._select_bar(1)
        self.structure_view.set_number_format(self.numberFormatCombo.currentIndex() == 1)
        self._show_construction()

    @staticmethod
    def _populate(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
        '''Заполняет таблицу и настраивает безопасный режим просмотра.

        Args:
            table: Виджет таблицы из формы.
            rows: Последовательность текстовых строк.
        '''
        table.setRowCount(len(rows))
        table.setShowGrid(False)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumSectionSize(60)
        table.verticalHeader().setDefaultSectionSize(35)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                table.setItem(row_index, column, item)

    def _fill_tables(self) -> None:
        '''Заполняет таблицы неизменяемым примером расчётной модели.'''
        bars = [
            (
                f'{index + 1:02d}', self._format(bar.length_m), self._format(bar.area_m2),
                self._format(bar.modulus_pa), self._format(bar.allowable_stress_pa),
            )
            for index, bar in enumerate(PREVIEW_BARS)
        ]
        coordinates = [Decimal('0')]
        for bar in PREVIEW_BARS:
            coordinates.append(coordinates[-1] + bar.length_m)
        nodes = [
            (f'{index + 1:02d}', self._format(position), 'Жёсткая опора' if index == 0 else 'Свободный')
            for index, position in enumerate(coordinates)
        ]
        self._populate(self.barsTable, bars)
        self._populate(self.nodesTable, nodes)
        loads = [(load.kind, load.element, self._format(load.value_si), load.unit) for load in PREVIEW_LOADS]
        self._populate(self.loadsTable, loads)
        for field in (self.lengthInput, self.areaInput, self.modulusInput, self.stressInput):
            field.setReadOnly(True)

    def _format(self, value: Decimal) -> str:
        '''Форматирует значение СИ согласно выбранному режиму.

        Args:
            value: Значение физической величины.

        Returns:
            Точная десятичная или экспоненциальная запись.
        '''
        return format_quantity(value, self.numberFormatCombo.currentIndex() == 1)

    def _refresh_numbers(self) -> None:
        '''Обновляет представление чисел без изменения исходных величин.'''
        index = self._selected_bar
        self.barsTable.blockSignals(True)
        self._fill_tables()
        self.barsTable.blockSignals(False)
        self._select_bar(index)
        self.structure_view.set_number_format(self.numberFormatCombo.currentIndex() == 1)

    def _select_bar(self, index: int) -> None:
        '''Согласует выбранную строку, стержень и панель свойств.

        Args:
            index: Индекс выбранного демонстрационного стержня.
        '''
        if not 0 <= index < len(PREVIEW_BARS):
            return
        self._selected_bar = index
        bar = PREVIEW_BARS[index]
        self.selectedBarLabel.setText(f'Стержень {index + 1:02d}')
        self.lengthInput.setText(self._format(bar.length_m))
        self.areaInput.setText(self._format(bar.area_m2))
        self.modulusInput.setText(self._format(bar.modulus_pa))
        self.stressInput.setText(self._format(bar.allowable_stress_pa))
        self.barsTable.blockSignals(True)
        self.barsTable.selectRow(index)
        self.barsTable.blockSignals(False)
        self.structure_view.select_bar(index)

    def _table_bar_selected(self, row: int, column: int, previous_row: int, previous_column: int) -> None:
        '''Передаёт выбор строки в схему и панель свойств.

        Args:
            row: Текущая строка.
            column: Текущий столбец.
            previous_row: Предыдущая строка.
            previous_column: Предыдущий столбец.
        '''
        self._select_bar(row)

    def _show_construction(self) -> None:
        '''Показывает геометрию конструкции и таблицу стержней.'''
        self.structure_view.set_loads_visible(False)
        self.dataTabs.setCurrentIndex(0)
        self.modelSplitter.setSizes([300, 300])

    def _show_loads(self) -> None:
        '''Показывает схему нагрузок и соответствующую таблицу.'''
        self.structure_view.set_loads_visible(True)
        self.dataTabs.setCurrentIndex(2)
        self.modelSplitter.setSizes([300, 300])

    def _show_data(self) -> None:
        '''Открывает таблицу узлов для просмотра исходных данных.'''
        self.dataTabs.setCurrentIndex(1)
        self.modelSplitter.setSizes([320, 310])

    def _show_tables(self) -> None:
        '''Увеличивает панель табличного представления модели.'''
        self.dataTabs.setCurrentIndex(0)
        self.modelSplitter.setSizes([260, 370])

    def _show_project_notice(self) -> None:
        '''Объясняет назначение будущей операции сохранения проекта.'''
        message = QMessageBox(self)
        message.setWindowTitle('Файл проекта')
        message.setText('Сохранение проекта будет добавлено на следующем этапе')
        message.setInformativeText('Сейчас доступен просмотр демонстрационной модели')
        message.addButton('Понятно', QMessageBox.ButtonRole.AcceptRole)
        message.exec()

