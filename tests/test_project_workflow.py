'''Проверяет сохранение проекта через действия интерфейса.'''

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.sapr.domain import demo_model
from src.sapr.storage import ProjectStore
from src.sapr.ui.main_window import MainWindow, Page
from src.sapr.ui.theme import ThemeManager


class ProjectWorkflowTests(unittest.TestCase):
    '''Проверяет связь редактора, диагностики и файлов проекта.'''

    @classmethod
    def setUpClass(cls) -> None:
        '''Создаёт приложение для проверки сигналов интерфейса.'''
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self) -> None:
        '''Открывает отдельный проверенный проект для каждого сценария.'''
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        settings = QSettings(str(self.root / 'settings.ini'), QSettings.Format.IniFormat)
        self.theme = ThemeManager(self.app, persist=False)
        self.window = MainWindow(self.theme, settings)
        self.store = ProjectStore()
        self.project = self.store.create(self.root, 'Проверка')
        self.project = self.store.save(self.project, demo_model(), validate=True)
        self.window._activate_project(self.project)
        self.page = self.window.preprocessor_page
        self.window.navigate(Page.PREPROCESSOR)

    def tearDown(self) -> None:
        '''Закрывает окно без модального запроса и освобождает файлы.'''
        self.window.current_project = None
        self.window._dirty = False
        self.window.close()
        self.window.deleteLater()
        self.theme.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def test_edit_save_reopen_preserves_decimal(self) -> None:
        '''Проверяет точность значения после кнопки Принять и сохранения.'''
        from decimal import Decimal

        exact = '0.0012345678901234567890123456789'
        self.page.areaInput.setText(exact)
        self.page.areaInput.setModified(True)
        self.page.applyBarButton.click()
        self.assertTrue(self.window._dirty)
        self.assertTrue(self.window.save_project())
        reopened = self.store.load(self.project.path)
        self.assertEqual(reopened.model.bars[0].area_m2, Decimal(exact))
        self.assertTrue(reopened.validated)
        self.assertFalse(self.window._dirty)

    def test_save_invalid_model_retains_draft_without_prepared_files(self) -> None:
        '''Проверяет сохранение модели без опор и отзыв старой подготовки.'''
        self.page.supportNodeCombo.setCurrentIndex(0)
        self.page.freeSupportButton.click()
        self.assertTrue(self.window._dirty)
        self.assertTrue(self.window.save_project())
        reopened = self.store.load(self.project.path)
        self.assertFalse(reopened.model.left_support)
        self.assertFalse(reopened.validated)
        self.assertFalse((self.project.path / 'project.cnx').exists())
        self.assertFalse((self.project.path / 'project.ldx').exists())

    def test_successful_check_writes_numeric_processed_files(self) -> None:
        '''Проверяет формирование числовых файлов действием Проверить.'''
        project = self.store.create(self.root, 'Проверка подготовки')
        self.window._activate_project(project)
        self.page.set_model(demo_model())
        self.page.validateButton.click()
        for extension in ('cnx', 'ldx'):
            text = (project.path / f'project.{extension}').read_text(encoding='ascii')
            self.assertEqual(text.splitlines()[-1], extension.upper())
            self.assertFalse(text.lstrip().startswith('{'))
        self.assertTrue(self.store.load(project.path).validated)
        self.assertFalse((project.path / 'project.mdx').exists())

    def test_failed_check_leaves_only_source_files(self) -> None:
        '''Проверяет отсутствие обработанных файлов для пустой модели.'''
        project = self.store.create(self.root, 'Пустая модель')
        self.window._activate_project(project)
        self.page.validateButton.click()
        self.assertFalse((project.path / 'project.cnx').exists())
        self.assertFalse((project.path / 'project.ldx').exists())
        self.assertFalse((project.path / 'project.mdx').exists())
        self.assertFalse(self.store.load(project.path).validated)

    def test_opened_long_decimal_is_not_truncated_in_inspector(self) -> None:
        '''Проверяет открытие и повторное применение длинного значения файла.'''
        from dataclasses import replace
        from decimal import Decimal

        exact = Decimal('0.' + '123456789' * 40)
        original = demo_model()
        model = replace(original, bars=(replace(original.bars[0], area_m2=exact),) + original.bars[1:])
        saved = self.store.save(self.project, model, validate=True)
        self.window._activate_project(self.store.load(saved.path))
        self.assertEqual(Decimal(self.page.areaInput.text()), exact)
        self.page.applyBarButton.click()
        self.assertEqual(self.page.model.bars[0].area_m2, exact)

    def test_failed_write_preserves_unsaved_state(self) -> None:
        '''Проверяет сохранность редактирования при ошибке записи на диск.'''
        self.page.supportNodeCombo.setCurrentIndex(len(self.page.model.supports) - 1)
        self.page.fixedSupportButton.click()
        with patch.object(self.window._store, 'save', side_effect=PermissionError('Нет доступа')):
            with patch.object(self.window, '_show_error') as notice:
                self.assertFalse(self.window.save_project())
                notice.assert_called_once()
        self.assertTrue(self.window._dirty)
        self.assertTrue(self.page.model.right_support)
        self.assertFalse(self.store.load(self.project.path).model.right_support)

    def test_cancel_leaves_modified_project_open(self) -> None:
        '''Проверяет отмену закрытия без потери изменённой модели.'''
        self.page.supportNodeCombo.setCurrentIndex(len(self.page.model.supports) - 1)
        self.page.fixedSupportButton.click()
        QTimer.singleShot(0, lambda: self._choose_message_button('Отмена'))
        self.assertFalse(self.window._confirm_project_change())
        self.assertTrue(self.window._dirty)

    def test_bad_input_can_be_discarded_on_close(self) -> None:
        '''Проверяет возможность закрыть проект с ошибочным вводом.'''
        self.page.lengthInput.setText('не число')
        self.page.lengthInput.setModified(True)
        QTimer.singleShot(0, lambda: self._choose_message_button('Не сохранять'))
        self.assertTrue(self.window._confirm_project_change())
        self.assertEqual(self.store.load(self.project.path).model, demo_model())

    def test_compact_layout_keeps_horizontal_content_accessible(self) -> None:
        '''Проверяет ширину редактора при переходе с большого окна на малое.'''
        self.window.resize(1440, 864)
        self.window.show()
        self.app.processEvents()
        self.window.resize(800, 600)
        for _ in range(5):
            self.app.processEvents()
        container = self.window._page_containers[Page.PREPROCESSOR]
        self.assertEqual(container.horizontalScrollBar().maximum(), 0)
        self.assertTrue(self.window.sectionButton.isVisible())
        self.assertFalse(self.window.sidebar.isVisible())

    def test_compact_welcome_keeps_project_actions_visible(self) -> None:
        '''Проверяет доступ к созданию проекта без прокрутки на малом экране.'''
        self.window.navigate(Page.WELCOME)
        self.window.resize(800, 600)
        self.window.show()
        for _ in range(5):
            self.app.processEvents()
        container = self.window._page_containers[Page.WELCOME]
        self.assertEqual(container.verticalScrollBar().maximum(), 0)
        self.assertEqual(container.horizontalScrollBar().maximum(), 0)

    def _choose_message_button(self, title: str) -> None:
        '''Выбирает действие модального диалога в текущем сценарии.

        Args:
            title: Подпись ожидаемой кнопки.
        '''
        dialog = self.app.activeModalWidget()
        if isinstance(dialog, QMessageBox):
            for button in dialog.buttons():
                if button.text() == title:
                    button.click()
                    return
        raise AssertionError('Ожидаемый диалог не открыт')


if __name__ == '__main__':
    unittest.main()
