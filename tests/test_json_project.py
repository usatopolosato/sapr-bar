'''Проверяет переносимый JSON без потери точности и скрытой проверки модели.'''

from dataclasses import replace
from decimal import Decimal
import json
from unittest.mock import patch

import pytest

from src.sapr.domain import StructuralModel, demo_model
from src.sapr.storage.json_project import read_project_json, write_project_json
from src.sapr.ui.number_input import parse_number
from src.sapr.formatting import format_quantity


@pytest.mark.parametrize('text, display', [('8.00000000002', '8'), ('1.23456789', '1.234568'),
                                        ('-0.00000001', '-1e-8'), ('2e11', '2e11')])
def test_display_rounds_only_to_six_places(text, display):
    '''Убирает лишние разряды на экране, сохраняя исходное значение Decimal.'''
    value = Decimal(text)
    assert format_quantity(value, places=6) == display
    assert str(value) == str(Decimal(text))


@pytest.mark.parametrize('text, expected', [('3/5', '0.6'), ('-3 / 5', '-0.6'),
                                           ('3/-5', '-0.6'), ('1,2/0,5', '2.4'),
                                           ('3e100/6e50', '5e49')])
def test_fraction_input(text, expected):
    '''Разбирает дроби с сохранением знака, запятой и экспонентой.'''
    assert parse_number(text) == Decimal(expected)


@pytest.mark.parametrize('text', ['3/0', '0/0', '1/-0.0e9', '1/2/3', '1/', '/2', 'NaN/2', '1e9999/1'])
def test_invalid_fraction_is_rejected(text):
    '''Не допускает деление на ноль и неподдерживаемые выражения.'''
    with pytest.raises(ValueError):
        parse_number(text)


def test_repeating_fraction_uses_decimal_precision():
    '''Обрабатывает бесконечную дробь без промежуточного float.'''
    third = parse_number('1/3')
    assert len(third.as_tuple().digits) == 60
    assert str(third).startswith('0.' + '3' * 60)
    with pytest.raises(ValueError):
        parse_number('-1/3', positive=True)


def test_json_round_trip_preserves_exact_numbers_and_name(tmp_path):
    '''Сохраняет точность, знаки нагрузок и название по имени выбранного файла.'''
    model = demo_model()
    model = replace(model, bars=(replace(model.bars[0], length_m=Decimal('1.234567890123456789012345678901')),) + model.bars[1:])
    path = tmp_path / 'Точная конструкция.json'
    write_project_json(path, model)
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['name'] == path.stem
    assert 'validated' not in data
    assert data['units'] == 'SI'
    assert read_project_json(path) == model
    path.write_text(json.dumps(data, ensure_ascii=False).replace('"L": "1.234567890123456789012345678901"',
                    '"L": 1.234567890123456789012345678901'), encoding='utf-8')
    assert read_project_json(path) == model


@pytest.mark.parametrize('model', [StructuralModel(), replace(demo_model(), supports=(False,) * 4)])
def test_json_allows_unfinished_draft(tmp_path, model):
    '''Разрешает пустой проект и проект без опор до отдельной проверки.'''
    path = tmp_path / 'Черновик.json'
    write_project_json(path, model)
    assert read_project_json(path) == model


@pytest.mark.parametrize('change', [
    lambda data: data['bars'][0].update(L='-1'),
    lambda data: data['bars'][0].update(A='0'),
    lambda data: data['bars'][0].update(E='NaN'),
    lambda data: data['bars'][0].update(sigma='Infinity'),
    lambda data: data['bars'][0].update(q=True),
    lambda data: data['nodes'][0].update(fixed=1),
    lambda data: data['nodes'].pop(),
    lambda data: data.update(units='mm'),
    lambda data: data.update(validated=True),
    lambda data: data['bars'][0].update(X2=1),
])
def test_invalid_json_cannot_be_imported(tmp_path, change):
    '''Отклоняет неверные величины, размерности, состав массивов и лишние поля.'''
    path = tmp_path / 'Ошибка.json'
    write_project_json(path, demo_model())
    data = json.loads(path.read_text(encoding='utf-8'))
    change(data)
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        read_project_json(path)


def test_duplicate_fields_and_bad_encoding_are_rejected(tmp_path):
    '''Не замещает повторяющиеся свойства и не открывает повреждённую кодировку.'''
    path = tmp_path / 'Ошибка.json'
    for content in (b'{"L": 1, "L": 2}', b'\xff\xfe'):
        path.write_bytes(content)
        with pytest.raises(ValueError):
            read_project_json(path)


def test_failed_export_preserves_previous_file(tmp_path):
    '''Не повреждает старый JSON при отказе завершающей записи.'''
    path = tmp_path / 'Проект.json'
    write_project_json(path, StructuralModel())
    original = path.read_bytes()
    with patch('src.sapr.storage.json_project.os.replace', side_effect=OSError('Нет доступа')):
        with pytest.raises(OSError):
            write_project_json(path, demo_model())
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
