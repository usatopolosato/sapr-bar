'''Проверяет допуск к расчёту исключительно по актуальной подготовке.'''

from dataclasses import replace
from decimal import Decimal
import json
import os

import pytest

from src.sapr.domain import demo_model
from src.sapr.storage import ProjectStore
from src.sapr.storage.formats import ProjectFormatError
from src.sapr.storage.processed_formats import decode_processed, encode_processed


@pytest.fixture
def prepared(tmp_path):
    '''Создаёт сохранённый проверенный проект.'''
    store = ProjectStore()
    project = store.create(tmp_path, 'Расчёт')
    return store, store.save(project, demo_model(), validate=True)


def test_reads_actual_processed_model_with_exact_decimals(prepared):
    '''Восстанавливает точные длины из координат подготовленных файлов.'''
    store, project = prepared
    source = demo_model()
    exact = Decimal('0.' + '123456789' * 20)
    data = replace(source, bars=(replace(source.bars[0], length_m=exact),) + source.bars[1:])
    project = store.save(project, data, validate=True)
    actual, fingerprint = store.read_for_processor(project)
    assert actual == data
    assert actual.bars[0].length_m == exact
    assert len(fingerprint) == 64


@pytest.mark.parametrize('name', ['project.cn', 'project.ld', 'project.cnx', 'project.ldx', 'project.kpr'])
def test_missing_file_blocks_calculation(prepared, name):
    '''Отклоняет неполный набор проекта.'''
    store, project = prepared
    (project.path / name).unlink()
    with pytest.raises(ProjectFormatError):
        store.read_for_processor(project)


@pytest.mark.parametrize('name', ['project.cn', 'project.ld'])
def test_source_newer_than_prepared_blocks_even_if_content_matches(prepared, name):
    '''Проверяет время изменения исходника, даже когда его числа прежние.'''
    store, project = prepared
    times = [path.stat().st_mtime_ns for path in project.path.iterdir()]
    newer = max(times) + 1000000000
    os.utime(project.path / name, ns=(newer, newer))
    with pytest.raises(ProjectFormatError, match='устарели'):
        store.read_for_processor(project)


def test_same_timestamps_are_allowed_with_verified_content(prepared):
    '''Допускает одинаковое время файлов при подтверждённом содержимом.'''
    store, project = prepared
    timestamp = (project.path / 'project.kpr').stat().st_mtime_ns
    for path in project.path.iterdir():
        os.utime(path, ns=(timestamp, timestamp))
    assert store.read_for_processor(project)[0] == project.model


@pytest.mark.parametrize('name', ['project.cn', 'project.ld', 'project.cnx', 'project.ldx'])
def test_changed_content_with_restored_timestamp_is_rejected(prepared, name):
    '''Проверяет содержимое независимо от возможности сохранить время файла.'''
    store, project = prepared
    path = project.path / name
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b'2.0000000000000000e+03', b'3.0000000000000000e+03') + b'bad')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError):
        store.read_for_processor(project)


def test_unsuccessful_check_cannot_be_used(prepared):
    '''Не принимает обработанные файлы без отметки успешной проверки.'''
    store, project = prepared
    path = project.project_file
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['validated'] = False
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ProjectFormatError):
        store.read_for_processor(project)


def test_old_loaded_model_cannot_use_another_saved_revision(prepared):
    '''Не считает новую внешнюю версию под видом модели открытого окна.'''
    store, project = prepared
    changed = replace(project.model, supports=(True, False, False, True))
    store.save(project, changed, validate=True)
    with pytest.raises(ProjectFormatError, match='заново'):
        store.read_for_processor(project)


def test_processed_decoder_rejects_extra_tokens_and_bad_topology():
    '''Проверяет размеры, завершители и связи реального входа процессора.'''
    cnx, ldx = encode_processed(demo_model())
    assert decode_processed(cnx, ldx) == demo_model()
    with pytest.raises(ProjectFormatError):
        decode_processed(cnx.replace('CNX', '7 CNX'), ldx)
    with pytest.raises(ProjectFormatError):
        decode_processed(cnx.replace('   1    2    1', '   1    3    1'), ldx)
