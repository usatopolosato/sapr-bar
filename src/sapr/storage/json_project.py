'''Читает и записывает переносимые проекты JSON с величинами в СИ.'''

import json
import os
from decimal import Decimal
from pathlib import Path
import tempfile

from ..domain import Bar, StructuralModel
from .formats import ProjectFormatError, _decimal, decimal_text, validate_source_model


MAX_BYTES = 8 * 1024 * 1024
BAR_FIELDS = ('L', 'A', 'E', 'sigma', 'q')


class _JsonNumber(str):
    '''Сохраняет точную запись числа, отличая числовой литерал JSON от строки.'''


def _reject_constant(value: str):
    '''Не допускает расширения NaN и Infinity ни в одном поле JSON.'''
    raise ProjectFormatError(f'JSON не допускает значение {value}')


def _object(value, fields: set[str], label: str) -> dict:
    '''Проверяет обязательные поля объекта без игнорирования лишних данных.'''
    if not isinstance(value, dict) or set(value) != fields:
        raise ProjectFormatError(f'{label} - нужны поля {", ".join(sorted(fields))}')
    return value


def _number(value, label: str) -> Decimal:
    '''Читает точное число из строки или числового литерала JSON.'''
    if not isinstance(value, str):
        raise ProjectFormatError(f'{label} - требуется десятичное число или строка с числом')
    try:
        return _decimal(value)
    except ProjectFormatError as error:
        raise ProjectFormatError(f'{label} - {error}') from error


def read_project_json(path: Path) -> StructuralModel:
    '''Читает проект без доверия к сохранённым результатам расчёта.

    Args:
        path: Файл JSON в кодировке UTF-8.

    Returns:
        Исходная модель в СИ, требующая отдельной проверки перед расчётом.

    Raises:
        ProjectFormatError: Структура, версия или значения некорректны.
        OSError: Файл недоступен.
    '''
    with path.open('rb') as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ProjectFormatError('Файл JSON превышает допустимый размер')
    try:
        data = json.loads(content.decode('utf-8-sig'), parse_float=_JsonNumber, parse_int=_JsonNumber,
                          parse_constant=_reject_constant, object_pairs_hook=_unique_fields)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ProjectFormatError(f'Не удалось прочитать JSON - {error}') from error
    data = _object(data, {'version', 'name', 'units', 'bars', 'nodes'}, 'Проект')
    if type(data['version']) is not _JsonNumber or data['version'] != '1' or data['units'] != 'SI':
        raise ProjectFormatError('Поддерживается версия 1 с единицами SI')
    if type(data['name']) is not str:
        raise ProjectFormatError('Название проекта должно быть строкой')
    if not isinstance(data['bars'], list) or not isinstance(data['nodes'], list):
        raise ProjectFormatError('Стержни и узлы должны быть массивами')
    if len(data['bars']) > 10000 or len(data['nodes']) > 10001:
        raise ProjectFormatError('Допустимо не более 10000 стержней и 10001 узла')
    expected = len(data['bars']) + 1 if data['bars'] else 0
    if len(data['nodes']) != expected:
        raise ProjectFormatError(f'JSON: число узлов {len(data["nodes"])}, требуется {expected}. '
                                 'Для непустой цепочки число узлов должно равняться числу стержней + 1; '
                                 'для пустого проекта оба массива должны быть пустыми')
    bars = []
    loads = []
    for index, record in enumerate(data['bars'], start=1):
        label = f'Стержень {index}'
        record = _object(record, set(BAR_FIELDS), label)
        bar = Bar(length_m=_number(record['L'], f'{label}, L'),
                  area_m2=_number(record['A'], f'{label}, A'),
                  modulus_pa=_number(record['E'], f'{label}, E'),
                  allowable_stress_pa=_number(record['sigma'], f'{label}, sigma'))
        bars.append(bar)
        loads.append(_number(record['q'], f'{label}, q'))
    forces = []
    supports = []
    for index, record in enumerate(data['nodes'], start=1):
        record = _object(record, {'F', 'fixed'}, f'Узел {index}')
        forces.append(_number(record['F'], f'Узел {index}, F'))
        if type(record['fixed']) is not bool:
            raise ProjectFormatError(f'Узел {index}, fixed - требуется логическое значение true или false')
        supports.append(record['fixed'])
    model = StructuralModel(tuple(bars), tuple(forces), tuple(loads), tuple(supports))
    validate_source_model(model)
    return model


def _unique_fields(pairs: list[tuple]) -> dict:
    '''Отклоняет повторяющиеся ключи, чтобы данные не заменялись незаметно.'''
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProjectFormatError(f'Повторяется поле {key}')
        result[key] = value
    return result


def write_project_json(path: Path, model: StructuralModel) -> None:
    '''Атомарно сохраняет исходные данные с названием по имени файла.

    Args:
        path: Выбранное имя файла JSON.
        model: Точные исходные величины в СИ.

    Raises:
        ProjectFormatError: Модель не представима в формате JSON.
        OSError: Не удалось записать файл.
    '''
    validate_source_model(model)
    bars = []
    for bar, load in zip(model.bars, model.distributed_loads):
        bars.append({
            'L': decimal_text(bar.length_m),
            'A': decimal_text(bar.area_m2),
            'E': decimal_text(bar.modulus_pa),
            'sigma': decimal_text(bar.allowable_stress_pa),
            'q': decimal_text(load),
        })
    data = {
        'version': 1, 'name': path.stem, 'units': 'SI', 'bars': bars,
        'nodes': [{'F': decimal_text(force), 'fixed': fixed}
                  for force, fixed in zip(model.nodal_forces, model.supports)],
    }
    content = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if len(content) > MAX_BYTES:
        raise ProjectFormatError('Файл JSON превышает допустимый размер')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
