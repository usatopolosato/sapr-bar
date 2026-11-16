'''Предоставляет страницу выбора модуля проекта.'''

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QBoxLayout, QWidget

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
        self.set_availability(False, False, 'Выберите проект', 'Выберите проект')

    def set_project_name(self, name: str) -> None:
        '''Устанавливает название текущего проекта.

        Args:
            name: Название рабочего пространства.
        '''
        self.projectNameLabel.setText(name)

    def set_availability(
        self, processor_ready: bool, postprocessor_ready: bool,
        processor_message: str, postprocessor_message: str,
    ) -> None:
        '''Согласует метки и кнопки с готовностью расчётных модулей.

        Args:
            processor_ready: Признак актуальных проверенных исходных данных.
            postprocessor_ready: Признак успешного расчёта текущей модели.
            processor_message: Состояние процессора или причина недоступности.
            postprocessor_message: Состояние постпроцессора или причина недоступности.
        '''
        for badge, button, card, ready, message in (
            (self.processorBadgeLabel, self.processorButton, self.processorCard,
             processor_ready, processor_message),
            (self.postprocessorBadgeLabel, self.postprocessorButton, self.postprocessorCard,
             postprocessor_ready, postprocessor_message),
        ):
            badge.setText('Доступен' if ready else 'Недоступен')
            badge.setEnabled(ready)
            button.setEnabled(ready)
            for widget in (badge, button, card):
                widget.setToolTip(message)

    def resizeEvent(self, event) -> None:
        '''Перестраивает карточки модулей для узкого окна.

        Args:
            event: Событие изменения размера страницы.
        '''
        compact = self.width() < 760
        self.moduleCardsLayout.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        margin = 18 if self.width() < 1000 else 32
        self.hubLayout.setContentsMargins(margin, margin, margin, margin)
        for card in (self.preprocessorCard, self.processorCard, self.postprocessorCard):
            card.setMinimumHeight(180 if compact else 240)
        super().resizeEvent(event)

