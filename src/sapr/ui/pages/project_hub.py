'''Предоставляет страницу выбора модуля проекта.'''

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..loader import load_form


class ProjectHubPage(QWidget):
    '''Показывает три этапа работы с расчётной моделью.

    Args:
        parent: Родительский виджет страницы.
    '''

    preprocessorRequested = pyqtSignal()
    processorRequested = pyqtSignal()
    postprocessorRequested = pyqtSignal()
    homeRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        load_form('project_hub.ui', self)
        self.preprocessorButton.clicked.connect(self.preprocessorRequested.emit)
        self.processorButton.clicked.connect(self.processorRequested.emit)
        self.postprocessorButton.clicked.connect(self.postprocessorRequested.emit)
        self.returnButton.clicked.connect(self.homeRequested.emit)

    def set_project_name(self, name: str) -> None:
        '''Устанавливает название текущего проекта.

        Args:
            name: Название рабочего пространства.
        '''
        self.projectNameLabel.setText(name)

