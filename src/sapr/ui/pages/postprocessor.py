'''Связывает аналитические результаты с эпюрами, таблицей и сечением.'''

from decimal import Context, Decimal, InvalidOperation, localcontext
from html import escape

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHeaderView, QSizePolicy, QWidget

from ...domain.postprocessor import PostprocessorResult
from ...formatting import format_quantity, format_result
from ..feedback import set_input_error, show_feedback
from ..loader import load_form
from ..number_input import parse_number
from ..theme import LIGHT_COLORS, ThemeColors
from ..widgets.linear_system import configure_result_table, number_text
from ..widgets.response_plot import ResponsePlot
from ..widgets.response_table import ResponseTableModel


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
        self._setup_layout()
        self._setup_plot_controls()
        self._setup_table_controls()
        self._setup_section_controls()
        self.reportButton.clicked.connect(self.reportRequested)
        self.processorButton.clicked.connect(self.processorRequested)
        self.viewsBar.currentChanged.connect(self._show_view)
        self._show_view(0)
        self.set_unavailable('Выполните расчёт в процессоре')

    def _setup_layout(self) -> None:
        '''Размещает графики в форме и задаёт размеры панелей.'''
        self.epures_view = ResponsePlot(self)
        self.graph_view = ResponsePlot(self, local=True)
        self.epuresLayout.addWidget(self.epures_view)
        self.graphLayout.addWidget(self.graph_view)
        self.hoverValuesLabel.setMinimumHeight(self.hoverValuesLabel.fontMetrics().lineSpacing() * 2 + 4)
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
        self.tableLayout.setStretch(1, 1)
        self.tableToolsLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for page in (self.emptyPage, self.resultsPage, self.epuresPage, self.graphPage, self.tablePage):
            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def _setup_plot_controls(self) -> None:
        '''Связывает графики с переключателями эпюр и кнопками масштаба.'''
        self.componentCombo.currentIndexChanged.connect(self._component_changed)
        self.fitButton.clicked.connect(lambda: self._active_plot().fit_view())
        self.zoomInButton.clicked.connect(lambda: self._active_plot().zoom_by(Decimal('1.2')))
        self.zoomOutButton.clicked.connect(lambda: self._active_plot().zoom_by(Decimal(1) / Decimal('1.2')))
        self.fitLimitsButton.clicked.connect(self._fit_limits)
        for view in (self.epures_view, self.graph_view):
            self.limitsCheck.toggled.connect(view.set_limits_visible)
            view.set_limits_visible(self.limitsCheck.isChecked())
            view.viewChanged.connect(self._update_plot_controls)
            view.sectionHovered.connect(self._show_hover)
            view.hoverLeft.connect(self._clear_hover)
            view.sectionSelected.connect(self._select_section)
        for check in (self.forceCheck, self.stressCheck, self.displacementCheck):
            check.toggled.connect(self._components_changed)

    def _setup_table_controls(self) -> None:
        '''Настраивает столбцы, фильтры и сетку сечений.'''
        configure_result_table(self.resultsTable)
        self.resultsTable.verticalHeader().hide()
        header = self.resultsTable.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(100)
        header.setStretchLastSection(True)
        self.tableScopeCombo.currentIndexChanged.connect(self._refresh_table)
        self.tableComponentCombo.addItem('Все величины', None)
        self.tableComponentCombo.addItem('Продольная сила N', 'N')
        self.tableComponentCombo.addItem('Напряжение σ', 'sigma')
        self.tableComponentCombo.addItem('Перемещение u', 'u')
        self.tableModeCombo.currentIndexChanged.connect(self._table_mode_changed)
        self.tableComponentCombo.currentIndexChanged.connect(self._refresh_table)
        self.subdivisionsSpin.valueChanged.connect(self._refresh_table)
        self.samplingCombo.currentIndexChanged.connect(self._sampling_changed)
        self.stepInput.editingFinished.connect(self._refresh_table)
        self.subdivisionsSpin.setKeyboardTracking(False)
        self.subdivisionsSpin.setToolTip('Характерные точки добавляются независимо от числа разбиений')

    def _setup_section_controls(self) -> None:
        '''Настраивает выбор сечения и формат показанных результатов.'''
        self.numberFormatCombo.currentIndexChanged.connect(self._format_changed)
        self.precisionSpin.setKeyboardTracking(True)
        self.precisionSpin.valueChanged.connect(self._format_changed)
        self.precisionSpin.setToolTip('Число знаков после точки при округлении.')
        self.numberFormatCombo.setToolTip('Округлять - по полю Знаков. Точно - все значащие цифры.\nНа эпюрах подписи краткие.')
        for field in (self.forceValue, self.stressValue, self.displacementValue):
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.barCombo.currentIndexChanged.connect(self._bar_changed)
        self.sectionButton.clicked.connect(self._apply_position)
        self.positionInput.returnPressed.connect(self._apply_position)
        self.formulasButton.toggled.connect(self.formulasView.setVisible)
        self.formulasView.hide()
        self.sectionErrorLabel.hide()

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
        self._set_table_model(None)
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
        if exceeded:
            self.show_status(f'Прочность не обеспечена. Стержней с превышением {exceeded}', error=True)
        else:
            self.show_status('Прочность обеспечена')
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
        self.plotHintLabel.setVisible(index != 2)
        self.hoverValuesLabel.setVisible(index != 2)
        self.componentCombo.setVisible(index == 1)
        for check in (self.forceCheck, self.stressCheck, self.displacementCheck):
            check.setVisible(index == 0)
        self.limitsCheck.setEnabled(index == 0 or self.componentCombo.currentIndex() == 1)
        self._update_plot_controls()
        self._clear_hover()

    def _update_plot_controls(self) -> None:
        '''Согласует доступность приближения допуска с выбранными эпюрами.'''
        view = self._active_plot()
        shows_stress = view.component == 'sigma' if view.local else 'sigma' in view.components
        self.fitLimitsButton.setEnabled(self.result is not None and shows_stress)

    def _fit_limits(self) -> None:
        '''Показывает область допуска, оставляя видимыми признаки превышения.'''
        self.limitsCheck.setChecked(True)
        self._active_plot().fit_limits()

    def _show_hover(self, index: int, x: Decimal) -> None:
        '''Показывает точное сечение под мышью без изменения закреплённого выбора.'''
        if self.result is None:
            return
        section = self.result.at(index, x)
        limit = self.result.bars[index].geometry.allowable_stress_pa
        text = (f'Стержень {index + 1}, x = {number_text(x, True)} м. '
                f'N = {number_text(section.force_n, True)} Н; σ = {number_text(section.stress_pa, True)} Па; '
                f'u = {number_text(section.displacement_m, True)} м. Допуск ±{number_text(limit, True)} Па')
        self.hoverValuesLabel.setText(text)
        self.hoverValuesLabel.setToolTip(text)

    def _clear_hover(self) -> None:
        '''Возвращает подсказку, когда временное сечение не выбрано.'''
        self.hoverValuesLabel.setText('Наведите мышь на график для просмотра значений')
        self.hoverValuesLabel.setToolTip('')

    def _components_changed(self) -> None:
        '''Разрешает любой набор эпюр, включая пустой.'''
        checks = (self.forceCheck, self.stressCheck, self.displacementCheck)
        self.epures_view.set_components(tuple(key for key, check in zip(('N', 'sigma', 'u'), checks) if check.isChecked()))

    def _sampling_changed(self, index: int) -> None:
        '''Переключает равномерные разбиения и шаг в метрах.'''
        self.samplingStack.setCurrentIndex(index)
        self._refresh_table()

    def _table_mode_changed(self) -> None:
        '''Открывает экстремумы напряжения, если ранее были выбраны все величины.'''
        if self.tableModeCombo.currentIndex() and self.tableComponentCombo.currentData() is None:
            self.tableComponentCombo.setCurrentIndex(2)
        else:
            self._refresh_table()

    def sampling_step(self) -> Decimal | None:
        '''Читает шаг таблицы и отчёта, если выбрана сетка по расстоянию.'''
        if self.tableModeCombo.currentIndex() or not self.samplingCombo.currentIndex():
            return None
        return parse_number(self.stepInput.text(), positive=True)

    def _component_changed(self, index: int) -> None:
        '''Выбирает компоненту локального графика.'''
        self.graph_view.set_component(('N', 'sigma', 'u')[index])
        self.limitsCheck.setEnabled(self.viewsBar.currentIndex() == 0 or index == 1)

    def _format_changed(self) -> None:
        '''Переформатирует представление без повторного расчёта модели.'''
        rounded = self.numberFormatCombo.currentIndex() == 0
        self.precisionLabel.setVisible(rounded)
        self.precisionSpin.setVisible(rounded)
        if self.result is None:
            return
        self._refresh_table()
        self._show_section(self.barCombo.currentIndex(), self._selected_x)

    def _result_text(self, value: Decimal) -> str:
        '''Форматирует результат по общему режиму, не меняя расчётное значение.'''
        if self.numberFormatCombo.currentIndex() == 0:
            return format_result(value, self.precisionSpin.value())
        return format_quantity(value)

    def _refresh_table(self) -> bool:
        '''Создаёт ленивую модель для текущей выборки и числа разбиений.'''
        if self.result is None:
            return False
        extrema = bool(self.tableModeCombo.currentIndex())
        self.samplingCombo.setVisible(not extrema)
        self.samplingStack.setVisible(not extrema)
        selected = self.barCombo.currentIndex() if self.tableScopeCombo.currentIndex() else None
        try:
            model = ResponseTableModel(
                self.result, subdivisions=self.subdivisionsSpin.value(),
                extrema_only=extrema, selected_bar=selected,
                compact=self.numberFormatCombo.currentIndex() == 0, places=self.precisionSpin.value(),
                step=self.sampling_step(), component=self.tableComponentCombo.currentData(), parent=self,
            )
        except ValueError as error:
            self._set_table_model(None)
            set_input_error(self.stepInput, True)
            show_feedback(self.tableInfoLabel, str(error), error=True)
            return False
        set_input_error(self.stepInput, False)
        model.set_theme(self._colors)
        self._set_table_model(model)
        self.resultsTable.selectionModel().currentRowChanged.connect(self._table_section_selected)
        if extrema:
            message = ('Минимум и максимум на каждом стержне. x отсчитывается от начала стержня. '
                       'При совпадении значений показаны обе строки; при нескольких координатах указана одна.')
        else:
            message = f'Сечений {model.rowCount()}. x отсчитывается от начала стержня.'
        show_feedback(self.tableInfoLabel, message)
        return True

    def _set_table_model(self, model: ResponseTableModel | None) -> None:
        '''Подключает текущую таблицу и освобождает предыдущую модель Qt.'''
        self.resultsTable.setModel(model)
        if self._table_model is not None:
            self._table_model.deleteLater()
        self._table_model = model

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
        try:
            x = parse_number(self.positionInput.text())
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
            label.setText(self._result_text(value))
            label.setCursorPosition(0)
            label.setToolTip(str(value))
        exceeded = bar.stress_status == 'Превышение'
        show_feedback(self.strengthLabel, 'Превышение в стержне' if exceeded else bar.stress_status, error=exceeded)
        peak = bar.max_abs_stress_pa
        limit = bar.geometry.allowable_stress_pa
        if self.numberFormatCombo.currentIndex() == 0:
            peak_text = self._result_text(peak)
            limit_text = self._result_text(limit)
        else:
            peak_text = format_quantity(peak, compact=True)
            limit_text = format_quantity(limit, compact=True)
        self.strengthDetailsLabel.setText(f'Максимум модуля σ = {peak_text} Па\nДопуск = {limit_text} Па')
        self.strengthDetailsLabel.setToolTip(f'Максимум модуля σ = {bar.max_abs_stress_pa} Па\n'
                                             f'Допуск = {bar.geometry.allowable_stress_pa} Па')
        self.epures_view.set_section(index, x)
        self.graph_view.set_section(index, x)
        self._show_formulas(bar, section)

    def _show_formulas(self, bar, section) -> None:
        '''Оформляет формулы и числовую подстановку выбранного сечения.'''
        def text(value: Decimal) -> str:
            return escape(self._result_text(value))

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
        self.sectionCard.setMaximumWidth(16777215 if narrow else 320)
        self.workspaceSplitter.setOrientation(Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal)
        self.workspaceSplitter.refresh()
        self.workspaceSplitter.setSizes([600, 450] if narrow else [900, 280])
        # QScrollArea иначе сохраняет минимальную ширину горизонтального splitter.
        for widget in (self.plotsCard, self.sectionCard, self.workspaceSplitter, self.resultsPage, self.stateStack, self):
            if widget.layout() is not None:
                widget.layout().invalidate()
                widget.layout().activate()
            widget.updateGeometry()

    def resizeEvent(self, event) -> None:
        '''Согласует компоновку с фактической шириной страницы.'''
        super().resizeEvent(event)
        if hasattr(self, '_narrow'):
            self._update_layout()
