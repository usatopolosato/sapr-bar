'''Редактирует исходные данные стержневой конструкции в единицах СИ.'''

import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QHeaderView, QLineEdit, QMessageBox,
    QScrollArea, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QWidget,
)

from ...domain import Bar, StructuralModel, validate_model
from ..formatting import format_quantity
from ..loader import load_form
from ..widgets.structure_view import StructureView


ZERO = Decimal('0')
NUMBER_PATTERN = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')


class DecimalDelegate(QStyledItemDelegate):
    '''Открывает точное значение независимо от формата таблицы.'''

    def createEditor(self, parent, option, index):
        '''Создаёт текстовый редактор без преобразования в float.

        Args:
            parent: Родитель редактора.
            option: Параметры представления ячейки.
            index: Индекс редактируемой ячейки.

        Returns:
            Поле ввода десятичной записи.
        '''
        editor = QLineEdit(parent)
        editor.setMaxLength(4096)
        return editor

    def setEditorData(self, editor, index) -> None:
        '''Переносит точную запись в поле ввода.

        Args:
            editor: Поле ввода значения.
            index: Индекс редактируемой ячейки.
        '''
        value = index.data(Qt.ItemDataRole.UserRole)
        editor.setText(str(value) if value is not None else index.data())
        editor.selectAll()


