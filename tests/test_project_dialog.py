'''Проверяет создание проекта в выбранном пользователем каталоге.'''

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QDialog

from src.sapr.storage import ProjectStore
from src.sapr.ui.project_dialog import ProjectDialog


class ProjectDialogTests(unittest.TestCase):
    '''Проверяет сохранение введённых параметров при ошибках создания.'''

    @classmethod
    def setUpClass(cls) -> None:
        '''Создаёт приложение Qt для сценариев диалога.'''
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        '''Открывает форму с временным расположением проектов.'''
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = ProjectStore()
        self.dialog = ProjectDialog(self.root, store=self.store)
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        '''Закрывает форму и освобождает временные данные.'''
        self.dialog.reject()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def test_nested_quoted_path_creates_the_previewed_folder(self) -> None:
        '''Проверяет вставку пути с кавычками и создание вложенных папок.'''
        parent = self.root / 'Учебные проекты' / 'Новая папка'
        self.dialog.directoryInput.setText(f'"{parent}"')
        self.dialog.nameInput.setText('Конструкция 1')
        target = parent / 'Конструкция 1'
        self.assertEqual(self.dialog.targetPathLabel.text(), str(target))
        self.dialog.accept()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.dialog.project.path, target.resolve())
        self.assertTrue((target / 'project.cn').is_file())
        self.assertTrue((target / 'project.ld').is_file())

    def test_existing_project_keeps_dialog_open_and_can_be_renamed(self) -> None:
        '''Проверяет исправление имени без потери введённого пути.'''
        existing = self.store.create(self.root, 'Новый проект')
        original = {file.name: file.read_bytes() for file in existing.path.iterdir()}
        self.dialog.accept()
        self.assertTrue(self.dialog.isVisible())
        self.assertIsNone(self.dialog.project)
        self.assertTrue(self.dialog.errorLabel.isVisible())
        self.assertEqual(self.dialog.directoryInput.text(), str(self.root))
        self.assertEqual(original, {file.name: file.read_bytes() for file in existing.path.iterdir()})
        self.dialog.nameInput.setText('Другой проект')
        self.dialog.accept()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.dialog.project.name, 'Другой проект')

    def test_write_error_keeps_fields_for_retry(self) -> None:
        '''Проверяет повторную попытку после отказа записи.'''
        self.dialog.nameInput.setText('Проверка записи')
        with patch.object(self.store, 'create', side_effect=PermissionError('Нет доступа к папке')):
            self.dialog.continueButton.click()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(self.dialog.nameInput.text(), 'Проверка записи')
        self.assertIn('Нет доступа', self.dialog.errorLabel.text())
        self.dialog.continueButton.click()
        self.assertIsNotNone(self.dialog.project)

    def test_parent_file_error_does_not_dismiss_dialog(self) -> None:
        '''Проверяет отказ при выборе файла вместо каталога.'''
        parent = self.root / 'Файл'
        parent.write_text('Исходное содержимое', encoding='utf-8')
        self.dialog.directoryInput.setText(str(parent))
        self.dialog.accept()
        self.assertTrue(self.dialog.isVisible())
        self.assertIsNone(self.dialog.project)
        self.assertEqual(parent.read_text(encoding='utf-8'), 'Исходное содержимое')

    def test_invalid_path_does_not_escape_text_changed_handler(self) -> None:
        '''Проверяет безопасную обработку некорректного пути во время ввода.'''
        self.dialog.directoryInput.setText('""')
        self.assertFalse(self.dialog.continueButton.isEnabled())
        self.assertTrue(self.dialog.errorLabel.isVisible())
        self.dialog.directoryInput.setText(str(self.root))
        self.assertTrue(self.dialog.continueButton.isEnabled())


if __name__ == '__main__':
    unittest.main()
