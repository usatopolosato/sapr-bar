'''Проверяет файловые действия и устойчивость редактора конструкции.'''

from dataclasses import replace
from decimal import Decimal as D
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLineEdit, QMessageBox

from src.sapr.domain import Bar, StructuralModel, demo_model
from src.sapr.domain.processor import AxialProcessor
from src.sapr.storage import ProjectStore
from src.sapr.storage.formats import decode_sources, encode_sources
from src.sapr.storage.json_project import read_project_json, write_project_json
from src.sapr.ui.main_window import MainWindow, Page
from src.sapr.ui.theme import ThemeManager


@pytest.fixture(scope='module')
def app():
    '''Предоставляет приложение Qt для действий пользователя.'''
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, app):
    '''Создаёт независимое окно и пустой проект в временном каталоге.'''
    theme = ThemeManager(app, persist=False)
    result = MainWindow(theme, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    result._activate_project(ProjectStore().create(tmp_path, 'Пустой проект'))
    yield result
    result.current_project = None
    result._dirty = False
    result.close()
    result.deleteLater()
    theme.deleteLater()
    app.processEvents()


def test_import_goes_to_appdata_without_overwriting_project(window, tmp_path):
    '''Импортирует исходные данные в отдельные папки с сохранением старого проекта.'''
    path = tmp_path / 'Балка.json'
    write_project_json(path, demo_model())
    imported = tmp_path / 'AppData' / 'projects'
    with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')), \
            patch.object(MainWindow, '_import_directory', return_value=imported):
        window.import_project()
        first = window.current_project
        before = {file.name: file.read_bytes() for file in first.path.iterdir()}
        window.import_project()
    second = window.current_project
    assert first.path == imported / 'Балка'
    assert second.path == imported / 'Балка 2'
    assert second.name == first.name == 'Балка'
    assert second.model == demo_model()
    assert window.current_page is Page.PREPROCESSOR
    assert not second.validated
    assert set(before) == {'project.cn', 'project.ld', 'project.kpr'}
    assert {file.name: file.read_bytes() for file in first.path.iterdir()} == before
    assert not (second.path / 'project.cnx').exists()
    assert window.validate_project()
    assert (second.path / 'project.cnx').exists()
    assert window.project_page.processorButton.isEnabled()
    assert window._settings.value('projects/directory') == str(imported)


def test_export_names_copy_and_keeps_working_draft_dirty(window, tmp_path):
    '''Разделяет сохранение копии JSON и запись исходных файлов открытого проекта.'''
    window.preprocessor_page.applyBarButton.click()
    path = tmp_path / 'Копия.json'
    with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')) as picker:
        assert window.save_project_as()
    assert Path(picker.call_args.args[2]).parent == tmp_path
    assert json.loads(path.read_text(encoding='utf-8'))['name'] == 'Копия'
    assert read_project_json(path) == window.preprocessor_page.model
    assert window._dirty
    assert not ProjectStore().load(window.current_project.path).model.bars
    assert window.save_project()
    assert not window._dirty
    assert ProjectStore().load(window.current_project.path).model == read_project_json(path)


@pytest.mark.parametrize('action', ['open_project', 'create_project', 'import_project'])
def test_cancel_change_prevents_opening_picker(window, action):
    '''Отмена запроса сохранения останавливает выбор другого проекта.'''
    with patch.object(window, '_confirm_project_change', return_value=False) as confirmation, \
            patch.object(QFileDialog, 'getExistingDirectory') as directory, \
            patch.object(QFileDialog, 'getOpenFileName') as file:
        getattr(window, action)()
    confirmation.assert_called_once()
    directory.assert_not_called()
    file.assert_not_called()


def test_rename_updates_sources_and_invalidates_prepared_files(window):
    '''Согласует новое название в KPR и исходных файлах с повторной проверкой.'''
    project = window._store.save(window.current_project, demo_model(), validate=True)
    window._activate_project(project)
    with patch.object(QInputDialog, 'getText', return_value=('Другая конструкция', True)):
        window.rename_project()
    restored = window._store.load(project.path)
    assert restored.name == 'Другая конструкция'
    assert restored.model == demo_model()
    assert 'Другая конструкция' in (project.path / 'project.cn').read_text(encoding='utf-8')
    assert not restored.validated
    assert not (project.path / 'project.ldx').exists()


def test_loads_reappear_on_open(window):
    '''Открывает новый проект в препроцессоре с видимыми нагрузками.'''
    window.preprocessor_page.loadsVisibleButton.setChecked(False)
    window._activate_project(replace(window.current_project, model=demo_model()))
    assert window.current_page is Page.PREPROCESSOR
    assert window.preprocessor_page.loadsVisibleButton.isChecked()
    assert window.preprocessor_page.structure_view._loads_visible


def test_node_editor_keeps_value_on_its_row_while_scrolling(window, app):
    '''Не переносит ввод в другие узлы при прокрутке большой таблицы.'''
    model = StructuralModel((Bar(D(1), D(1), D(1), D(1)),) * 40,
                            tuple(D(i) for i in range(41)), (D(0),) * 40, (True,) + (False,) * 40)
    page = window.preprocessor_page
    page.set_model(model)
    window.resize(1200, 800)
    window.show()
    page.dataTabs.setCurrentIndex(1)
    app.processEvents()
    table = page.nodesTable
    table.setCurrentCell(1, 3)
    table.editItem(table.item(1, 3))
    app.processEvents()
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.setText('99.125')
    table.verticalScrollBar().setValue(table.verticalScrollBar().maximum())
    app.processEvents()
    assert page.commit_pending_edits()
    assert page.model.nodal_forces == (D(0), D('99.125')) + model.nodal_forces[2:]
    assert table.item(40, 3).data(Qt.ItemDataRole.UserRole) == '40'
    assert table.rowCount() == 41


def test_double_click_scene_does_not_open_another_window(window, app):
    '''Двойной щелчок выбирает стержень и не создаёт пустого окна.'''
    window.preprocessor_page.set_model(demo_model())
    window.show()
    app.processEvents()
    viewport = window.preprocessor_page.structure_view.viewport()
    before = set(app.topLevelWidgets())
    QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, pos=viewport.rect().center())
    app.processEvents()
    assert set(app.topLevelWidgets()) == before


