'''Настраивает окружение Qt и запускает главное окно.'''

import sys
from pathlib import Path

from PyQt6.QtCore import QLocale
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

from .ui.loader import read_theme
from .ui.main_window import MainWindow


def create_application(arguments: list[str] | None = None) -> QApplication:
    '''Создаёт приложение с единой темой и русской локалью.

    Args:
        arguments: Аргументы командной строки для Qt.

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
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, '#10151d'),
        (QPalette.ColorRole.WindowText, '#e8edf5'),
        (QPalette.ColorRole.Base, '#171f2a'),
        (QPalette.ColorRole.AlternateBase, '#1c2735'),
        (QPalette.ColorRole.Text, '#e8edf5'),
        (QPalette.ColorRole.Button, '#1c2735'),
        (QPalette.ColorRole.ButtonText, '#e8edf5'),
        (QPalette.ColorRole.Highlight, '#285349'),
        (QPalette.ColorRole.HighlightedText, '#d3fff0'),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(read_theme())
    return app


def main() -> int:
    '''Запускает цикл обработки событий приложения.

    Returns:
        Код завершения Qt.
    '''
    app = create_application()
    window = MainWindow()
    available = app.primaryScreen().availableGeometry()
    window.resize(min(1440, available.width() - 48), min(870, available.height() - 48))
    window.move(available.center() - window.rect().center())
    window.show()
    return app.exec()
