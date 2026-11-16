'''Представляет этапы решения и вектор перемещений глобальных узлов.'''

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHeaderView, QWidget

from ...domain.processor import ProcessorResult
from ..feedback import show_feedback
from ..loader import load_form
from ..math_notation import formula_html
from ..widgets.back_substitution import BackSubstitutionModel
from ..widgets.forward_elimination import ForwardEliminationDetails
from ..widgets.linear_system import LinearSystemView, NodeTableModel, configure_result_table, number_text


class ProcessorPage(QWidget):
    '''Переключает этапы решения независимо от расчётного ядра.'''

    calculateRequested = pyqtSignal()
    preprocessorRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        load_form('processor.ui', self)
        self.result: ProcessorResult | None = None
        self._node_models = []
        self._forward_details = None
        self.system_view = LinearSystemView(self)
        self.matrixLayout.insertWidget(1, self.system_view, 1)
        self.matrixLayout.setStretch(1, 1)
        self.matrixLayout.setStretch(2, 1)
        self.matrixLayout.setStretch(3, 1)
        self.matrixLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.backSubstitutionPanel.hide()
        self.displacementsLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.displacementsLayout.addStretch(1)
        self.displacementsView.setMaximumWidth(420)
        self.pageLayout.setStretch(2, 1)
        self.solutionLayout.setStretch(3, 1)
        self.cardLayout.setStretch(3, 1)
        for name in ('Прямой ход', 'Обратный ход'):
            self.sweepBar.addTab(name)
        self.sweepBar.setExpanding(False)
        self.sweepBar.setDrawBase(False)
        self.sweepBar.currentChanged.connect(self._show_sweep)
        self.forwardRowSpin.setKeyboardTracking(False)
        self.forwardRowSpin.valueChanged.connect(self._refresh_forward)
        self.forwardStateCombo.currentIndexChanged.connect(self._refresh_forward)
        self.previousForwardButton.clicked.connect(lambda: self.forwardRowSpin.setValue(self.forwardRowSpin.value() - 1))
        self.nextForwardButton.clicked.connect(lambda: self.forwardRowSpin.setValue(self.forwardRowSpin.value() + 1))
        self.forwardRowSpin.setToolTip('Выберите изменяемую строку. Первая строка служит опорной')
        self.forwardDetails.setToolTip('Числа взяты из расчёта Decimal. Формат Точно показывает полную рабочую точность')
        self.forwardControls.hide()
        self.forwardDetails.hide()
        self.sweepBar.hide()
        for name in ('Сборка', 'Закрепления', 'Прогонка', 'Уравнения', 'Перемещения'):
            self.stepsBar.addTab(name)
            self.stepCombo.addItem(name)
        self.stepsBar.setDrawBase(False)
        self.stepsBar.setExpanding(False)
        self.stepsBar.currentChanged.connect(self._show_step)
        self.stepCombo.currentIndexChanged.connect(self.stepsBar.setCurrentIndex)
        self.numberFormatCombo.currentIndexChanged.connect(self._refresh_numbers)
        self.numberFormatCombo.setItemText(0, 'Формат Кратко')
        self.numberFormatCombo.setItemText(1, 'Формат Точно')
        self.numberFormatCombo.setToolTip('Кратко - округление только для показа\nТочно - полная рабочая точность Decimal')
        self.calculateButton.clicked.connect(self.calculateRequested)
        self.preprocessorButton.clicked.connect(self.preprocessorRequested)
        for view in (self.equationsView, self.displacementsView):
            configure_result_table(view)
            view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        configure_result_table(self.backSubstitutionView)
        self.backSubstitutionView.setToolTip('Коэффициенты после прямого хода. Выберите узел для просмотра полной подстановки')
        self.backSubstitutionDetails.setToolTip('a с нижними индексами - коэффициент матрицы A после прямого хода\nb с нижним индексом - соответствующий элемент правой части')
        for page in (self.emptyPage, self.solutionPage, self.matrixPage, self.equationsPage, self.displacementsPage):
            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.set_availability(False, 'Выберите проект')

    def set_availability(self, ready: bool, message: str, *, reset: bool = False, error: bool = False) -> None:
        '''Обновляет допуск к расчёту, скрывая недостоверные результаты.

        Args:
            ready: Признак актуальных проверенных файлов.
            message: Причина блокировки или статус готовности.
            reset: Необходимость сбросить прежний результат.
            error: Признак ошибки, отличающий её от ожидания проверки.
        '''
        self.calculateButton.setEnabled(ready)
        self.calculateButton.setText('Рассчитать')
        show_feedback(self.statusLabel, message, error=error)
        self.statusLabel.setToolTip('')
        self.preprocessorButton.setVisible(not ready)
        if reset or not ready:
            self.result = None
        if self.result is None:
            self._forward_details = None
            self.stateStack.setCurrentWidget(self.emptyPage)
            prompt = 'Нажмите Рассчитать' if ready else message
            self.emptyLabel.setText('Проверьте проект в препроцессоре' if error else prompt)

    def set_busy(self) -> None:
        '''Показывает выполнение расчёта без блокировки навигации.'''
        self.calculateButton.setEnabled(False)
        self.calculateButton.setText('Расчёт')
        show_feedback(self.statusLabel, 'Вычисление перемещений')

    def set_result(self, result: ProcessorResult) -> None:
        '''Публикует согласованные этапы одного завершённого расчёта.'''
        self.result = result
        self.forwardRowSpin.blockSignals(True)
        self.forwardRowSpin.setRange(2, len(result.displacements))
        self.forwardRowSpin.setSuffix(f' из {len(result.displacements)}')
        self.forwardRowSpin.setValue(2)
        self.forwardRowSpin.blockSignals(False)
        self.calculateButton.setEnabled(True)
        self.calculateButton.setText('Рассчитать')
        show_feedback(self.statusLabel, f'Расчёт выполнен   Стержней {len(result.model.bars)}   Узлов {len(result.displacements)}')
        self.statusLabel.setToolTip(f'Decimal {result.precision} значащих цифр\nОтносительная невязка {result.relative_residual}')
        self.stateStack.setCurrentWidget(self.solutionPage)
        self._refresh_numbers()
        self.stepsBar.setCurrentIndex(0)
        self._show_step(0)

    def _refresh_numbers(self, index: int = 0) -> None:
        '''Обновляет только отображение чисел на всех шагах.'''
        if self.result is None:
            return
        selected_back_row = max(0, self.backSubstitutionView.currentIndex().row())
        for model in self._node_models:
            model.deleteLater()
        compact = self.numberFormatCombo.currentIndex() == 0
        self._forward_details = ForwardEliminationDetails(self.result, compact)
        equations = NodeTableModel(self.result, True, compact, self)
        displacements = NodeTableModel(self.result, False, compact, self)
        back_substitution = BackSubstitutionModel(self.result, compact, self)
        self._node_models = [equations, displacements, back_substitution]
        self.equationsView.setModel(equations)
        self.displacementsView.setModel(displacements)
        self.backSubstitutionView.setModel(back_substitution)
        self.backSubstitutionView.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backSubstitutionView.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.backSubstitutionView.setColumnWidth(1, 150)
        self.backSubstitutionView.setMaximumHeight(40 * len(self.result.displacements) + 46)
        self.backSubstitutionView.selectionModel().currentRowChanged.connect(self._back_node_selected)
        self.backSubstitutionView.selectRow(min(selected_back_row, back_substitution.rowCount() - 1))
        vector_height = 40 * len(self.result.displacements) + 46
        self.displacementsView.setMaximumHeight(vector_height)
        self.deltaLabel.setMaximumHeight(vector_height)
        self.equationsView.selectionModel().currentRowChanged.connect(self._node_selected)
        self.equationsView.selectRow(0)
        self._show_step(self.stepsBar.currentIndex())

    def _show_step(self, index: int) -> None:
        '''Показывает исходную систему, закрепления, прогонку или результат.'''
        self.stepCombo.setCurrentIndex(index)
        if self.result is None:
            return
        titles = ('Матрица A до закреплений', 'Матрица A после закреплений', 'Прямой и обратный ход', 'Уравнения узлов', 'Вектор перемещений')
        nodes = [str(i + 1) for i, flag in enumerate(self.result.model.supports) if flag]
        fixed = ' '.join(nodes[:12])
        if len(nodes) > 12:
            fixed += f'   Всего {len(nodes)}'
        descriptions = (
            'k = E * A / L   Вклад q в каждый конец стержня равен q * L / 2',
            'Закреплённые узлы ' + fixed,
            'Исключение коэффициентов по строкам и подстановка перемещений',
            'Уравнения после закреплений   k = E * A / L',
            'Перемещения глобальных узлов в метрах',
        )
        self.stepTitleLabel.setText(titles[index])
        self.stepDescriptionLabel.setText(descriptions[index])
        self.stepDescriptionLabel.setToolTip(descriptions[index])
        self.stepDescriptionLabel.setVisible(index != 2)
        self.sweepBar.setVisible(index == 2)
        self.backSubstitutionPanel.setVisible(index == 2 and self.sweepBar.currentIndex() == 1)
        self.forwardControls.setVisible(index == 2 and self.sweepBar.currentIndex() == 0)
        self.forwardDetails.setVisible(index == 2 and self.sweepBar.currentIndex() == 0)
        if index < 3:
            self.stepsStack.setCurrentWidget(self.matrixPage)
            if index == 2:
                self._show_sweep(self.sweepBar.currentIndex())
                return
            system = (self.result.original, self.result.constrained, self.result.eliminated)[index]
            self.system_view.set_system(system, self.numberFormatCombo.currentIndex() == 0)
        else:
            self.stepsStack.setCurrentWidget(self.equationsPage if index == 3 else self.displacementsPage)

    def _show_sweep(self, index: int) -> None:
        '''Переключает прямой ход по строкам и обратную подстановку.'''
        if self.result is None or self.stepsBar.currentIndex() != 2:
            return
        self.forwardControls.setVisible(index == 0)
        self.forwardDetails.setVisible(index == 0)
        self.backSubstitutionPanel.setVisible(index == 1)
        if index == 0:
            self._refresh_forward()
        else:
            self.system_view.set_system(self.result.eliminated, self.numberFormatCombo.currentIndex() == 0)

    def _refresh_forward(self, index: int = 0) -> None:
        '''Показывает выбранное исключение и матрицу до либо после операции.'''
        if self.result is None or self._forward_details is None or self.stepsBar.currentIndex() != 2 or self.sweepBar.currentIndex() != 0:
            return
        row = self.forwardRowSpin.value() - 1
        completed = row if self.forwardStateCombo.currentIndex() == 1 else row - 1
        system = self._forward_details.trace.system_after(completed)
        self.system_view.set_system(system, self.numberFormatCombo.currentIndex() == 0)
        self.system_view.focus_elimination(row)
        self.forwardDetails.setHtml(self._forward_details.details_html(row))
        self.previousForwardButton.setEnabled(row > 1)
        self.nextForwardButton.setEnabled(row < len(self.result.displacements) - 1)

    def _node_selected(self, current, previous) -> None:
        '''Выводит символическое уравнение и подстановку для выбранного узла.'''
        if self.result is None or not current.isValid():
            return
        row = current.row()
        n = len(self.result.displacements)
        if self.result.model.supports[row]:
            formula = f'Δ{row + 1} = 0'
        elif row == 0:
            formula = 'k1 * (Δ1 - Δ2) = F1 + q1 * L1 / 2'
        elif row == n - 1:
            formula = f'k{row} * (Δ{n} - Δ{row}) = F{n} + q{row} * L{row} / 2'
        else:
            formula = (f'-k{row} * Δ{row} + (k{row} + k{row + 1}) * Δ{row + 1}'
                       f' - k{row + 1} * Δ{row + 2} = F{row + 1}'
                       f' + q{row} * L{row} / 2 + q{row + 1} * L{row + 1} / 2')
        numeric = self._node_models[0].equation(row, self.numberFormatCombo.currentIndex() == 0)
        value = number_text(self.result.displacements[row], self.numberFormatCombo.currentIndex() == 0)
        if self.result.model.supports[row]:
            text = f'Узел {row + 1} закреплён   Δ{row + 1} = 0 м'
        else:
            text = f'Формула   {formula}\nПодстановка   {numeric}\nРезультат   Δ{row + 1} = {value} м'
        self.nodeFormulaLabel.setText(formula_html(text))

    def _back_node_selected(self, current, previous) -> None:
        '''Показывает полную подстановку выбранного шага обратного хода.'''
        if self.result is not None and current.isValid():
            self.backSubstitutionDetails.setHtml(self._node_models[2].details_html(current.row()))

    def resizeEvent(self, event) -> None:
        '''Заменяет ряд шагов компактным списком на узком экране.'''
        super().resizeEvent(event)
        compact = self.width() < 900
        self.stepsBar.setVisible(not compact)
        self.stepCombo.setVisible(compact)
        self.forwardControlsLayout.addWidget(self.forwardStateCombo, 1 if compact else 0,
                                             0 if compact else 3, 1, 3 if compact else 1)
        self.forwardControlsLayout.setColumnStretch(1, 1 if compact else 0)
        self.forwardControlsLayout.setColumnStretch(3, 0 if compact else 1)
        for button in (self.previousForwardButton, self.nextForwardButton):
            button.setMaximumWidth(16777215 if compact else 110)
        self.forwardRowSpin.setMaximumWidth(16777215 if compact else 200)
