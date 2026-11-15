'''Предоставляет стартовую страницу приложения.'''

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..loader import load_form
from ..widgets.structure_view import StructureView


class WelcomePage(QWidget):
    '''Отображает действия создания и выбора проекта.

    Args:
        parent: Родительский виджет страницы.
    '''

    createRequested = pyqtSignal()
    openRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        load_form('welcome.ui', self)
        self.structure_view = StructureView.replace(self.welcomeStructureView, compact=True)
        self.createProjectButton.clicked.connect(self.createRequested.emit)
        self.openProjectButton.clicked.connect(self.openRequested.emit)

