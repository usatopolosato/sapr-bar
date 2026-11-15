'''Проверяет связность НДС, интерфейса и актуальных файлов проекта.'''

from dataclasses import replace
from decimal import Decimal as D, localcontext
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.sapr.domain import Bar, StructuralModel, demo_model
from src.sapr.domain.postprocessor import AxialPostprocessor
from src.sapr.domain.processor import AxialProcessor
from src.sapr.ui.main_window import MainWindow, Page
from src.sapr.ui.theme import ThemeManager, ThemeMode
from src.sapr.ui.widgets.response_table import ResponseTableModel
from src.sapr.ui.widgets.response_plot import ResponsePlot


class PostprocessorWorkflowTests(unittest.TestCase):
    '''Проверяет подготовку результатов, экспорт, сечения и отзыв расчёта.'''

    @classmethod
    def setUpClass(cls):
        '''Создаёт единый экземпляр приложения для сценариев Qt.'''
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        '''Открывает проект с прошедшими проверку исходными файлами.'''
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.theme = ThemeManager(self.app, persist=False)
        self.window = MainWindow(self.theme, QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat))
        store = self.window._store
        self.project = store.save(store.create(root, 'Постпроцессор'), demo_model(), validate=True)
        self.window._activate_project(self.project)
        self.page = self.window.postprocessor_page

    def tearDown(self):
        '''Завершает фоновые операции и закрывает окно без записи правок.'''
        self._wait(lambda: self.window._processor_task is None and self.window._postprocessor_task is None
                   and self.window._report_task is None)
        self.window.current_project = None
        self.window._dirty = False
        self.window.preprocessor_page.set_model(demo_model())
        self.window.close()
        self.window.deleteLater()
        self.theme.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def _wait(self, condition):
        '''Ожидает результат Qt, сохраняя ограничение по времени.'''
        end = time.monotonic() + 15
        while not condition() and time.monotonic() < end:
            QTest.qWait(10)
        self.assertTrue(condition())

    def _calculate(self):
        '''Выполняет процессор и открывает готовый постпроцессор.'''
        self.window.navigate(Page.PROCESSOR)
        self.window.calculate_project()
        self._wait(lambda: self.window._processor_task is None)
        self.assertIsNotNone(self.window.processor_page.result)
        self.window.navigate(Page.POSTPROCESSOR)
        self._wait(lambda: self.window._postprocessor_task is None)
        self.assertIsNotNone(self.page.result)

    def test_requires_current_successful_processor_result(self):
        '''Проверенные файлы сами по себе не заменяют рассчитанный вектор Delta.'''
        self.window.navigate(Page.POSTPROCESSOR)
        self.assertIsNone(self.page.result)
        self.assertFalse(self.page.reportButton.isEnabled())
        self._calculate()
        self.assertIs(self.page.result.processor, self.window.processor_page.result)
        self.assertTrue(self.page.reportButton.isEnabled())
        self.assertEqual(self.page.stateStack.currentWidget(), self.page.resultsPage)

    def test_section_and_table_preserve_exact_decimal(self):
        '''Показывает то же сечение в таблице, полях и аналитическом графике.'''
        self._calculate()
        self.page.barCombo.setCurrentIndex(1)
        self.page.positionInput.setText('1.234567891234567891')
        self.page.sectionButton.click()
        exact = self.page.result.at(1, D('1.234567891234567891'))
        self.assertEqual(self.page.forceValue.toolTip(), str(exact.force_n))
        self.assertEqual(self.page.stressValue.toolTip(), str(exact.stress_pa))
        self.assertEqual(self.page.displacementValue.toolTip(), str(exact.displacement_m))
        self.assertEqual(self.page.epures_view.selected_x, exact.x_m)
        self.assertEqual(self.page.graph_view.selected_bar, 1)
        self.page.viewsBar.setCurrentIndex(2)
        model = self.page.resultsTable.model()
        for row in (0, 5, model.rowCount() - 1):
            section = model.section(row)
            self.assertEqual(model.index(row, 2).data(Qt.ItemDataRole.UserRole), section.force_n)
            self.assertEqual(model.index(row, 4).data(Qt.ItemDataRole.UserRole), section.displacement_m)
        self.page.resultsTable.selectRow(model.rowCount() - 1)
        self.assertEqual(self.page.barCombo.currentIndex(), 2)
        self.assertEqual(self.page.epures_view.selected_x, D(1))

    def test_invalid_coordinate_keeps_last_valid_section_and_recovers(self):
        '''Ошибочный ввод не изменяет расчёт, а исправление снимает подсветку.'''
        self._calculate()
        self.page.positionInput.setText('1')
        self.page.sectionButton.click()
        for text in ('bad', '-1', '100', 'NaN', '1e1001'):
            self.page.positionInput.setText(text)
            self.page.sectionButton.click()
            self.assertTrue(self.page.positionInput.property('invalid'))
            self.assertEqual(self.page.epures_view.selected_x, D(1))
        self.page.positionInput.setText('0.5')
        self.page.sectionButton.click()
        self.assertFalse(self.page.positionInput.property('invalid'))
        self.assertEqual(self.page.epures_view.selected_x, D('0.5'))

    def test_unapplied_input_and_saved_changes_invalidate_every_view(self):
        '''Не показывает прежние эпюры после неприменённого неверного ввода.'''
        self._calculate()
        self.window.navigate(Page.PREPROCESSOR)
        self.window.preprocessor_page.lengthInput.setText('bad')
        self.window.preprocessor_page.lengthInput.setModified(True)
        self.window.navigate(Page.POSTPROCESSOR)
        self.assertIsNone(self.page.result)
        self.assertIsNone(self.page.epures_view.result)
        self.assertIsNone(self.page.graph_view.result)
        self.assertFalse(self.page.reportButton.isEnabled())
        self.window.preprocessor_page.cancelBarButton.click()
        self.window.save_project()
        self.window.navigate(Page.POSTPROCESSOR)
        self.assertIsNone(self.page.result)
        self._calculate()

    def test_external_change_invalidates_postprocessor_and_export(self):
        '''Отзывает НДС при изменении файла и при экспорте до срабатывания таймера.'''
        self._calculate()
        path = self.project.path / 'project.cnx'
        path.write_bytes(path.read_bytes() + b'\n')
        self.page.reportButton.click()
        self.assertIsNone(self.page.result)
        self.assertIsNone(self.window._report_task)
        self.assertFalse((self.project.path / 'project.res').exists())

    def test_watcher_checks_files_on_postprocessor_page(self):
        '''Следит за CN и LD, когда пользователь просматривает эпюры.'''
        self._calculate()
        path = self.project.path / 'project.ld'
        path.write_bytes(path.read_bytes() + b'\n')
        self.window._watch_processor_files()
        self.assertIsNone(self.page.result)
        self.assertEqual(self.page.stateStack.currentWidget(), self.page.emptyPage)

    def test_export_report_uses_same_result_and_density(self):
        '''Сохраняет отчёт текущего расчёта из кнопки интерфейса.'''
        self._calculate()
        self.page.subdivisionsSpin.setValue(3)
        self.page.reportButton.click()
        self._wait(lambda: self.window._report_task is None)
        text = (self.project.path / 'project.res').read_text(encoding='utf-8')
        self.assertIn('разбиений на стержень 3', text)
        self.assertIn(str(self.page.result.processor.displacements[2]), text)
        self.assertIn('Отчёт сохранён', self.page.statusLabel.text())

    def test_old_result_cannot_enter_another_project(self):
        '''Отбрасывает завершение задачи прежнего проекта.'''
        self._calculate()
        old = self.page.result
        revision, fingerprint = self.window._processor_revision, self.window._processor_fingerprint
        other = self.window._store.create(self.project.path.parent, 'Другой проект')
        self.window._activate_project(other)
        self.window._postprocessor_finished(revision, old, fingerprint, '')
        self.assertIsNone(self.page.result)

    def test_themes_and_adaptive_views(self):
        '''Сохраняет доступ к эпюрам и таблице при ширине окна 800 пикселей.'''
        self._calculate()
        self.window.show()
        for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
            self.theme.set_mode(mode)
            for width, height in ((1440, 864), (800, 600)):
                self.window.resize(width, height)
                for index in range(3):
                    self.page.viewsBar.setCurrentIndex(index)
                    self.app.processEvents()
                    self.assertFalse(self.page.grab().isNull())
                    self.assertEqual(self.window._page_containers[Page.POSTPROCESSOR].horizontalScrollBar().maximum(), 0)
                self.assertEqual(self.page.workspaceSplitter.orientation(),
                                 Qt.Orientation.Vertical if width == 800 else Qt.Orientation.Horizontal)


