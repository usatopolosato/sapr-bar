'''Проверяет запись отчёта, точность чисел и защиту от устаревших данных.'''

from dataclasses import replace
from decimal import Decimal as D
from unittest.mock import patch

import pytest

from src.sapr.domain import Bar, StructuralModel, demo_model
from src.sapr.domain.postprocessor import AxialPostprocessor
from src.sapr.domain.processor import AxialProcessor
from src.sapr.formatting import format_result
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


def test_report_contains_readable_tables_without_changing_source_values(checked_result):
    '''Сокращает отображение чисел, сохраняя исходники и расчётные значения.'''
    project, result, fingerprint = checked_result
    before = {name: (project.path / name).read_bytes() for name in ProjectStore.FILES}
    displacements = result.processor.displacements
    path = ResultReport().write(project, result, fingerprint, 3)
    assert path == project.path / 'project.txt'
    text = path.read_text(encoding='utf-8')
    for expected in ('Стержни', 'Узлы', 'Формулы', 'Экстремумы', 'Проверка прочности', 'Сечения',
                     'округлены только для чтения', format_result(displacements[2])):
        assert expected in text
    assert fingerprint not in text
    assert max(map(len, text.splitlines())) <= 100
    for bar in result.bars:
        assert format_result(bar.extrema('u')[1].displacement_m) in text
        assert bar.stress_status in text
    assert result.processor.displacements == displacements
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
    target = project.path / 'project.txt'
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
    target = project.path / 'project.txt'
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
    assert not (project.path / 'project.txt').exists()


def test_failed_replace_preserves_previous_report(checked_result):
    '''Удаляет временный файл при ошибке записи и сохраняет прежний отчёт.'''
    project, result, fingerprint = checked_result
    target = project.path / 'project.txt'
    target.write_text('Прежний отчёт', encoding='utf-8')
    with patch('pathlib.Path.replace', side_effect=PermissionError('Нет доступа')), pytest.raises(PermissionError):
        ResultReport().write(project, result, fingerprint)
    assert target.read_text(encoding='utf-8') == 'Прежний отчёт'
    assert not list(project.path.glob('.report-*.tmp'))


@pytest.mark.parametrize('force', ['-12', '0', '12'])
@pytest.mark.parametrize('q', ['0', '8', '-8'])
def test_extrema_include_minimum_and_maximum_for_every_quantity(force, q):
    '''Даже постоянная величина имеет отдельные строки минимума и максимума.'''
    model = StructuralModel(bars=(Bar(D(1), D(1), D(1), D(1)),),
                            nodal_forces=(D(0), D(force)), distributed_loads=(D(q),),
                            supports=(True, False))
    result = AxialPostprocessor().analyze(AxialProcessor().solve(model))
    tables = list(ResultReport._tables(result, 10, None, False))
    _, headers, rows, marked = next(table for table in tables if table[0].startswith('Экстремумы'))
    assert headers == ('Величина', 'Экстремум', 'x, м', 'Значение', 'Результат')
    assert len(rows) == 6
    assert marked == (3, 4)
    for index, label in enumerate(('N, Н', 'σ, Па', 'u, м')):
        minimum, maximum = rows[2 * index:2 * index + 2]
        assert minimum[:2] == (label, 'Минимум')
        assert maximum[:2] == (label, 'Максимум')
        assert minimum[3] <= maximum[3]
    assert rows[0][3] == D(force) + min(D(0), D(q))
    assert rows[1][3] == D(force) + max(D(0), D(q))
    if q == '0':
        assert rows[0][2:] == rows[1][2:]
        assert rows[2][2:] == rows[3][2:]
        assert rows[4][3] == min(D(0), D(force))
        assert rows[5][3] == max(D(0), D(force))
    for row in rows[2:4]:
        assert row[-1] == ('Превышение' if abs(row[3]) > D(1) else '')


@pytest.mark.parametrize('file_format', ['txt', 'html'])
def test_export_labels_both_extrema_including_coincident_values(tmp_path, file_format):
    '''В обоих форматах сохраняются все шесть строк и подсветка напряжений.'''
    model = StructuralModel(bars=(Bar(D(1), D(1), D(1), D(1)),),
                            nodal_forces=(D(0), D(-12)), distributed_loads=(D(0),),
                            supports=(True, False))
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Экстремумы'), model, validate=True)
    fingerprint = store.read_for_processor(project)[1]
    result = AxialPostprocessor().analyze(AxialProcessor().solve(model))
    path = ResultReport().write(project, result, fingerprint, file_format=file_format,
                                diagram='<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    text = path.read_text(encoding='utf-8')
    table = text.split('Экстремумы - стержень 1', 1)[1].split('Сечения - стержень 1', 1)[0]
    assert table.count('Минимум') == 3
    assert table.count('Максимум') == 3
    assert table.count('Превышение') == 2
    assert table.count('N, Н') == table.count('σ, Па') == table.count('u, м') == 2
    assert table.count('-12.000000') == 5
    if file_format == 'html':
        assert table.count('<td class="exceeded">-12.000000</td>') == 2
        assert table.count('<td class="exceeded">Превышение</td>') == 2


def test_extrema_report_keeps_internal_displacement_maximum():
    '''Координата внутреннего максимума не заменяется концом стержня.'''
    model = StructuralModel(bars=(Bar(D(1), D(1), D(1), D(1)),),
                            nodal_forces=(D(0), D(0)), distributed_loads=(D(8),),
                            supports=(True, True))
    result = AxialPostprocessor().analyze(AxialProcessor().solve(model))
    rows = next(table[2] for table in ResultReport._tables(result, 10, None, False)
                if table[0].startswith('Экстремумы'))
    assert rows[4] == ('u, м', 'Минимум', D(0), D(0), '')
    assert rows[5] == ('u, м', 'Максимум', D('0.5'), D(1), '')
