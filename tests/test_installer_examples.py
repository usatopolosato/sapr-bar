'''Проверяет комплект задач перед упаковкой установщика Windows.'''

from scripts import build_windows
from sapr.domain import validate_model
from sapr.storage import ProjectStore
from sapr.storage.json_project import read_project_json


def test_installer_contains_all_tasks_in_both_formats(tmp_path, monkeypatch):
    from shutil import copytree

    source = build_windows.ROOT / 'Проекты'
    copytree(source, tmp_path / 'Проекты')
    (tmp_path / 'build').mkdir()
    monkeypatch.setattr(build_windows, 'ROOT', tmp_path)
    build_windows.prepare_examples()

    packaged = tmp_path / 'build' / 'examples'
    store = ProjectStore()
    expected = {path.parent.relative_to(source) for path in (source / 'Единичные').glob('*/project.kpr')}
    actual = {path.parent.relative_to(packaged) for path in packaged.rglob('project.kpr')}
    assert actual == expected
    assert len(actual) == len(list(packaged.rglob('*.json'))) == 12
    for folder in actual:
        project = store.load(packaged / folder)
        exported = read_project_json(packaged / 'JSON' / 'Единичные' / f'{folder.name}.json')
        assert exported == project.model == store.load(source / folder).model
        assert not validate_model(exported)
        assert not project.validated
        assert {path.suffix for path in project.path.iterdir()} == {'.cn', '.ld', '.kpr'}
