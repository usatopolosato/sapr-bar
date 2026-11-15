'''Связывает аналитические результаты с эпюрами, таблицей и сечением.'''

from decimal import Context, Decimal, InvalidOperation, localcontext
from html import escape
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHeaderView, QWidget

from ...domain.postprocessor import PostprocessorResult
from ..feedback import set_input_error, show_feedback
from ..loader import load_form
from ..theme import LIGHT_COLORS, ThemeColors
from ..widgets.linear_system import configure_result_table, number_text
from ..widgets.response_plot import ResponsePlot
from ..widgets.response_table import ResponseTableModel


NUMBER_PATTERN = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')


class PostprocessorPage(QWidget):
    '''Организует согласованный выбор сечения во всех представлениях.

    Args:
        parent: Родитель страницы в основном окне.
    '''

    reportRequested = pyqtSignal()
    processorRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        load_form('postprocessor.ui', self)
        self.result: PostprocessorResult | None = None
        self._colors = LIGHT_COLORS
        self._table_model = None
        self._selected_x = Decimal(0)
        self._narrow = None
        self.epures_view = ResponsePlot(self)
        self.graph_view = ResponsePlot(self, local=True)
        self.epuresLayout.addWidget(self.epures_view)
        self.graphLayout.addWidget(self.graph_view)
        for title in ('Эпюры', 'График', 'Таблица'):
            self.viewsBar.addTab(title)
        self.viewsBar.setExpanding(False)
        self.viewsBar.setDrawBase(False)
        self.workspaceSplitter.setChildrenCollapsible(False)
        self.workspaceSplitter.setStretchFactor(0, 1)
        self.workspaceSplitter.setStretchFactor(1, 0)
        self.workspaceSplitter.setSizes([900, 280])
        self.pageLayout.setStretch(2, 1)
        self.resultsLayout.setStretch(1, 1)
        self.plotsCardLayout.setStretch(1, 1)
        configure_result_table(self.resultsTable)
        self.resultsTable.verticalHeader().hide()
        self.resultsTable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.resultsTable.horizontalHeader().setMinimumSectionSize(75)
        self.resultsTable.horizontalHeader().setStretchLastSection(True)
        for page in (self.emptyPage, self.resultsPage, self.epuresPage, self.graphPage, self.tablePage):
            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.reportButton.clicked.connect(self.reportRequested)
        self.processorButton.clicked.connect(self.processorRequested)
        self.viewsBar.currentChanged.connect(self._show_view)
        self.numberFormatCombo.currentIndexChanged.connect(self._format_changed)
        self.componentCombo.currentIndexChanged.connect(self._component_changed)
        self.limitsCheck.toggled.connect(self.epures_view.set_limits_visible)
        self.limitsCheck.toggled.connect(self.graph_view.set_limits_visible)
        self.fitButton.clicked.connect(lambda: self._active_plot().fit_view())
        self.zoomInButton.clicked.connect(lambda: self._active_plot().zoom_by(Decimal('1.5')))
        self.zoomOutButton.clicked.connect(lambda: self._active_plot().zoom_by(Decimal('0.6666666666666666666667')))
        self.tableScopeCombo.currentIndexChanged.connect(self._refresh_table)
        self.tableModeCombo.currentIndexChanged.connect(self._refresh_table)
        self.subdivisionsSpin.valueChanged.connect(self._refresh_table)
        self.subdivisionsSpin.setKeyboardTracking(False)
        self.subdivisionsSpin.setToolTip('Характерные точки добавляются независимо от числа разбиений')
        self.numberFormatCombo.setToolTip('Формат чисел в таблице и формулах\nНа эпюрах подписи краткие, точное значение доступно в сечении')
        self.barCombo.currentIndexChanged.connect(self._bar_changed)
        self.sectionButton.clicked.connect(self._apply_position)
        self.positionInput.returnPressed.connect(self._apply_position)
        self.formulasButton.toggled.connect(self.formulasView.setVisible)
        self.formulasButton.toggled.connect(lambda checked: self.numberFormatCombo.setEnabled(checked or self.viewsBar.currentIndex() != 0))
        self.epures_view.sectionSelected.connect(self._select_section)
        self.graph_view.sectionSelected.connect(self._select_section)
        self.formulasView.hide()
        self.sectionErrorLabel.hide()
        self._show_view(0)
        self.set_unavailable('Выполните расчёт в процессоре')

    def show_status(self, text: str, *, error: bool = False) -> None:
        '''Показывает сообщение операции без изменения расчётных данных.

        Args:
            text: Содержание сообщения.
            error: Признак ошибки вычисления или сохранения.
        '''
        show_feedback(self.statusLabel, text, error=error)

    def set_unavailable(self, message: str, *, error: bool = False) -> None:
        '''Убирает недостоверные результаты и запрещает формирование отчёта.

        Args:
            message: Причина отсутствия актуального расчёта.
            error: Признак повреждённых данных или ошибки вычисления.
        '''
        self.result = None
        self.resultsTable.setModel(None)
        if self._table_model is not None:
            self._table_model.deleteLater()
            self._table_model = None
        self.epures_view.clear()
        self.graph_view.clear()
        self.reportButton.setEnabled(False)
        self.stateStack.setCurrentWidget(self.emptyPage)
        self.emptyLabel.setText('Выполните расчёт в процессоре' if error else message)
        self.show_status(message if error else '', error=error)

    def set_result(self, result: PostprocessorResult) -> None:
        '''Публикует единый результат для эпюр, графика, таблицы и сечения.'''
        self.result = result
        self.epures_view.set_result(result)
        self.graph_view.set_result(result)
        self.barCombo.blockSignals(True)
        self.barCombo.clear()
        for bar in result.bars:
            self.barCombo.addItem(f'Стержень {bar.index + 1}', bar.index)
        self.barCombo.blockSignals(False)
        self.reportButton.setEnabled(True)
        self.stateStack.setCurrentWidget(self.resultsPage)
        exceeded = sum(bar.stress_status == 'Превышение' for bar in result.bars)
        self.show_status(f'Стержней с превышением допуска {exceeded}' if exceeded else 'Расчёт актуален', error=bool(exceeded))
        self._select_section(0, Decimal(0))
        self._refresh_table()
        self._update_layout()

    def set_theme(self, colors: ThemeColors) -> None:
        '''Применяет общую тему к графике и ячейкам превышения допуска.'''
        self._colors = colors
        self.epures_view.set_theme(colors)
        self.graph_view.set_theme(colors)
        if self._table_model is not None:
            self._table_model.set_theme(colors)

    def _active_plot(self) -> ResponsePlot:
        '''Возвращает график, к которому относятся кнопки масштаба.'''
        return self.graph_view if self.viewsBar.currentIndex() == 1 else self.epures_view

    def _show_view(self, index: int) -> None:
        '''Переключает представление с сохранением выбранного сечения.'''
        self.viewsStack.setCurrentIndex(index)
        self.plotTools.setVisible(index != 2)
        self.componentCombo.setVisible(index == 1)
        self.limitsCheck.setEnabled(index == 0 or self.componentCombo.currentIndex() == 1)
        self.numberFormatCombo.setEnabled(index != 0 or self.formulasButton.isChecked())

    def _component_changed(self, index: int) -> None:
        '''Выбирает компоненту локального графика.'''
        self.graph_view.set_component(('N', 'sigma', 'u')[index])
        self.limitsCheck.setEnabled(self.viewsBar.currentIndex() == 0 or index == 1)

    def _format_changed(self) -> None:
        '''Переформатирует представление без повторного расчёта модели.'''
        if self.result is None:
            return
        self._refresh_table()
        self._show_section(self.barCombo.currentIndex(), self._selected_x)

    def _refresh_table(self) -> None:
        '''Создаёт ленивую модель для текущей выборки и числа разбиений.'''
        if self.result is None:
            return
        selected = self.barCombo.currentIndex() if self.tableScopeCombo.currentIndex() else None
        model = ResponseTableModel(self.result, self.subdivisionsSpin.value(),
                                   bool(self.tableModeCombo.currentIndex()), selected,
                                   self.numberFormatCombo.currentIndex() == 0, self)
        model.set_theme(self._colors)
        previous = self._table_model
        self._table_model = model
        self.resultsTable.setModel(model)
        self.resultsTable.selectionModel().currentRowChanged.connect(self._table_section_selected)
        for index, width in enumerate((85, 135, 145, 145, 145)):
            self.resultsTable.setColumnWidth(index, width)
            self.resultsTable.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        self.tableInfoLabel.setText(f'Сечений {model.rowCount()}   Концы и экстремумы включены')
        self.subdivisionsSpin.setEnabled(self.tableModeCombo.currentIndex() == 0)
        if previous is not None:
            previous.deleteLater()

    def _table_section_selected(self, current, previous) -> None:
        '''Передаёт выбранную строку в общую панель сечения.'''
        if self._table_model is not None and current.isValid():
            section = self._table_model.section(current.row())
            self._select_section(section.bar_index, section.x_m)

    def _bar_changed(self, index: int) -> None:
        '''Переносит сечение в начало вновь выбранного стержня.'''
        if self.result is not None and index >= 0:
            self._select_section(index, Decimal(0))
            if self.tableScopeCombo.currentIndex():
                self._refresh_table()

    def _select_section(self, index: int, x: Decimal) -> None:
        '''Согласует выбор на эпюре, в таблице и в поле координаты.'''
        if self.result is None:
            return
        changed = self.barCombo.currentIndex() != index
        self.barCombo.blockSignals(True)
        self.barCombo.setCurrentIndex(index)
        self.barCombo.blockSignals(False)
        self.positionInput.setText(str(x))
        self._show_section(index, x)
        if changed and self.tableScopeCombo.currentIndex():
            self._refresh_table()

    def _apply_position(self) -> None:
        '''Проверяет координату без промежуточного преобразования в float.'''
        if self.result is None:
            return
        text = self.positionInput.text().strip().replace(',', '.')
        try:
            if len(text) > 4096 or not NUMBER_PATTERN.fullmatch(text):
                raise ValueError('Введите число например 1.234 или 1.2e8')
            x = Decimal(text)
            if not x.is_finite() or abs(x.as_tuple().exponent) > 1000:
                raise ValueError('Некорректная координата')
            bar = self.result.bars[self.barCombo.currentIndex()]
            if not Decimal(0) <= x <= bar.geometry.length_m:
                raise ValueError(f'x должен быть от 0 до {number_text(bar.geometry.length_m, True)} м')
            self._show_section(bar.index, x)
        except (ValueError, InvalidOperation) as error:
            set_input_error(self.positionInput, True)
            show_feedback(self.sectionErrorLabel, str(error), error=True)
            self.positionInput.setFocus()

    def _show_section(self, index: int, x: Decimal) -> None:
        '''Показывает все компоненты и условие прочности выбранного стержня.'''
        bar = self.result.bars[index]
        section = bar.at(x)
        self._selected_x = x
        set_input_error(self.positionInput, False)
        show_feedback(self.sectionErrorLabel, '')
        self.lengthLabel.setText(f'L = {number_text(bar.geometry.length_m, True)} м')
        self.lengthLabel.setToolTip(str(bar.geometry.length_m))
        for label, value in ((self.forceValue, section.force_n), (self.stressValue, section.stress_pa),
                             (self.displacementValue, section.displacement_m)):
            label.setText(number_text(value, True))
            label.setToolTip(str(value))
        exceeded = bar.stress_status == 'Превышение'
        show_feedback(self.strengthLabel, 'Превышение в стержне' if exceeded else bar.stress_status, error=exceeded)
        self.strengthDetailsLabel.setText(f'Максимум модуля σ = {number_text(bar.max_abs_stress_pa, True)} Па\n'
                                          f'Допуск = {number_text(bar.geometry.allowable_stress_pa, True)} Па')
        self.epures_view.set_section(index, x)
        self.graph_view.set_section(index, x)
        self._show_formulas(bar, section)

    def _show_formulas(self, bar, section) -> None:
        '''Оформляет формулы и числовую подстановку выбранного сечения.'''
        compact = self.numberFormatCombo.currentIndex() == 0
        text = lambda value: escape(number_text(value, compact))
        with localcontext(Context(prec=bar.precision)):
            stiffness = bar.geometry.modulus_pa * bar.geometry.area_m2 / bar.geometry.length_m
        x, length = text(section.x_m), text(bar.geometry.length_m)
        left, right = text(bar.u_left_m), text(bar.u_right_m)
        q, area = text(bar.q_n_per_m), text(bar.geometry.area_m2)
        modulus, k = text(bar.geometry.modulus_pa), text(stiffness)
        first, second = bar.index + 1, bar.index + 2
        parts = (
            f'<b>N(x)</b> = EA / L * (Δ<sub>{second}</sub> - Δ<sub>{first}</sub>) + q * (L / 2 - x)',
            f'N({x}) = {k} * ({right} - {left}) + ({q}) * ({length} / 2 - {x})',
            f'N = {text(section.force_n)} Н',
            '<b>σ(x)</b> = N(x) / A',
            f'σ({x}) = ({text(section.force_n)}) / {area} = {text(section.stress_pa)} Па',
            f'<b>u(x)</b> = Δ<sub>{first}</sub> + x / L * (Δ<sub>{second}</sub> - Δ<sub>{first}</sub>) + q * x * (L - x) / (2EA)',
            f'u({x}) = {left} + {x} / {length} * ({right} - {left}) + '
            f'({q}) * {x} * ({length} - {x}) / (2 * {modulus} * {area})',
            f'u = {text(section.displacement_m)} м',
        )
        self.formulasView.setHtml('<div style="line-height:135%;"><p>' + '</p><p>'.join(parts) + '</p></div>')

    def _update_layout(self) -> None:
        '''Переносит панель сечения вниз при недостатке ширины.'''
        narrow = self.width() < 940
        if narrow == self._narrow:
            return
        self._narrow = narrow
        self.workspaceSplitter.setOrientation(Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal)
        self.sectionCard.setMaximumWidth(16777215 if narrow else 320)
        self.workspaceSplitter.setSizes([600, 450] if narrow else [900, 280])

    def resizeEvent(self, event) -> None:
        '''Согласует компоновку с фактической шириной страницы.'''
        super().resizeEvent(event)
        if hasattr(self, '_narrow'):
            self._update_layout()
