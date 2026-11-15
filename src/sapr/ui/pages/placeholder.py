'''Предоставляет общий экран будущих расчётных модулей.'''

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..loader import load_form


class PlaceholderPage(QWidget):
    '''Показывает назначение ещё не реализованного модуля.

    Args:
        number: Номер этапа работы.
        title: Название модуля.
        description: Краткое описание будущих возможностей.
        parent: Родительский виджет страницы.
    '''

    backRequested = pyqtSignal()

    def __init__(self, number: str, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        load_form('placeholder.ui', self)
        self.moduleNumberLabel.setText(number)
        self.moduleTitleLabel.setText(title)
        self.moduleDescriptionLabel.setText(description)
        self.backButton.clicked.connect(self.backRequested.emit)