def test_delete_by_number_removes_only_related_data(window):
    '''Удаляет выбранный номер, его q и правый узел с F и закреплением.'''
    model = replace(demo_model(), supports=(True, False, True, True))
    page = window.preprocessor_page
    page.set_model(model)
    with patch.object(QInputDialog, 'getInt', return_value=(2, True)), \
            patch.object(QMessageBox, 'exec', return_value=0), \
            patch.object(QMessageBox, 'clickedButton', lambda box: next(
                button for button in box.buttons() if box.buttonRole(button) == QMessageBox.ButtonRole.DestructiveRole)):
        page._remove_bar_by_number()
    assert page.model.bars == (model.bars[0], model.bars[2])
    assert page.model.nodal_forces == model.nodal_forces[:2] + model.nodal_forces[3:]
    assert page.model.distributed_loads == (model.distributed_loads[0], model.distributed_loads[2])
    assert page.model.supports == (True, False, True)


@pytest.mark.parametrize('length', ['0', '-1'])
def test_nonincreasing_coordinates_are_rejected(length):
    '''Отклоняет нулевую длину и возврат узлов назад по оси при открытии CN.'''
    model = demo_model()
    model = replace(model, bars=(model.bars[0], replace(model.bars[1], length_m=D(length)), model.bars[2]))
    with pytest.raises(ValueError, match='строго возрастать'):
        decode_sources(*encode_sources('Ошибка координат', model))


def test_control_problem_from_checked_files(tmp_path):
    '''Сверяет задачу КР с независимо полученными перемещениями и реакциями.'''
    source = Path(__file__).resolve().parents[1] / 'Проекты' / 'Единичные' / 'Задача КР'
    store = ProjectStore()
    project = store.load(source)
    assert {'.cn', '.ld', '.kpr'} <= {path.suffix for path in source.iterdir()}
    assert tuple(bar.length_m for bar in project.model.bars) == (D(2), D(3), D(3))
    assert tuple(bar.area_m2 for bar in project.model.bars) == (D(1), D(3), D(2))
    assert project.model.nodal_forces == tuple(map(D, (0, 3, -3, 0)))
    assert project.model.distributed_loads == tuple(map(D, (-3, 0, 3)))
    checked = store.create(tmp_path, 'КР', model=project.model)
    assert not checked.validated
    assert {path.suffix for path in checked.path.iterdir()} == {'.cn', '.ld', '.kpr'}
    checked = store.save(checked, project.model, validate=True)
    model, _ = store.read_for_processor(checked)
    result = AxialProcessor().solve(model)
    for actual, expected in zip(result.displacements, map(D, ('0', '1', '1.5', '0'))):
        assert abs(actual - expected) < D('1e-50')
    for actual, expected in zip(result.reactions, map(D, ('2.5', '0', '0', '-5.5'))):
        assert abs(actual - expected) < D('1e-50')
