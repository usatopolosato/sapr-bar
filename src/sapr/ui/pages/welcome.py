'''Предоставляет стартовую страницу приложения.'''

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QBoxLayout, QSizePolicy, QWidget

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

    def resizeEvent(self, event) -> None:
        '''Перестраивает стартовый экран по доступной ширине.

        Args:
            event: Событие изменения размера страницы.
        '''
        compact = self.width() < 1000
        self.welcomeLayout.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        margin = 24 if compact else 48
        self.welcomeLayout.setContentsMargins(margin, margin, margin, margin)
        self.welcomeLayout.setSpacing(24 if compact else 48)
        self.welcomeLayout.setStretch(0, 0 if compact else 3)
        self.welcomeLayout.setStretch(1, 1 if compact else 2)
        self.startCard.setMaximumWidth(16777215 if compact else 440)
        self.structure_view.setVisible(not compact)
        self.heroLayout.setSpacing(12 if compact else 20)
        for spacer in (self.heroLayout.itemAt(0).spacerItem(), self.heroLayout.itemAt(self.heroLayout.count() - 1).spacerItem()):
            spacer.changeSize(0, 0 if compact else 24, QSizePolicy.Policy.Minimum,
                              QSizePolicy.Policy.Fixed if compact else QSizePolicy.Policy.Expanding)
        if compact:
            self.startCardLayout.setContentsMargins(24, 24, 24, 24)
        else:
            self.startCardLayout.setContentsMargins(32, 36, 32, 28)
        role = 'pageTitle' if compact else 'heroTitle'
        if self.heroTitleLabel.property('role') != role:
            self.heroTitleLabel.setProperty('role', role)
            self.heroTitleLabel.setText('Расчёт стержневых систем' if compact else 'Расчёт стержневых\nсистем')
            self.heroTitleLabel.style().unpolish(self.heroTitleLabel)
            self.heroTitleLabel.style().polish(self.heroTitleLabel)
        self.heroLayout.invalidate()
        super().resizeEvent(event)

