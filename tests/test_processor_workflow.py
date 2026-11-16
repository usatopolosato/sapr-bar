'''Проверяет запуск, показ этапов и отзыв устаревшего результата в Qt.'''

from dataclasses import replace
from decimal import Decimal
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.sapr.domain import demo_model
from src.sapr.storage import ProjectStore
from src.sapr.ui.main_window import MainWindow, Page
from src.sapr.ui.theme import ThemeManager, ThemeMode


class ProcessorWorkflowTests(unittest.TestCase):
    '''Проверяет согласованность файлов, состояния интерфейса и расчёта.'''

    @classmethod
    def setUpClass(cls) -> None:
        '''Создаёт приложение для проверки сигналов рабочих потоков.'''
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self) -> None:
        '''Открывает независимый проверенный проект.'''
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        settings = QSettings(str(self.root / 'settings.ini'), QSettings.Format.IniFormat)
        self.theme = ThemeManager(self.app, persist=False)
        self.window = MainWindow(self.theme, settings)
        self.store = ProjectStore()
        project = self.store.create(self.root, 'Процессор')
        self.project = self.store.save(project, demo_model(), validate=True)
        self.window._activate_project(self.project)
        self.window.navigate(Page.PROCESSOR)
        self.page = self.window.processor_page

    def tearDown(self) -> None:
        '''Закрывает окно без записи изменений модели.'''
        self.window.current_project = None
        self.window._dirty = False
        self.window.preprocessor_page.set_model(demo_model())
        self.window.close()
        self.window.deleteLater()
        self.theme.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def _calculate(self) -> None:
        '''Ожидает завершения фонового расчёта с ограничением времени.'''
        self.page.calculateButton.click()
        deadline = time.monotonic() + 10
        while self.window._processor_task is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNotNone(self.page.result, self.page.statusLabel.text())

    def test_all_steps_use_same_decimal_result(self) -> None:
        '''Показывает обе матрицы, прямой ход, уравнения и вектор delta.'''
        self._calculate()
        result = self.page.result
        for step, system in enumerate((result.original, result.constrained, result.eliminated)):
            self.page.stepsBar.setCurrentIndex(step)
            matrix = self.page.system_view.matrixView.model()
            self.assertEqual(matrix.data(matrix.index(0, 0), Qt.ItemDataRole.UserRole), system.diagonal[0])
            self.assertEqual(self.page.stepsStack.currentWidget(), self.page.matrixPage)
            self.assertTrue(self.page.backSubstitutionPanel.isHidden())
        self.page.sweepBar.setCurrentIndex(1)
        self.assertFalse(self.page.backSubstitutionPanel.isHidden())
        self.assertIs(self.page.system_view.matrixView.model().system, result.eliminated)
        back = self.page.backSubstitutionView.model()
        self.page.backSubstitutionView.selectRow(1)
        self.assertIn(back.substitution(1, True), self.page.backSubstitutionDetails.toPlainText())
        self.assertEqual(back.index(0, 1).data(Qt.ItemDataRole.UserRole), result.displacements[-1])
        self.page.stepsBar.setCurrentIndex(3)
        self.assertIn('Δ1 = 0', self.page.equationsView.model().index(0, 0).data())
        self.page.stepsBar.setCurrentIndex(4)
        vector = self.page.displacementsView.model()
        self.assertEqual(vector.rowCount(), 4)
        self.assertEqual(vector.index(3, 0).data(Qt.ItemDataRole.UserRole), result.displacements[3])
        self.page.numberFormatCombo.setCurrentIndex(1)
        self.assertIs(self.page.result, result)
        self.assertEqual(self.page.displacementsView.model().index(3, 0).data(), str(result.displacements[3]))
        self.assertEqual(self.page.backSubstitutionView.currentIndex().row(), 1)
        self.assertIn(self.page.backSubstitutionView.model().substitution(1, False), self.page.backSubstitutionDetails.toPlainText())

    def test_forward_controls_show_zeroing_and_keep_selection(self) -> None:
        '''Согласует матрицу, пояснение и выбранную строку при переключениях.'''
        self._calculate()
        self.page.stepsBar.setCurrentIndex(2)
        self.assertFalse(self.page.forwardControls.isHidden())
        self.assertFalse(self.page.previousForwardButton.isEnabled())
        self.page.nextForwardButton.click()
        self.assertEqual(self.page.forwardRowSpin.value(), 3)
        self.page.forwardStateCombo.setCurrentIndex(0)
        before = self.page.system_view.matrixView.model()
        self.assertEqual(before.index(2, 1).data(Qt.ItemDataRole.UserRole), self.page.result.constrained.lower[1])
        self.assertTrue(before.index(2, 1).data(Qt.ItemDataRole.FontRole).bold())
        self.page.forwardStateCombo.setCurrentIndex(1)
        after = self.page.system_view.matrixView.model()
        self.assertEqual(after.index(2, 1).data(Qt.ItemDataRole.UserRole), 0)
        self.assertIn('Обнуление', self.page.forwardDetails.toPlainText())
        self.page.numberFormatCombo.setCurrentIndex(1)
        self.assertEqual(self.page.forwardRowSpin.value(), 3)
        self.page.sweepBar.setCurrentIndex(1)
        self.assertTrue(self.page.forwardControls.isHidden())
        self.page.sweepBar.setCurrentIndex(0)
        self.assertEqual(self.page.forwardRowSpin.value(), 3)
        self.page.forwardRowSpin.setValue(len(self.page.result.displacements))
        self.assertFalse(self.page.nextForwardButton.isEnabled())
        self.assertIs(self.page.system_view.matrixView.model().system, self.page.result.eliminated)
        self.page.set_availability(False, 'Данные изменены', reset=True)
        self.assertIsNone(self.page._forward_details)
        self.assertIs(self.page.stateStack.currentWidget(), self.page.emptyPage)

    def test_unapplied_invalid_input_blocks_processor(self) -> None:
        '''Не запускает сохранённую модель поверх некорректного нового ввода.'''
        self.window.navigate(Page.PREPROCESSOR)
        self.window.preprocessor_page.lengthInput.setText('ошибка')
        self.window.preprocessor_page.lengthInput.setModified(True)
        self.window.navigate(Page.PROCESSOR)
        self.assertFalse(self.page.calculateButton.isEnabled())
        self.assertIsNone(self.page.result)

    def test_edit_requires_successful_recheck(self) -> None:
        '''Отзывает результат после правки и разрешает запуск после проверки.'''
        self._calculate()
        self.window.navigate(Page.PREPROCESSOR)
        editor = self.window.preprocessor_page
        editor.lengthInput.setText('4')
        editor.lengthInput.setModified(True)
        self.window.navigate(Page.PROCESSOR)
        self.assertFalse(self.page.calculateButton.isEnabled())
        self.assertIsNone(self.page.result)
        self.window.validate_project()
        self.window.navigate(Page.PROCESSOR)
        self.assertTrue(self.page.calculateButton.isEnabled())
        self._calculate()
        self.assertEqual(self.page.result.model.bars[0].length_m, Decimal('4'))

    def test_deleted_prepared_file_blocks_at_click_without_timer(self) -> None:
        '''Повторно проверяет файлы непосредственно при запуске.'''
        (self.project.path / 'project.ldx').unlink()
        self.page.calculateButton.click()
        self.assertIsNone(self.window._processor_task)
        self.assertIsNone(self.page.result)
        self.assertFalse(self.page.calculateButton.isEnabled())

    def test_external_change_hides_existing_solution(self) -> None:
        '''Убирает устаревшую матрицу после внешнего изменения исходника.'''
        self._calculate()
        path = self.project.path / 'project.cn'
        path.write_bytes(path.read_bytes() + b'\n')
        self.window._watch_processor_files()
        self.assertIsNone(self.page.result)
        self.assertEqual(self.page.stateStack.currentWidget(), self.page.emptyPage)

    def test_old_request_cannot_publish_into_another_project(self) -> None:
        '''Игнорирует запоздалое завершение от ранее открытого проекта.'''
        self._calculate()
        old_result = self.page.result
        revision = self.window._processor_revision
        project = self.store.create(self.root, 'Другой проект')
        self.window._activate_project(project)
        self.window._processor_finished(revision, old_result, 'old', '')
        self.assertIsNone(self.page.result)

    def test_layout_and_synchronized_scroll_in_both_themes(self) -> None:
        '''Сохраняет доступ ко всем шагам при небольшом окне и смене темы.'''
        source = demo_model()
        data = replace(source, bars=(source.bars[0],) * 50, nodal_forces=(Decimal(0),) * 50 + (Decimal(1),),
                       distributed_loads=(Decimal(0),) * 50, supports=(True,) + (False,) * 50)
        self.project = self.store.save(self.project, data, validate=True)
        self.window._activate_project(self.project)
        self.window.navigate(Page.PROCESSOR)
        self._calculate()
        self.window.show()
        for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
            self.theme.set_mode(mode)
            for width, height in ((1440, 864), (800, 600)):
                self.window.resize(width, height)
                for step in range(5):
                    self.page.stepsBar.setCurrentIndex(step)
                    self.app.processEvents()
                    self.assertEqual(self.window._page_containers[Page.PROCESSOR].horizontalScrollBar().maximum(), 0)
                self.page.stepsBar.setCurrentIndex(0)
                self.app.processEvents()
                views = self.page.system_view._views
                views[0].verticalScrollBar().setValue(200)
                self.assertEqual([view.verticalScrollBar().value() for view in views], [200, 200, 200])
