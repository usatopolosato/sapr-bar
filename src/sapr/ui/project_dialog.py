'''Предоставляет диалог проектов текущего демонстрационного сеанса.'''

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import QDialog, QWidget

from .loader import load_form


class ProjectDialog(QDialog):
    '''Запрашивает имя нового проекта или выбор проекта из списка.

    Args:
        project_names: Имена проектов текущего сеанса.
        create: Признак режима создания проекта.
        parent: Родительское окно.
    '''

    def __init__(self, project_names: list[str], create: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        load_form('project_dialog.ui', self)
        self._create = create
        self.setWindowTitle('Создать проект' if create else 'Выбрать проект')
        self.titleLabel.setText(self.windowTitle())
        self.descriptionLabel.setText('Стержневая система на растяжение и сжатие')
        self.modeStack.setCurrentWidget(self.createPage if create else self.openPage)
        self.continueButton.setText('Создать проект' if create else 'Открыть проект')
        self.projectList.addItems(project_names)
        if project_names:
            self.projectList.setCurrentRow(0)
        self.nameInput.setValidator(QRegularExpressionValidator(QRegularExpression(r'[\p{L}\p{N} -]{1,60}'), self))
        next_name = 'Новый проект'
        number = 2
        while next_name in project_names:
            next_name = f'Новый проект {number}'
            number += 1
        self.nameInput.setText(next_name)
        self.nameInput.selectAll()
        self.nameInput.textChanged.connect(self._update_button)
        self.projectList.currentRowChanged.connect(self._update_button)
        self.projectList.itemDoubleClicked.connect(lambda _: self.accept())
        self.cancelButton.clicked.connect(self.reject)
        self.continueButton.clicked.connect(self.accept)
        self._update_button()

    def _update_button(self) -> None:
        '''Разрешает продолжение только при корректном выборе.'''
        valid = bool(self.nameInput.text().strip()) if self._create else self.projectList.currentItem() is not None
        self.continueButton.setEnabled(valid)

    def project_name(self) -> str:
        '''Возвращает имя выбранного рабочего пространства.

        Returns:
            Имя нового или выбранного проекта.
        '''
        if self._create:
            return self.nameInput.text().strip()
        selected = self.projectList.currentItem()
        return selected.text() if selected is not None else ''

