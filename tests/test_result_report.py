'''Проверяет запись отчёта, точность чисел и защиту от устаревших данных.'''

from dataclasses import replace
from decimal import Decimal as D
from unittest.mock import patch

import pytest

from src.sapr.domain import demo_model
from src.sapr.domain.postprocessor import AxialPostprocessor
from src.sapr.domain.processor import AxialProcessor
from src.sapr.storage import ProjectStore
from src.sapr.storage.result_report import ResultReport


@pytest.fixture
def checked_result(tmp_path):
    '''Создаёт независимые проверенные файлы и соответствующий им расчёт.'''
    store = ProjectStore()
    project = store.create(tmp_path, 'Отчёт')
    project = store.save(project, demo_model(), validate=True)
    model, fingerprint = store.read_for_processor(project)
    result = AxialPostprocessor().analyze(AxialProcessor().solve(model))
    return project, result, fingerprint


def test_report_contains_inputs_exact_values_extrema_and_fingerprint(checked_result):
    '''Сохраняет все требуемые разделы в папке проекта без округления Decimal.'''
    project, result, fingerprint = checked_result
    before = {name: (project.path / name).read_bytes() for name in ProjectStore.FILES}
    path = ResultReport().write(project, result, fingerprint, 3)
    assert path == project.path / 'project.res'
    text = path.read_text(encoding='utf-8')
    for expected in ('ИСХОДНЫЕ ДАННЫЕ', 'УЗЛОВЫЕ ПЕРЕМЕЩЕНИЯ', 'ФОРМУЛЫ', 'ЭКСТРЕМУМЫ',
                     'ПРОВЕРКА ПРОЧНОСТИ', 'ТАБЛИЦА СЕЧЕНИЙ', fingerprint, str(result.processor.displacements[2])):
        assert expected in text
    for bar in result.bars:
        assert str(bar.extrema('u')[1].displacement_m) in text
        assert bar.stress_status in text
    assert before == {name: (project.path / name).read_bytes() for name in ProjectStore.FILES}
    assert not list(project.path.glob('.report-*.tmp'))


@pytest.mark.parametrize('filename', ['project.cn', 'project.ld', 'project.cnx', 'project.ldx'])
def test_modified_files_cannot_overwrite_previous_report(checked_result, filename):
    '''Отказывает в экспорте изменённых файлов и сохраняет прежний отчёт.'''
    project, result, fingerprint = checked_result
    target = ResultReport().write(project, result, fingerprint)
    previous = target.read_bytes()
    path = project.path / filename
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        ResultReport().write(project, result, fingerprint)
    assert target.read_bytes() == previous


def test_changed_files_during_report_abort_atomic_write(checked_result):
    '''Повторно проверяет снимок непосредственно перед заменой готового файла.'''
    project, result, fingerprint = checked_result
    target = project.path / 'project.res'
    target.write_text('Предыдущий отчёт', encoding='utf-8')
    writer = ResultReport()
    original_lines = writer.lines

    def change_during_write(*args):
        '''Изменяет исходник после формирования содержимого временного файла.'''
        yield from original_lines(*args)
        path = project.path / 'project.ld'
        path.write_bytes(path.read_bytes() + b'\n')

    with patch.object(writer, 'lines', side_effect=change_during_write), pytest.raises(ValueError):
        writer.write(project, result, fingerprint)
    assert target.read_text(encoding='utf-8') == 'Предыдущий отчёт'
    assert not list(project.path.glob('.report-*.tmp'))


def test_cancelled_report_keeps_previous_file(checked_result):
    '''Прерывает запись при правках в интерфейсе, не трогая прежний отчёт.'''
    project, result, fingerprint = checked_result
    target = project.path / 'project.res'
    target.write_text('Прежний расчёт', encoding='utf-8')
    with pytest.raises(ValueError, match='отменён'):
        ResultReport().write(project, result, fingerprint, cancelled=lambda: True)
    assert target.read_text(encoding='utf-8') == 'Прежний расчёт'
    assert not list(project.path.glob('.report-*.tmp'))


def test_wrong_model_and_excessive_report_size_rejected(checked_result):
    '''Не записывает НДС другой модели или чрезмерно большую таблицу.'''
    project, result, fingerprint = checked_result
    model = result.processor.model
    other = replace(model, distributed_loads=(D(1),) + model.distributed_loads[1:])
    wrong = AxialPostprocessor().analyze(AxialProcessor().solve(other))
    with pytest.raises(ValueError, match='устарел'):
        ResultReport().write(project, wrong, fingerprint)
    with patch.object(ResultReport, 'MAX_ROWS', 3), pytest.raises(ValueError, match='разбиений'):
        ResultReport().write(project, result, fingerprint)
    assert not (project.path / 'project.res').exists()


def test_failed_replace_preserves_previous_report(checked_result):
    '''Удаляет временный файл при ошибке записи и сохраняет прежний отчёт.'''
    project, result, fingerprint = checked_result
    target = project.path / 'project.res'
    target.write_text('Прежний отчёт', encoding='utf-8')
    with patch('pathlib.Path.replace', side_effect=PermissionError('Нет доступа')), pytest.raises(PermissionError):
        ResultReport().write(project, result, fingerprint)
    assert target.read_text(encoding='utf-8') == 'Прежний отчёт'
    assert not list(project.path.glob('.report-*.tmp'))
