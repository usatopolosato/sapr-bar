'''Проверяет запись только изменённых файлов и сохранность действующей проверки.'''

from dataclasses import replace
from decimal import Decimal
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.sapr.domain import demo_model
from src.sapr.storage import ProjectFormatError, ProjectStore


def snapshot(folder):
    '''Сохраняет содержимое и даты без задержек между проверками.'''
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.iterdir()}


@pytest.mark.parametrize(('checked', 'validate'), [(False, False), (True, False), (True, True)])
def test_unchanged_save_does_not_replace_any_files(tmp_path, checked, validate):
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Без изменений'), demo_model(), validate=checked)
    before = snapshot(project.path)
    fingerprint = store.read_for_processor(project)[1] if checked else None
    with patch.object(Path, 'replace', side_effect=AssertionError('Неизменённый файл перезаписан')):
        saved = store.save(project, project.model, validate=validate)
    assert snapshot(project.path) == before
    assert saved.validated == checked
    assert store.load(saved.path) == saved
    if checked:
        assert store.read_for_processor(saved)[1] == fingerprint


def test_check_prepares_saved_draft_without_rewriting_sources(tmp_path):
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Проверка черновика'), demo_model())
    before = snapshot(project.path)
    saved = store.save(project, project.model, validate=True)
    after = snapshot(project.path)
    for name in ('project.cn', 'project.ld'):
        assert after[name] == before[name]
    assert saved.validated
    assert store.read_for_processor(saved)[0] == saved.model


@pytest.mark.parametrize('validate', [False, True])
@pytest.mark.parametrize('changed_file', ['project.cn', 'project.ld'])
def test_only_changed_source_is_replaced(tmp_path, validate, changed_file):
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Изменение'), demo_model(), validate=True)
    before = snapshot(project.path)
    model = project.model
    if changed_file == 'project.cn':
        model = replace(model, bars=(replace(model.bars[0], length_m=Decimal('7')), *model.bars[1:]))
    else:
        model = replace(model, nodal_forces=(Decimal('100'), *model.nodal_forces[1:]))
    saved = store.save(project, model, validate=validate)
    after = snapshot(project.path)
    unchanged_file = 'project.ld' if changed_file == 'project.cn' else 'project.cn'
    assert after[unchanged_file] == before[unchanged_file]
    assert after[changed_file][0] != before[changed_file][0]
    assert saved.validated == validate
    assert store.load(saved.path) == saved
    if validate:
        assert store.read_for_processor(saved)[0] == model
    else:
        assert 'project.cnx' not in after and 'project.ldx' not in after


@pytest.mark.parametrize('filename', ['project.cn', 'project.ld', 'project.cnx', 'project.ldx', 'project.kpr'])
def test_save_does_not_reuse_validation_after_external_damage(tmp_path, filename):
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Повреждение'), demo_model(), validate=True)
    (project.path / filename).write_bytes(b'broken')
    saved = store.save(project, project.model)
    assert not saved.validated
    assert not store.load(saved.path).validated
    with pytest.raises(ProjectFormatError):
        store.read_for_processor(saved)


@pytest.mark.parametrize('filename', ['project.cn', 'project.ld', 'project.cnx', 'project.ldx'])
def test_check_restores_missing_files(tmp_path, filename):
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Восстановление'), demo_model(), validate=True)
    (project.path / filename).unlink()
    before = snapshot(project.path)
    saved = store.save(project, project.model, validate=True)
    for name in ('project.cn', 'project.ld'):
        if name != filename:
            assert snapshot(project.path)[name] == before[name]
    assert store.read_for_processor(saved)[0] == project.model


@pytest.mark.parametrize('validate', [False, True])
def test_newer_source_requires_explicit_check_without_rewriting_it(tmp_path, validate):
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Даты файлов'), demo_model(), validate=True)
    source = project.path / 'project.cn'
    future = max(path.stat().st_mtime_ns for path in project.path.iterdir()) + 10_000_000_000
    os.utime(source, ns=(future, future))
    before = snapshot(project.path)
    saved = store.save(project, project.model, validate=validate)
    after = snapshot(project.path)
    for name in ('project.cn', 'project.ld'):
        assert after[name] == before[name]
    assert saved.validated == validate
    if validate:
        assert store.read_for_processor(saved)[0] == saved.model
    else:
        assert not (saved.path / 'project.cnx').exists()


def test_check_after_rename_refreshes_unchanged_prepared_data(tmp_path):
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Прежнее имя'), demo_model(), validate=True)
    before = snapshot(project.path)
    saved = store.save(replace(project, name='Новое имя'), project.model, validate=True)
    assert store.read_for_processor(saved)[0] == saved.model
    after = snapshot(project.path)
    for name in ('project.cnx', 'project.ldx'):
        assert after[name][0] == before[name][0]
