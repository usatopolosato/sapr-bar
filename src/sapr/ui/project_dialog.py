'''Запрашивает название и расположение нового проекта.'''

import os
from pathlib import Path

from PyQt6.QtCore import QRegularExpression, QStandardPaths
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import QDialog, QFileDialog, QWidget

from ..storage import Project, ProjectStore
from .feedback import set_input_error, show_feedback
from .loader import load_form


class ProjectDialog(QDialog):
    '''Настраивает создание отдельной папки проекта.

    Args:
        directory: Исходная родительская папка проектов.
        parent: Родительское окно.
        store: Хранилище для создания файлов проекта.
    '''

    def __init__(
        self, directory: Path | None = None, parent: QWidget | None = None,
        *, store: ProjectStore | None = None,
    ) -> None:
        super().__init__(parent)
        load_form('project_dialog.ui', self)
        self._store = store if store is not None else ProjectStore()
        self.project: Project | None = None
        self.errorLabel.hide()
        default_directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
        if not default_directory.is_dir():
            default_directory = Path.home()
        self.directoryInput.setText(str(directory or default_directory))
        self.nameInput.setValidator(QRegularExpressionValidator(QRegularExpression(r'[\p{L}\p{N} -]{1,60}'), self))
        self.nameInput.setText('Новый проект')
        self.nameInput.selectAll()
        self.browseButton.clicked.connect(self._choose_directory)
        self.nameInput.textChanged.connect(self._update_button)
        self.directoryInput.textChanged.connect(self._update_button)
        self.cancelButton.clicked.connect(self.reject)
        self.continueButton.clicked.connect(self.accept)
        self._update_button()

    def _choose_directory(self) -> None:
        '''Открывает выбор родительской папки для проекта.'''
        try:
            initial = self.project_directory()
            while not initial.exists() and initial.parent != initial:
                initial = initial.parent
        except (OSError, ValueError):
            initial = Path.home()
        directory = QFileDialog.getExistingDirectory(self, 'Расположение проекта', str(initial))
        if directory:
            self.directoryInput.setText(directory)

    def _update_button(self) -> None:
        '''Показывает итоговую папку и проверяет наличие имени и пути.'''
        self.errorLabel.hide()
        valid = self.nameInput.hasAcceptableInput() and bool(self.project_name()) and bool(self.directoryInput.text().strip())
        set_input_error(self.directoryInput, False)
        try:
            target = self.project_directory() / self.project_name() if valid else None
            self.targetPathLabel.setText(str(target) if target is not None else '')
        except (OSError, ValueError):
            valid = False
            self.targetPathLabel.clear()
            set_input_error(self.directoryInput, True)
            self._show_error('Укажите корректный путь к папке')
        self.continueButton.setEnabled(valid)

    def accept(self) -> None:
        '''Создаёт проект и закрывает диалог только после успешной записи.'''
        if not self.continueButton.isEnabled():
            return
        try:
            self.project = self._store.create(self.project_directory(), self.project_name())
        except (OSError, ValueError) as error:
            self._show_error(str(error))
            return
        super().accept()

    def _show_error(self, text: str) -> None:
        '''Оставляет описание ошибки рядом с введёнными параметрами.

        Args:
            text: Причина отказа при выборе пути или создании проекта.
        '''
        show_feedback(self.errorLabel, text, error=True)

    def project_name(self) -> str:
        '''Возвращает название нового проекта.

        Returns:
            Название без пробелов по краям.
        '''
        return self.nameInput.text().strip()

    def project_directory(self) -> Path:
        '''Возвращает родительскую папку проекта.

        Returns:
            Абсолютный путь к выбранному каталогу.
        '''
        text = self.directoryInput.text().strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
            text = text[1:-1].strip()
        if not text or '\x00' in text:
            raise ValueError('Укажите путь к папке')
        return Path(os.path.expandvars(text)).expanduser().absolute()