class PreprocessorPage(QWidget):
    '''Связывает редактируемую модель, таблицы и расчётную схему.

    Args:
        parent: Родительский виджет страницы.
    '''

    modelChanged = pyqtSignal(object)
    saveRequested = pyqtSignal()
    validateRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        load_form('preprocessor.ui', self)
        self._model = StructuralModel()
        self._selected_bar = -1
        self._adding_bar = False
        self._updating = False
        self._narrow = None
        self._load_rows = []
        self._load_target = None
        self._support_node = 0
        self._invalid_cells = {}
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.timeout.connect(self._scroll_inspector_into_view)
        self.structure_view = StructureView.replace(self.structureView)
        self.pageLayout.setStretch(0, 0)
        self.pageLayout.setStretch(1, 0)
        self.pageLayout.setStretch(2, 1)
        self.canvasCard.setMinimumHeight(275)
        self._bar_fields = (self.lengthInput, self.areaInput, self.modulusInput, self.stressInput)
        self._bar_attributes = ('length_m', 'area_m2', 'modulus_pa', 'allowable_stress_pa')
        for splitter in (self.workspaceSplitter, self.modelSplitter):
            splitter.setChildrenCollapsible(False)
            splitter.setStretchFactor(0, 1)
        self.workspaceSplitter.setSizes([800, 310])
        self.modelSplitter.setSizes([320, 290])
        self.dataLayout.removeWidget(self.dataActions)
        self.dataTabs.setCornerWidget(self.dataActions, Qt.Corner.TopRightCorner)
        for tabs in (self.dataTabs, self.inspectorTabs):
            tabs.tabBar().setDrawBase(False)
        for table in (self.barsTable, self.nodesTable, self.loadsTable):
            self._configure_table(table)
        self.addBarButton.clicked.connect(self._start_bar)
        self.removeBarButton.clicked.connect(self._remove_bar)
        self.applyBarButton.clicked.connect(self._apply_bar)
        self.cancelBarButton.clicked.connect(self._cancel_bar)
        self.applyLoadButton.clicked.connect(self._apply_load)
        self.removeLoadButton.clicked.connect(self._remove_load)
        self.loadKindCombo.currentIndexChanged.connect(self._load_kind_changed)
        self.loadElementCombo.currentIndexChanged.connect(self._load_element_changed)
        self.supportNodeCombo.currentIndexChanged.connect(self._support_node_selected)
        self._support_group = QButtonGroup(self)
        self._support_group.addButton(self.freeSupportButton, 0)
        self._support_group.addButton(self.fixedSupportButton, 1)
        self._support_group.idClicked.connect(lambda choice: self._set_selected_support(bool(choice)))
        self.saveProjectButton.clicked.connect(self._request_save)
        self.validateButton.clicked.connect(self._validate)
        self.fitButton.clicked.connect(self.structure_view.fit_model)
        self.zoomInButton.clicked.connect(lambda: self.structure_view.zoom_by(1.2))
        self.zoomOutButton.clicked.connect(lambda: self.structure_view.zoom_by(1 / 1.2))
        self.gridButton.toggled.connect(self.structure_view.set_grid_visible)
        self.loadsVisibleButton.toggled.connect(self.structure_view.set_loads_visible)
        self.numberFormatCombo.currentIndexChanged.connect(self._refresh_numbers)
        self.numberFormatCombo.setToolTip('Кратко - до трёх знаков после точки в мантиссе\nТочно - полное значение')
        self.barsTable.currentCellChanged.connect(self._table_bar_selected)
        self.barsTable.itemChanged.connect(self._bar_cell_changed)
        self.nodesTable.itemChanged.connect(self._node_cell_changed)
        self.nodesTable.currentCellChanged.connect(self._table_node_selected)
        self.loadsTable.itemChanged.connect(self._load_cell_changed)
        self.loadsTable.currentCellChanged.connect(self._table_load_selected)
        self.dataTabs.currentChanged.connect(self._show_data_editor)
        self.structure_view.barSelected.connect(self._select_bar)
        self._refresh()

    @property
    def model(self) -> StructuralModel:
        '''Возвращает текущие исходные данные в единицах СИ.'''
        return self._model

    def set_model(self, model: StructuralModel) -> None:
        '''Заменяет модель при создании или открытии проекта.

        Args:
            model: Исходные данные выбранного проекта.
        '''
        self._model = model
        self._selected_bar = 0 if model.bars else -1
        self._adding_bar = False
        self._load_target = None
        self._support_node = 0
        self._invalid_cells.clear()
        self.inspectorTabs.setCurrentIndex(0)
        for field in self._bar_fields:
            field.setModified(False)
        self.loadValueInput.setModified(False)
        self.show_status('')
        self._refresh()

    def show_status(self, text: str) -> None:
        '''Показывает результат операции или ошибку ввода.

        Args:
            text: Сообщение для пользователя или пустая строка.
        '''
        self.statusLabel.setText(text)
        self.statusLabel.setVisible(bool(text))

    @staticmethod
    def _parse(text: str, positive: bool = False) -> Decimal:
        '''Разбирает десятичное значение без промежуточного float.

        Args:
            text: Десятичная или экспоненциальная запись.
            positive: Требование строго положительного значения.

        Returns:
            Точное конечное значение Decimal.

        Raises:
            ValueError: Запись некорректна или значение недопустимо.
        '''
        normalized = text.strip().replace(',', '.')
        if len(normalized) > 4096 or not NUMBER_PATTERN.fullmatch(normalized):
            raise ValueError('Введите число например 1.234 или 1.2e8')
        try:
            value = Decimal(normalized)
        except InvalidOperation as error:
            raise ValueError('Некорректное число') from error
        if not value.is_finite() or abs(value.as_tuple().exponent) > 1000:
            raise ValueError('Порядок числа должен быть от -1000 до 1000')
        if positive and value <= ZERO:
            raise ValueError('Значение должно быть больше нуля')
        return value

    def _format(self, value: Decimal) -> str:
        '''Форматирует величину только для показа.

        Args:
            value: Значение в единицах СИ.

        Returns:
            Запись с выбранной точностью отображения.
        '''
        return format_quantity(value, self.numberFormatCombo.currentIndex() == 1)

    def _configure_table(self, table: QTableWidget) -> None:
        '''Настраивает таблицу и точный редактор чисел.

        Args:
            table: Таблица исходных данных.
        '''
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumSectionSize(78)
        table.verticalHeader().setDefaultSectionSize(38)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        table.setAlternatingRowColors(True)
        table.setItemDelegate(DecimalDelegate(table))

    def _cell(self, table: QTableWidget, row: int, column: int, value, editable: bool = False) -> None:
        '''Записывает текст или величину в ячейку.

        Args:
            table: Таблица данных.
            row: Индекс строки.
            column: Индекс столбца.
            value: Текст или Decimal.
            editable: Разрешение редактирования.
        '''
        entry = QTableWidgetItem(self._format(value) if isinstance(value, Decimal) else str(value))
        entry.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if editable:
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsEditable)
            entry.setData(Qt.ItemDataRole.UserRole, str(value))
            entry.setToolTip(str(value))
        table.setItem(row, column, entry)

    def _refresh(self) -> None:
        '''Обновляет представления, сохраняя ещё не применённый ввод.'''
        self._updating = True
        count = len(self._model.bars)
        self.dataCard.setVisible(bool(count))
        self.canvasCard.setMinimumHeight(180 if self._narrow and not count else 275)
        self.barsTable.setRowCount(count)
        for row, bar in enumerate(self._model.bars):
            self._cell(self.barsTable, row, 0, f'{row + 1:02d}')
            for col, attr in enumerate(self._bar_attributes, 1):
                self._cell(self.barsTable, row, col, getattr(bar, attr), True)
            self._cell(self.barsTable, row, 5, self._model.distributed_loads[row], True)
        coordinates = self._model.node_positions_m
        self.nodesTable.setRowCount(len(coordinates))
        for row, position in enumerate(coordinates):
            self._cell(self.nodesTable, row, 0, f'{row + 1:02d}')
            self._cell(self.nodesTable, row, 1, position)
            self._cell(self.nodesTable, row, 2, '')
            support = self.nodesTable.item(row, 2)
            support.setFlags(support.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            support.setCheckState(Qt.CheckState.Checked if self._model.supports[row] else Qt.CheckState.Unchecked)
            support.setToolTip('Нулевые кинематические граничные условия')
            self._cell(self.nodesTable, row, 3, self._model.nodal_forces[row], True)
        self._load_rows = [('F', i, value) for i, value in enumerate(self._model.nodal_forces) if value != ZERO]
        self._load_rows += [('q', i, value) for i, value in enumerate(self._model.distributed_loads) if value != ZERO]
        self.loadsTable.setRowCount(len(self._load_rows))
        for row, (kind, index, value) in enumerate(self._load_rows):
            for col, text in enumerate((kind, f'{index + 1:02d}', value, 'Н' if kind == 'F' else 'Н/м')):
                self._cell(self.loadsTable, row, col, text, col == 2)
        self.dataTabs.setTabText(0, f'Стержни {count}')
        self.dataTabs.setTabText(1, f'Узлы {len(coordinates)}')
        self.dataTabs.setTabText(2, f'Нагрузки {len(self._load_rows)}')
        self._refresh_support_nodes()
        if not self._adding_bar and not any(field.isModified() for field in self._bar_fields):
            self._fill_bar_fields()
        self._update_bar_actions()
        self.structure_view.set_model(self._model)
        self.structure_view.set_number_format(self.numberFormatCombo.currentIndex() == 1)
        if self._selected_bar >= 0:
            self.barsTable.selectRow(self._selected_bar)
            self.structure_view.select_bar(self._selected_bar)
        self._refresh_load_elements()
        for (table, row, column), (text, error) in self._invalid_cells.items():
            if row < table.rowCount():
                entry = table.item(row, column)
                entry.setText(text)
                entry.setData(Qt.ItemDataRole.UserRole, text)
                entry.setToolTip(error)
        self._updating = False

    def _fill_bar_fields(self) -> None:
        '''Показывает исходные значения выбранного стержня без округления.'''
        valid = 0 <= self._selected_bar < len(self._model.bars)
        self._adding_bar = not valid
        self.selectedBarLabel.setText(f'Стержень {self._selected_bar + 1:02d}' if valid else 'Новый стержень')
        for field, attribute in zip(self._bar_fields, self._bar_attributes):
            field.setEnabled(True)
            field.setText(str(getattr(self._model.bars[self._selected_bar], attribute)) if valid else '')
            field.setModified(False)
        self._update_bar_actions()

    def _update_bar_actions(self) -> None:
        '''Согласует добавление в таблице и действия редактора стержня.'''
        creating = self._adding_bar
        self.addBarButton.setEnabled(not creating)
        self.removeBarButton.setVisible(not creating)
        self.removeBarButton.setEnabled(self._selected_bar >= 0 and not creating)
        self.applyBarButton.setText('Добавить' if creating else 'Применить')
        self.applyBarButton.setEnabled(True)
        self.cancelBarButton.setText('Очистить' if creating and not self._model.bars else 'Отменить')
        self.cancelBarButton.setEnabled(True)

    def _publish(self, model: StructuralModel) -> None:
        '''Публикует изменённую модель и обновляет интерфейс.

        Args:
            model: Модель после пользовательского изменения.
        '''
        changed = model != self._model
        self._model = model
        self._refresh()
        self.show_status('')
        if changed:
            self.modelChanged.emit(model)

    def _start_bar(self) -> None:
        '''Открывает ввод нового стержня в конце цепочки.'''
        if not self.commit_pending_edits():
            return
        self._adding_bar = True
        self.inspectorTabs.setCurrentIndex(0)
        self.dataTabs.setCurrentIndex(0)
        self.selectedBarLabel.setText('Новый стержень')
        self._update_bar_actions()
        for field in self._bar_fields:
            field.setEnabled(True)
            field.clear()
            field.setModified(False)
        self.lengthInput.setFocus()
        self._reveal_timer.start(0)

    def _scroll_inspector_into_view(self) -> None:
        '''Прокручивает страницу к редактору после завершения компоновки.'''
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea):
                ancestor.ensureWidgetVisible(self.inspectorCard, 16, 16)
                return
            ancestor = ancestor.parentWidget()

    def _cancel_bar(self) -> None:
        '''Отменяет незавершённый ввод свойств стержня.'''
        self._adding_bar = False
        self._fill_bar_fields()
        self.show_status('')

    def _apply_bar(self) -> bool:
        '''Проверяет поля и сохраняет свойства стержня.

        Returns:
            Признак успешного применения введённых значений.
        '''
        if not self._adding_bar and self._selected_bar < 0:
            return True
        values = []
        for field in self._bar_fields:
            try:
                values.append(self._parse(field.text(), positive=True))
            except ValueError as error:
                self.show_status(f'{field.toolTip()} - {error}')
                field.setFocus()
                return False
        bar = Bar(*values)
        if self._adding_bar:
            had_bars = bool(self._model.bars)
            forces = self._model.nodal_forces + (ZERO,) if had_bars else (ZERO, ZERO)
            supports = self._model.supports + (False,) if had_bars else (False, False)
            updated = replace(self._model, bars=self._model.bars + (bar,), nodal_forces=forces,
                              distributed_loads=self._model.distributed_loads + (ZERO,), supports=supports)
            self._selected_bar = len(updated.bars) - 1
        else:
            bars = list(self._model.bars)
            bars[self._selected_bar] = bar
            updated = replace(self._model, bars=tuple(bars))
        self._adding_bar = False
        for field in self._bar_fields:
            field.setModified(False)
        self._publish(updated)
        return True

    def _remove_bar(self) -> None:
        '''Удаляет стержень и правый узел после подтверждения последствий.'''
        if self._selected_bar < 0 or not self.commit_pending_edits():
            return
        index = self._selected_bar
        box = QMessageBox(self)
        box.setWindowTitle('Удалить стержень')
        box.setText(f'Удалить стержень {index + 1:02d}')
        if len(self._model.bars) == 1:
            box.setInformativeText('Конструкция и все нагрузки будут удалены')
        else:
            box.setInformativeText('Правый узел этого стержня будет удалён вместе с его силой и граничными условиями\nНагрузка q на стержне также будет удалена')
        remove = box.addButton('Удалить', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not remove:
            return
        if len(self._model.bars) == 1:
            updated = StructuralModel()
        else:
            updated = replace(self._model,
                bars=self._model.bars[:index] + self._model.bars[index + 1:],
                distributed_loads=self._model.distributed_loads[:index] + self._model.distributed_loads[index + 1:],
                nodal_forces=self._model.nodal_forces[:index + 1] + self._model.nodal_forces[index + 2:],
                supports=self._model.supports[:index + 1] + self._model.supports[index + 2:])
        self._selected_bar = min(index, len(updated.bars) - 1)
        if self._support_node > index:
            self._support_node -= 1
        self._publish(updated)

    def _select_bar(self, index: int) -> None:
        '''Согласует выбор схемы, таблицы и редактора.

        Args:
            index: Индекс выбранного стержня.
        '''
        if self._updating or not 0 <= index < len(self._model.bars):
            return
        if index != self._selected_bar and not self.commit_pending_edits():
            self._updating = True
            self.barsTable.selectRow(self._selected_bar)
            self.structure_view.select_bar(self._selected_bar)
            self._updating = False
            return
        if index == self._selected_bar and any(field.isModified() for field in self._bar_fields):
            return
        self._selected_bar = index
        self.inspectorTabs.setCurrentIndex(0)
        self._updating = True
        self.barsTable.selectRow(index)
        self.structure_view.select_bar(index)
        self._updating = False
        if not self._adding_bar:
            self._fill_bar_fields()

    def _table_bar_selected(self, row: int, column: int, previous_row: int, previous_column: int) -> None:
        '''Передаёт выбор табличной строки в общий редактор.

        Args:
            row: Выбранная строка.
            column: Выбранный столбец.
            previous_row: Предыдущая строка.
            previous_column: Предыдущий столбец.
        '''
        self._select_bar(row)

    def _show_data_editor(self, index: int) -> None:
        '''Открывает редактор выбранного вида исходных данных.

        Args:
            index: Вкладка стержней, узлов или нагрузок.
        '''
        if 0 <= index < 3:
            self.inspectorTabs.setCurrentIndex((0, 2, 1)[index])

    def _bar_cell_changed(self, item: QTableWidgetItem) -> None:
        '''Применяет правку параметра или погонной нагрузки в таблице.

        Args:
            item: Изменённая ячейка.
        '''
        if self._updating or item.column() == 0:
            return
        if not self._allow_cell_edit(self.barsTable, item):
            return
        try:
            value = self._parse(item.text(), positive=item.column() < 5)
        except ValueError as error:
            self._remember_invalid_cell(self.barsTable, item, str(error))
            return
        self._invalid_cells.pop((self.barsTable, item.row(), item.column()), None)
        if item.column() == 5:
            self._set_load('q', item.row(), value)
        else:
            bars = list(self._model.bars)
            bars[item.row()] = replace(bars[item.row()], **{self._bar_attributes[item.column() - 1]: value})
            self._publish(replace(self._model, bars=tuple(bars)))

    def _node_cell_changed(self, item: QTableWidgetItem) -> None:
        '''Применяет узловую силу или закрепление.

        Args:
            item: Изменённая ячейка таблицы узлов.
        '''
        if self._updating:
            return
        if not self._allow_cell_edit(self.nodesTable, item):
            return
        if item.column() == 2:
            self._support_node = item.row()
            supports = list(self._model.supports)
            supports[item.row()] = item.checkState() == Qt.CheckState.Checked
            self._publish(replace(self._model, supports=tuple(supports)))
        elif item.column() == 3:
            try:
                value = self._parse(item.text())
            except ValueError as error:
                self._remember_invalid_cell(self.nodesTable, item, str(error))
                return
            self._invalid_cells.pop((self.nodesTable, item.row(), item.column()), None)
            self._set_load('F', item.row(), value)

    def _remember_invalid_cell(self, table: QTableWidget, item: QTableWidgetItem, error: str) -> None:
        '''Сохраняет ошибочный ввод до исправления пользователем.

        Args:
            table: Таблица с ошибкой ввода.
            item: Редактируемая ячейка.
            error: Текст причины отказа.
        '''
        self._invalid_cells[(table, item.row(), item.column())] = (item.text(), error)
        self._updating = True
        item.setData(Qt.ItemDataRole.UserRole, item.text())
        item.setToolTip(error)
        self._updating = False
        self.show_status(error)

    def _allow_cell_edit(self, table: QTableWidget, item: QTableWidgetItem) -> bool:
        '''Не допускает смещение строк с ещё не исправленной ошибкой.

        Args:
            table: Таблица редактируемой ячейки.
            item: Изменённая ячейка.

        Returns:
            Разрешение применить введённое значение.
        '''
        if self._invalid_cells and (table, item.row(), item.column()) not in self._invalid_cells:
            self._refresh()
            self.show_status('Сначала исправьте ошибку в таблице')
            return False
        return True

    def _refresh_load_elements(self) -> None:
        '''Обновляет список элементов для выбранного типа нагрузки.'''
        current = self.loadElementCombo.currentData()
        self.loadElementCombo.blockSignals(True)
        self.loadElementCombo.clear()
        nodal = self.loadKindCombo.currentIndex() == 0
        values = self._model.nodal_forces if nodal else self._model.distributed_loads
        prefix = 'Узел' if nodal else 'Стержень'
        for index in range(len(values)):
            self.loadElementCombo.addItem(f'{prefix} {index + 1:02d}', index)
        if current is not None and current < len(values):
            self.loadElementCombo.setCurrentIndex(current)
        self.loadElementCombo.blockSignals(False)
        self.loadValueLabel.setText('F, Н' if nodal else 'q, Н/м')
        for widget in (self.loadElementCombo, self.loadValueInput, self.applyLoadButton, self.removeLoadButton):
            widget.setEnabled(bool(values))
        if not self.loadValueInput.isModified():
            self._load_selected_value()

    def _load_selected_value(self) -> None:
        '''Показывает точное значение нагрузки выбранного элемента.'''
        index = self.loadElementCombo.currentData()
        kind = self.loadKindCombo.currentText()
        values = self._model.nodal_forces if kind == 'F' else self._model.distributed_loads
        self._load_target = (kind, index) if index is not None else None
        self.loadValueInput.setText(str(values[index]) if index is not None and index < len(values) else '0')
        self.loadValueInput.setModified(False)

    def _load_kind_changed(self) -> None:
        '''Применяет текущую нагрузку перед сменой её типа.'''
        if self._updating:
            return
        if self.loadValueInput.isModified() and not self._apply_load():
            self.loadKindCombo.blockSignals(True)
            self.loadKindCombo.setCurrentIndex(0 if self._load_target[0] == 'F' else 1)
            self.loadKindCombo.blockSignals(False)
            return
        self._refresh_load_elements()
        self._load_selected_value()

    def _load_element_changed(self) -> None:
        '''Применяет текущую нагрузку перед сменой элемента.'''
        if self._updating:
            return
        if self.loadValueInput.isModified() and not self._apply_load():
            self.loadElementCombo.blockSignals(True)
            self.loadElementCombo.setCurrentIndex(self._load_target[1])
            self.loadElementCombo.blockSignals(False)
            return
        self._load_selected_value()

    def _set_load(self, kind: str, index: int, value: Decimal) -> None:
        '''Заменяет нагрузку выбранного элемента.

        Args:
            kind: Обозначение F или q.
            index: Индекс узла или стержня.
            value: Значение в ньютонах или ньютонах на метр.
        '''
        attribute = 'nodal_forces' if kind == 'F' else 'distributed_loads'
        values = list(getattr(self._model, attribute))
        values[index] = value
        self._publish(replace(self._model, **{attribute: tuple(values)}))

    def _apply_load(self) -> bool:
        '''Сохраняет введённую нагрузку.

        Returns:
            Признак успешного применения значения.
        '''
        if self._load_target is None:
            return True
        if self._invalid_cells:
            self.show_status('Сначала исправьте ошибку в таблице')
            return False
        kind, index = self._load_target
        try:
            value = self._parse(self.loadValueInput.text())
        except ValueError as error:
            self.show_status(str(error))
            self.loadValueInput.setFocus()
            return False
        self.loadValueInput.setModified(False)
        self._set_load(kind, index, value)
        return True

    def _remove_load(self) -> None:
        '''Сбрасывает выбранную нагрузку в ноль.'''
        if self._invalid_cells:
            self.show_status('Сначала исправьте ошибку в таблице')
            return
        if self._load_target is not None:
            kind, index = self._load_target
            self.loadValueInput.setModified(False)
            self._set_load(kind, index, ZERO)

    def _load_cell_changed(self, item: QTableWidgetItem) -> None:
        '''Применяет значение в сводной таблице нагрузок.

        Args:
            item: Изменённая ячейка.
        '''
        if self._updating or item.column() != 2:
            return
        if not self._allow_cell_edit(self.loadsTable, item):
            return
        try:
            value = self._parse(item.text())
        except ValueError as error:
            self._remember_invalid_cell(self.loadsTable, item, str(error))
            return
        self._invalid_cells.pop((self.loadsTable, item.row(), item.column()), None)
        kind, index, previous = self._load_rows[item.row()]
        self._set_load(kind, index, value)

    def _table_load_selected(self, row: int, column: int, previous_row: int, previous_column: int) -> None:
        '''Открывает выбранную нагрузку в инспекторе.

        Args:
            row: Выбранная строка.
            column: Выбранный столбец.
            previous_row: Предыдущая строка.
            previous_column: Предыдущий столбец.
        '''
        if self._updating or not 0 <= row < len(self._load_rows):
            return
        target = self._load_rows[row]
        if self.loadValueInput.isModified() and not self._apply_load():
            return
        kind, index, value = target
        self.inspectorTabs.setCurrentIndex(1)
        self.loadKindCombo.setCurrentIndex(0 if kind == 'F' else 1)
        self.loadElementCombo.setCurrentIndex(index)
        self._load_selected_value()
        self._reveal_timer.start(0)

    def _refresh_support_nodes(self) -> None:
        '''Обновляет выбор узла и его граничные условия.'''
        count = len(self._model.supports)
        self._support_node = min(self._support_node, max(0, count - 1))
        self.supportNodeCombo.blockSignals(True)
        self.supportNodeCombo.clear()
        for index in range(count):
            self.supportNodeCombo.addItem(f'{index + 1:02d}', index)
        self.supportNodeCombo.setCurrentIndex(self._support_node if count else -1)
        self.supportNodeCombo.blockSignals(False)
        self.supportNodeCombo.setEnabled(bool(count))
        self._sync_support_value()

    def _sync_support_value(self) -> None:
        '''Показывает граничные условия выбранного узла без изменения модели.'''
        index = self.supportNodeCombo.currentData()
        valid = index is not None and 0 <= index < len(self._model.supports)
        self._support_group.setExclusive(False)
        self.freeSupportButton.setChecked(valid and not self._model.supports[index])
        self.fixedSupportButton.setChecked(valid and self._model.supports[index])
        self._support_group.setExclusive(True)
        self.freeSupportButton.setEnabled(valid)
        self.fixedSupportButton.setEnabled(valid)

    def _support_node_selected(self) -> None:
        '''Согласует выбранный узел инспектора с таблицей.'''
        if self._updating:
            return
        index = self.supportNodeCombo.currentData()
        if index is None:
            return
        self._support_node = index
        self._sync_support_value()
        if self.nodesTable.currentRow() != index:
            self.nodesTable.setCurrentCell(index, 2)

    def _table_node_selected(self, row: int, column: int, previous_row: int, previous_column: int) -> None:
        '''Показывает граничные условия узла, выбранного в таблице.

        Args:
            row: Выбранный узел.
            column: Выбранный столбец.
            previous_row: Предыдущий узел.
            previous_column: Предыдущий столбец.
        '''
        if not self._updating and 0 <= row < len(self._model.supports):
            self.supportNodeCombo.setCurrentIndex(row)

    def _set_selected_support(self, enabled: bool) -> None:
        '''Меняет граничные условия выбранного узла.

        Args:
            enabled: Признак нулевых кинематических граничных условий.
        '''
        index = self.supportNodeCombo.currentData()
        if self._updating or index is None:
            return
        if self._invalid_cells:
            self._sync_support_value()
            self.show_status('Сначала исправьте ошибку в таблице')
            return
        supports = list(self._model.supports)
        supports[index] = enabled
        self._publish(replace(self._model, supports=tuple(supports)))

    def commit_pending_edits(self) -> bool:
        '''Применяет ввод перед сохранением или сменой проекта.

        Returns:
            Ложь при ошибке ввода, требующей исправления пользователем.
        '''
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and focused not in self._bar_fields and focused is not self.loadValueInput:
            if any(table.isAncestorOf(focused) for table in (self.barsTable, self.nodesTable, self.loadsTable)):
                focused.clearFocus()
        if self._invalid_cells:
            (table, row, column), (text, error) = next(iter(self._invalid_cells.items()))
            self.show_status(error)
            self.dataTabs.setCurrentIndex((self.barsTable, self.nodesTable, self.loadsTable).index(table))
            table.setFocus()
            return False
        pending_bar = any(field.isModified() for field in self._bar_fields)
        if self._adding_bar:
            pending_bar = any(field.text().strip() for field in self._bar_fields)
        if pending_bar and not self._apply_bar():
            return False
        if self.loadValueInput.isModified() and not self._apply_load():
            return False
        return True

    def _request_save(self) -> None:
        '''Передаёт сохранение проекта контроллеру главного окна.'''
        if self.commit_pending_edits():
            self.saveRequested.emit()

    def _validate(self) -> None:
        '''Проверяет данные перед созданием файлов для процессора.'''
        if not self.commit_pending_edits():
            return
        issues = validate_model(self._model)
        if issues:
            self.show_status('\n'.join(issue.message for issue in issues[:4]))
            return
        self.show_status('Данные проверены')
        self.validateRequested.emit()

    def _refresh_numbers(self) -> None:
        '''Меняет только отображение чисел в таблицах и на схеме.'''
        self._refresh()

    def resizeEvent(self, event) -> None:
        '''Перестраивает инспектор при изменении доступной ширины.

        Args:
            event: Событие изменения размеров страницы.
        '''
        super().resizeEvent(event)
        narrow = self.width() < 1050
        if self._narrow == narrow:
            return
        self._narrow = narrow
        self.canvasCard.setMinimumHeight(180 if narrow and not self._model.bars else 275)
        margin = 12 if narrow else 20
        self.pageLayout.setContentsMargins(margin, margin, margin, margin)
        self.workspaceSplitter.setOrientation(Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal)
        self.inspectorCard.setMinimumWidth(0 if narrow else 310)
        self.inspectorCard.setMaximumWidth(16777215 if narrow else 340)
        for index, name in enumerate(('lengthField', 'areaField', 'modulusField', 'stressField')):
            self.propertiesLayout.addWidget(getattr(self, name), 0 if narrow else index, index if narrow else 0)
        for index, name in enumerate(('loadKindField', 'loadElementField', 'loadValueField')):
            self.loadFieldsLayout.addWidget(getattr(self, name), 0 if narrow else index, index if narrow else 0)
        for index, name in enumerate(('supportNodeField', 'supportStateField')):
            self.boundaryFieldsLayout.addWidget(getattr(self, name), 0 if narrow else index, index if narrow else 0)
        self.boundaryFieldsLayout.setColumnStretch(0, 1)
        self.boundaryFieldsLayout.setColumnStretch(1, 2 if narrow else 0)
        for page in (self.barEditorTab, self.loadEditorTab, self.supportsTab):
            page.layout().invalidate()
            page.layout().activate()
            page.updateGeometry()
        self.inspectorTabs.updateGeometry()
        self.inspectorCard.layout().invalidate()
        self.inspectorCard.layout().activate()
        self.inspectorCard.updateGeometry()
        self.workspaceSplitter.setSizes([max(250, self.height() - 270), 210] if narrow else [max(500, self.width() - 350), 310])

    def showEvent(self, event) -> None:
        '''Показывает форму первого стержня при открытии пустого проекта.

        Args:
            event: Событие появления страницы на экране.
        '''
        super().showEvent(event)
        if self._narrow and not self._model.bars:
            self._reveal_timer.start(0)