class ResponseTableTests(unittest.TestCase):
    '''Проверяет точность и ленивую индексацию таблицы отсчётов.'''

    @classmethod
    def setUpClass(cls):
        '''Создаёт приложение Qt для моделей и рендеринга.'''
        cls.app = QApplication.instance() or QApplication([])

    def test_lazy_rows_match_analytical_sampling(self):
        '''Сопоставляет равномерную сетку с дополнительными характерными точками.'''
        for subdivisions in (1, 3, 7, 10, 1000):
            result = AxialPostprocessor().analyze(AxialProcessor().solve(demo_model()))
            table = ResponseTableModel(result, subdivisions)
            expected = [bar.at(x) for bar in result.bars for x in bar.sample_positions(subdivisions)]
            self.assertEqual(table.rowCount(), len(expected))
            for row, point in enumerate(expected):
                self.assertEqual(table.section(row), point)

    def test_extrema_present_when_density_is_one(self):
        '''Не теряет максимум параболы между двумя закреплёнными концами.'''
        source = StructuralModel((Bar(D(2), D('0.001'), D('2e11'), D('1e6')),),
                                 (D(0), D(0)), (D(2000),), (True, True))
        result = AxialPostprocessor().analyze(AxialProcessor().solve(source))
        for mode in (False, True):
            table = ResponseTableModel(result, 1, mode)
            self.assertIn(D(1), [table.section(row).x_m for row in range(table.rowCount())])

    def test_stress_highlight_preserves_sub_display_precision(self):
        '''Находит превышение, скрываемое обычным контекстом Decimal или форматом.'''
        limit = D('9.99999999999999999999999999999999999999999')
        source = StructuralModel((Bar(D(1), D(1), D(1), limit),), (D(0), D(10)), (D(0),), (True, False))
        result = AxialPostprocessor().analyze(AxialProcessor().solve(source))
        table = ResponseTableModel(result)
        with localcontext() as context:
            context.prec = 6
            self.assertIn('Превышение', table.index(0, 3).data(Qt.ItemDataRole.ToolTipRole))
            self.assertIsNotNone(table.index(0, 3).data(Qt.ItemDataRole.BackgroundRole))

    def test_large_table_does_not_materialize_all_rows(self):
        '''Представляет миллион сечений с памятью, пропорциональной числу стержней.'''
        bar = Bar(D(1), D(1), D(1), D(10))
        count = 1000
        source = StructuralModel((bar,) * count, (D(0),) * count + (D(1),),
                                 (D(0),) * count, (True,) + (False,) * count)
        result = AxialPostprocessor().analyze(AxialProcessor().solve(source))
        table = ResponseTableModel(result, 1000)
        self.assertGreaterEqual(table.rowCount(), 1000000)
        self.assertEqual(len(table._offsets), count + 1)
        self.assertLessEqual(sum(map(len, table._extra_positions)), 7 * count)
        self.assertEqual(table.section(table.rowCount() - 1).x_m, D(1))

    def test_plot_normalizes_extreme_si_values_before_float_conversion(self):
        '''Рисует нулевые поля и диапазоны за пределами float без переполнения.'''
        for exponent, force in ((800, D(1)), (-800, D(1)), (0, D(0))):
            scale = D(f'1e{exponent}')
            inverse = D(f'1e{-exponent}')
            source = StructuralModel((Bar(scale, scale, inverse, D('1e900')),),
                                     (D(0), force), (D(0),), (True, False))
            result = AxialPostprocessor().analyze(AxialProcessor().solve(source))
            for local in (False, True):
                view = ResponsePlot(local=local)
                view.set_result(result)
                view.resize(900, 550)
                view.show()
                for component in ('N', 'sigma', 'u'):
                    view.set_component(component)
                    view.set_section(0, scale / 2)
                    view.zoom_by(D('1.5'))
                    self.app.processEvents()
                    self.assertFalse(view.grab().isNull())
                    view.fit_view()
                view.close()
                view.deleteLater()
        self.app.processEvents()
