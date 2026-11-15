'''Настраивает окружение Qt и запускает главное окно.'''

import sys
from pathlib import Path

from PyQt6.QtCore import QLocale, QSettings
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import ThemeManager


def create_application(
    arguments: list[str] | None = None,
    *,
    persist_theme: bool = True,
    theme_settings: QSettings | None = None,
) -> QApplication:
    '''Создаёт приложение с единой темой и русской локалью.

    Args:
        arguments: Аргументы командной строки для Qt.
        persist_theme: Признак чтения и сохранения выбранной темы.
        theme_settings: Альтернативное хранилище настроек темы.

    Returns:
        Настроенный экземпляр QApplication.
    '''
    app = QApplication(arguments if arguments is not None else sys.argv)
    app.setApplicationName('САПР BAR')
    app.setOrganizationName('usatopolosato')
    app.setStyle('Fusion')
    QLocale.setDefault(QLocale(QLocale.Language.Russian, QLocale.Country.Russia))
    if 'Segoe UI' not in QFontDatabase.families():
        for font_name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
            font_path = Path('C:/Windows/Fonts') / font_name
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont('Segoe UI', 10))
    app.theme_manager = ThemeManager(app, theme_settings, persist_theme)
    return app


def main() -> int:
    '''Запускает цикл обработки событий приложения.

    Returns:
        Код завершения Qt.
    '''
    app = create_application()
    window = MainWindow(app.theme_manager)
    available = app.primaryScreen().availableGeometry()
    window.resize(min(1440, available.width() - 48), min(870, available.height() - 48))
    window.move(available.center() - window.rect().center())
    window.show()
    return app.exec()
