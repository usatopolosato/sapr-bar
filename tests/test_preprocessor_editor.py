'''Проверяет редактирование исходных данных без потери точности.'''

import os
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit, QMessageBox, QScrollArea

from src.sapr.domain import StructuralModel, demo_model
from src.sapr.ui.pages.preprocessor import PreprocessorPage


class PreprocessorEditorTests(unittest.TestCase):
    '''Проверяет действия пользователя и сохранение исходных Decimal.'''

    @classmethod
    def setUpClass(cls) -> None:
        '''Создаёт приложение Qt для редактора.'''
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        '''Создаёт независимый редактор с примером модели.'''
        self.page = PreprocessorPage()
        self.page.set_model(demo_model())

    def tearDown(self) -> None:
        '''Освобождает виджеты после проверки.'''
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def test_compact_display_keeps_exact_editor_and_model(self) -> None:
        '''Проверяет независимость формата отображения от исходного значения.'''
        value = '1.2345678901234567890123456789'
        self.page.lengthInput.setText(value)
        self.page.lengthInput.setModified(True)
        self.assertTrue(self.page.commit_pending_edits())
        self.page.numberFormatCombo.setCurrentIndex(1)
        self.assertEqual(self.page.barsTable.item(0, 1).text(), '1.235')
        self.assertEqual(self.page.lengthInput.text(), value)
        self.assertEqual(self.page.model.bars[0].length_m, Decimal(value))
        self.page.barsTable.item(0, 1).setText('2.9876543210987654321098765432')
        self.assertEqual(self.page.model.bars[0].length_m, Decimal('2.9876543210987654321098765432'))

    def test_add_to_empty_model_creates_two_nodes(self) -> None:
        '''Проверяет создание первого стержня и начальных нагрузок.'''
        self.page.set_model(StructuralModel())
        self.assertTrue(self.page.lengthInput.isEnabled())
        self.assertEqual(self.page.applyBarButton.text(), 'Добавить')
        for field, value in zip(self.page._bar_fields, ('2', '1e-3', '2e11', '1e8')):
            field.setText(value)
        self.page.applyBarButton.click()
        self.assertEqual(len(self.page.model.bars), 1)
        self.assertEqual(self.page.model.node_positions_m, (Decimal('0'), Decimal('2')))
        self.assertEqual(self.page.model.nodal_forces, (Decimal('0'), Decimal('0')))
        self.assertEqual(self.page.model.supports, (False, False))

    def test_empty_first_bar_form_saves_draft_and_partial_form_requires_completion(self) -> None:
        '''Отличает пустую начальную форму от незавершённого ввода стержня.'''
        self.page.set_model(StructuralModel())
        saved = []
        self.page.saveRequested.connect(lambda: saved.append(True))
        self.assertTrue(self.page.commit_pending_edits())
        self.page.saveProjectButton.click()
        self.assertEqual(saved, [True])
        self.page.lengthInput.setText('2')
        self.page.lengthInput.setModified(True)
        self.page.saveProjectButton.click()
        self.assertEqual(saved, [True])
        self.assertEqual(self.page.lengthInput.text(), '2')
        self.page.cancelBarButton.click()
        self.assertTrue(self.page.commit_pending_edits())
        self.assertEqual(self.page.lengthInput.text(), '')
        self.assertEqual(self.page.model, StructuralModel())

    def test_new_bar_action_keeps_creation_and_editing_in_one_editor(self) -> None:
        '''Переключает один редактор между новым и выбранным стержнем.'''
        original = self.page.model
        self.page.resize(1200, 800)
        self.page.show()
        self.app.processEvents()
        self.assertTrue(self.page.addBarButton.isVisible())
        self.page.addBarButton.click()
        self.assertTrue(self.page.addBarButton.isVisible())
        self.assertFalse(self.page.addBarButton.isEnabled())
        self.assertFalse(self.page.removeBarButton.isVisible())
        self.assertEqual(self.page.applyBarButton.text(), 'Добавить')
        self.assertTrue(self.page.commit_pending_edits())
        self.page.cancelBarButton.click()
        self.assertTrue(self.page.addBarButton.isVisible())
        self.assertTrue(self.page.addBarButton.isEnabled())
        self.assertTrue(self.page.removeBarButton.isVisible())
        self.assertEqual(self.page.applyBarButton.text(), 'Применить')
        self.assertEqual(self.page.model, original)

    def test_invalid_table_value_blocks_save_until_corrected(self) -> None:
        '''Не позволяет сохранить старое значение вместо ошибочного ввода.'''
        saved = []
        self.page.saveRequested.connect(lambda: saved.append(True))
        self.page.barsTable.item(0, 1).setText('nan')
        self.page.saveProjectButton.click()
        self.assertEqual(saved, [])
        self.assertEqual(self.page.barsTable.item(0, 1).text(), 'nan')
        self.assertEqual(self.page.model.bars[0].length_m, Decimal('2'))
        self.page.numberFormatCombo.setCurrentIndex(0)
        self.assertEqual(self.page.barsTable.item(0, 1).text(), 'nan')
        self.page.barsTable.item(0, 1).setText('4.25')
        self.page.saveProjectButton.click()
        self.assertEqual(saved, [True])
        self.assertEqual(self.page.model.bars[0].length_m, Decimal('4.25'))

    def test_invalid_inspector_value_preserves_selection(self) -> None:
        '''Сохраняет ошибочный ввод при попытке выбрать другой стержень.'''
        self.page.lengthInput.setText('-2')
        self.page.lengthInput.setModified(True)
        self.page._select_bar(1)
        self.assertEqual(self.page._selected_bar, 0)
        self.assertEqual(self.page.lengthInput.text(), '-2')
        self.assertFalse(self.page.commit_pending_edits())
        self.page.cancelBarButton.click()
        self.assertTrue(self.page.commit_pending_edits())

    def test_pending_load_stays_with_original_node(self) -> None:
        '''При переключении узла сохраняет силу в исходном узле.'''
        self.page.loadElementCombo.setCurrentIndex(1)
        self.page.loadValueInput.setText('-1.234567890123456789e8')
        self.page.loadValueInput.setModified(True)
        self.page.loadElementCombo.setCurrentIndex(2)
        self.assertEqual(self.page.model.nodal_forces[1], Decimal('-1.234567890123456789e8'))
        self.assertEqual(self.page.model.nodal_forces[2], Decimal('0'))
        self.assertEqual(self.page.loadValueInput.text(), '0')

    def test_load_types_and_internal_support_are_editable(self) -> None:
        '''Редактирует F и q и позволяет установить внутреннюю опору.'''
        self.page.loadKindCombo.setCurrentIndex(1)
        self.page.loadElementCombo.setCurrentIndex(0)
        self.page.loadValueInput.setText('-2500')
        self.page.applyLoadButton.click()
        self.assertEqual(self.page.model.distributed_loads[0], Decimal('-2500'))
        self.page.nodesTable.item(1, 3).setText('12500')
        self.assertEqual(self.page.model.nodal_forces[1], Decimal('12500'))
        self.page.nodesTable.item(1, 2).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(self.page.model.supports[1])
        self.page.supportNodeCombo.setCurrentIndex(len(self.page.model.supports) - 1)
        self.page.fixedSupportCheck.setChecked(True)
        self.assertTrue(self.page.model.right_support)
        self.page.removeLoadButton.click()
        self.assertEqual(self.page.model.distributed_loads[0], Decimal('0'))

    def test_remove_bar_preserves_other_loads_and_renumbers_nodes(self) -> None:
        '''Удаляет правый узел стержня и сохраняет остальные воздействия.'''
        self.page._select_bar(0)
        with patch.object(QMessageBox, 'exec', return_value=0), patch.object(
            QMessageBox, 'clickedButton', lambda box: next(
                button for button in box.buttons()
                if box.buttonRole(button) == QMessageBox.ButtonRole.DestructiveRole
            )
        ):
            self.page.removeBarButton.click()
        self.assertEqual(len(self.page.model.bars), 2)
        self.assertEqual(self.page.model.nodal_forces, (Decimal('0'), Decimal('0'), Decimal('12000')))
        self.assertEqual(self.page.model.distributed_loads, (Decimal('2000'), Decimal('0')))
        self.assertEqual(self.page.model.node_positions_m, (Decimal('0'), Decimal('3'), Decimal('4')))

    def test_boundary_conditions_select_any_node_and_sync_with_table(self) -> None:
        '''Согласует граничные условия внутреннего узла в таблице и инспекторе.'''
        self.page.supportNodeCombo.setCurrentIndex(2)
        self.assertFalse(self.page.fixedSupportCheck.isChecked())
        self.page.fixedSupportCheck.setChecked(True)
        self.assertTrue(self.page.model.supports[2])
        self.assertEqual(self.page.nodesTable.item(2, 2).checkState(), Qt.CheckState.Checked)
        self.page.nodesTable.item(2, 2).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(self.page.fixedSupportCheck.isChecked())
        self.page.nodesTable.setCurrentCell(0, 3)
        self.assertEqual(self.page.supportNodeCombo.currentData(), 0)
        self.assertTrue(self.page.fixedSupportCheck.isChecked())

    def test_boundary_editor_preserves_pending_parameters_and_disables_empty_model(self) -> None:
        '''Не теряет ввод параметров при закреплении узла и обрабатывает пустую схему.'''
        self.page.lengthInput.setText('2.34567890123456789')
        self.page.lengthInput.setModified(True)
        self.page.supportNodeCombo.setCurrentIndex(1)
        self.page.fixedSupportCheck.setChecked(True)
        self.assertTrue(self.page.lengthInput.isModified())
        self.assertTrue(self.page.commit_pending_edits())
        self.assertEqual(self.page.model.bars[0].length_m, Decimal('2.34567890123456789'))
        self.assertTrue(self.page.model.supports[1])
        self.page.set_model(StructuralModel())
        self.assertEqual(self.page.supportNodeCombo.count(), 0)
        self.assertFalse(self.page.supportNodeCombo.isEnabled())
        self.assertFalse(self.page.fixedSupportCheck.isEnabled())
        self.page.set_model(demo_model())
        self.assertEqual(self.page.supportNodeCombo.currentData(), 0)
        self.assertTrue(self.page.fixedSupportCheck.isChecked())

    def test_validation_does_not_block_draft_saving(self) -> None:
        '''Разрешает сохранять неполную модель без файлов для процессора.'''
        self.page.set_model(StructuralModel())
        saved, checked = [], []
        self.page.saveRequested.connect(lambda: saved.append(True))
        self.page.validateRequested.connect(lambda: checked.append(True))
        self.page.validateButton.click()
        self.assertEqual(checked, [])
        self.page.saveProjectButton.click()
        self.assertEqual(saved, [True])
        self.page.set_model(demo_model())
        self.page.validateButton.click()
        self.assertEqual(checked, [True])

    def test_nonfinite_and_extreme_numbers_are_rejected(self) -> None:
        '''Отсекает NaN и бесконечность до передачи модели в схему.'''
        for value in ('NaN', 'Infinity', '-Inf', '1e1001', '1e-1001', 'abc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.page._parse(value)
        self.assertEqual(self.page._parse('1,25e3'), Decimal('1250'))

    def test_narrow_layout_reflows_properties(self) -> None:
        '''Размещает инспектор снизу при уменьшении ширины.'''
        self.page.resize(1200, 800)
        self.page.show()
        self.app.processEvents()
        self.assertEqual(self.page.workspaceSplitter.orientation(), Qt.Orientation.Horizontal)
        self.page.resize(800, 800)
        for _ in range(3):
            self.app.processEvents()
        self.assertEqual(self.page.workspaceSplitter.orientation(), Qt.Orientation.Vertical)
        self.assertLessEqual(self.page.minimumSizeHint().width(), 800)

    def test_active_table_editor_commits_exact_value_and_blocks_invalid_value(self) -> None:
        '''Проверяет сохранение из активного редактора таблицы без смены фокуса.'''
        self.page.resize(1200, 800)
        self.page.show()
        self.app.processEvents()
        self.page.barsTable.setCurrentCell(0, 1)
        self.page.barsTable.editItem(self.page.barsTable.item(0, 1))
        self.app.processEvents()
        editor = QApplication.focusWidget()
        self.assertIsInstance(editor, QLineEdit)
        editor.setText('NaN')
        self.assertFalse(self.page.commit_pending_edits())
        self.assertEqual(self.page.barsTable.item(0, 1).text(), 'NaN')
        self.assertEqual(self.page.model.bars[0].length_m, Decimal('2'))
        self.app.processEvents()
        self.page.barsTable.editItem(self.page.barsTable.item(0, 1))
        self.app.processEvents()
        editor = QApplication.focusWidget()
        value = '1.2345678901234567890123456789'
        editor.setText(value)
        self.assertTrue(self.page.commit_pending_edits())
        self.assertEqual(self.page.model.bars[0].length_m, Decimal(value))

    def test_add_and_load_selection_reveal_editor_in_scroll_area(self) -> None:
        '''Прокручивает узкую страницу к выбранному редактору.'''
        container = QScrollArea()
        container.setWidgetResizable(True)
        container.setWidget(self.page)
        container.resize(800, 500)
        container.show()
        for _ in range(4):
            self.app.processEvents()
        container.verticalScrollBar().setValue(0)
        self.page.addBarButton.click()
        for _ in range(3):
            self.app.processEvents()
        self.assertGreater(container.verticalScrollBar().value(), 0)
        self.page.cancelBarButton.click()
        container.verticalScrollBar().setValue(0)
        self.page.dataTabs.setCurrentIndex(2)
        self.page.loadsTable.setCurrentCell(0, 0)
        for _ in range(3):
            self.app.processEvents()
        self.assertGreater(container.verticalScrollBar().value(), 0)
        self.assertEqual(self.page.inspectorTabs.currentIndex(), 1)
        container.takeWidget()
        container.close()
        container.deleteLater()


if __name__ == '__main__':
    unittest.main()
