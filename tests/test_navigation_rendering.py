'''Проверяет отрисовку страниц сразу после переключения.'''

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from src.sapr.ui.main_window import MainWindow, Page
from src.sapr.ui.theme import ThemeManager, ThemeMode


class NavigationRenderingTests(unittest.TestCase):
    '''Проверяет отсутствие прозрачных кадров и наложения страниц.'''

    @classmethod
    def setUpClass(cls) -> None:
        '''Создаёт приложение Qt для проверки отрисованных кадров.'''
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self) -> None:
        '''Открывает независимое окно с временными настройками.'''
        self.directory = tempfile.TemporaryDirectory()
        settings = QSettings(str(Path(self.directory.name) / 'settings.ini'), QSettings.Format.IniFormat)
        self.theme = ThemeManager(self.app, persist=False)
        self.window = MainWindow(self.theme, settings)
        self.window.resize(1440, 864)
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        '''Освобождает окно и настройки после сценария.'''
        self.window.close()
        self.window.deleteLater()
        self.theme.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def test_first_frame_is_opaque_in_both_themes(self) -> None:
        '''Проверяет первый кадр без ожидания завершения перехода.'''
        for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
            self.theme.set_mode(mode)
            for page in (Page.PROJECT, Page.PREPROCESSOR, Page.PROCESSOR, Page.POSTPROCESSOR, Page.WELCOME):
                with self.subTest(theme=mode.value, page=page.value):
                    self.window.navigate(page)
                    self._assert_page_frame(page)

    def test_rapid_navigation_with_resize_and_theme_change(self) -> None:
        '''Проверяет быстрые переходы при перестройке компоновки и темы.'''
        for width, height, mode in (
            (800, 600, ThemeMode.LIGHT),
            (1440, 864, ThemeMode.DARK),
            (1100, 760, ThemeMode.LIGHT),
        ):
            self.window.resize(width, height)
            self.theme.set_mode(mode)
            for _ in range(3):
                self.window.preprocessorNavButton.click()
                self.window.hubNavButton.click()
                self.window.processorNavButton.click()
                self.window.postprocessorNavButton.click()
                self._assert_page_frame(Page.POSTPROCESSOR)

    def _assert_page_frame(self, page: Page) -> None:
        '''Проверяет видимость страницы и непрозрачность её фона.

        Args:
            page: Ожидаемая активная страница.
        '''
        frame = self.window.pageStack.grab().toImage()
        expected = QColor(self.theme.colors.window)
        for x, y in ((10, 10), (frame.width() - 10, 10), (10, frame.height() - 10)):
            color = frame.pixelColor(x, y)
            self.assertEqual(color.alpha(), 255)
            self.assertEqual(color, expected)
        visible = [key for key, container in self.window._page_containers.items() if container.isVisible()]
        self.assertEqual(visible, [page])
        self.assertEqual(self.window.breadcrumbLabel.text(), page.value)


if __name__ == '__main__':
    unittest.main()
