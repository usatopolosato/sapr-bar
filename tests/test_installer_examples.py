'''Проверяет комплект задач перед упаковкой установщика Windows.'''

from scripts import build_windows
from sapr.domain import validate_model
from sapr.storage import ProjectStore
from sapr.storage.json_project import read_project_json


def test_installer_contains_twelve_json_tasks_in_one_folder(tmp_path, monkeypatch):
    from shutil import copytree

    source = build_windows.ROOT / 'Проекты'
    copytree(source, tmp_path / 'Проекты')
    (tmp_path / 'build').mkdir()
    monkeypatch.setattr(build_windows, 'ROOT', tmp_path)
    build_windows.prepare_examples()

    packaged = tmp_path / 'build' / 'examples'
    store = ProjectStore()
    expected = {path.parent.name for path in (source / 'Единичные').glob('*/project.kpr')}
    actual = {path.stem for path in (packaged / 'JSON').glob('*.json')}
    assert actual == expected
    assert len(actual) == len(list(packaged.rglob('*.json'))) == 12
    assert not list(packaged.rglob('project.kpr'))
    assert not any(path.is_dir() for path in (packaged / 'JSON').iterdir())
    for name in actual:
        exported = read_project_json(packaged / 'JSON' / f'{name}.json')
        assert exported == store.load(source / 'Единичные' / name).model
        assert not validate_model(exported)
