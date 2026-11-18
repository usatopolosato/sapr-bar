'''Читает и записывает переносимые проекты JSON с величинами в СИ.'''

import json
import os
from decimal import Decimal
from pathlib import Path
import tempfile

from ..domain import Bar, StructuralModel, validate_model
from .formats import ProjectFormatError, _decimal, decimal_text


MAX_BYTES = 8 * 1024 * 1024
BAR_FIELDS = ('L', 'A', 'E', 'sigma', 'q')


def _object(value, fields: set[str], label: str) -> dict:
    '''Проверяет обязательные поля объекта без игнорирования лишних данных.'''
    if not isinstance(value, dict) or set(value) != fields:
        raise ProjectFormatError(f'{label} - нужны поля {", ".join(sorted(fields))}')
    return value


def _number(value) -> Decimal:
    '''Читает точное число из строки или числового литерала JSON.'''
    if not isinstance(value, str):
        raise ProjectFormatError('Величины должны быть десятичными числами или строками')
    return _decimal(value)


def _check(model: StructuralModel) -> None:
    '''Проверяет геометрию и нагрузки, разрешая незавершённый проект без опор.'''
    issues = validate_model(model, ready=False)
    if issues:
        raise ProjectFormatError('\n'.join(issue.message for issue in issues))


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
        data = json.loads(content.decode('utf-8-sig'), parse_float=str, parse_int=str,
                          parse_constant=lambda value: value, object_pairs_hook=_unique_fields)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ProjectFormatError(f'Не удалось прочитать JSON - {error}') from error
    data = _object(data, {'version', 'name', 'units', 'bars', 'nodes'}, 'Проект')
    if data['version'] != '1' or data['units'] != 'SI':
        raise ProjectFormatError('Поддерживается версия 1 с единицами SI')
    if not isinstance(data['name'], str):
        raise ProjectFormatError('Название проекта должно быть строкой')
    if not isinstance(data['bars'], list) or not isinstance(data['nodes'], list):
        raise ProjectFormatError('Стержни и узлы должны быть массивами')
    if len(data['bars']) > 10000 or len(data['nodes']) > 10001:
        raise ProjectFormatError('Допустимо не более 10000 стержней')
    bars, loads, forces, supports = [], [], [], []
    for record in data['bars']:
        record = _object(record, set(BAR_FIELDS), 'Стержень')
        bars.append(Bar(*(_number(record[field]) for field in BAR_FIELDS[:4])))
        loads.append(_number(record['q']))
    for record in data['nodes']:
        record = _object(record, {'F', 'fixed'}, 'Узел')
        forces.append(_number(record['F']))
        supports.append(record['fixed'])
    model = StructuralModel(tuple(bars), tuple(forces), tuple(loads), tuple(supports))
    _check(model)
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
    _check(model)
    bars = []
    for bar, load in zip(model.bars, model.distributed_loads):
        values = (bar.length_m, bar.area_m2, bar.modulus_pa, bar.allowable_stress_pa, load)
        bars.append(dict(zip(BAR_FIELDS, map(decimal_text, values))))
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
