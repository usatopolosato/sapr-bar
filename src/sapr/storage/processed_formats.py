'''Формирует сокращённые числовые файлы CNX и LDX для осевой задачи.

Массивы следуют порядку исходных CN и LD. CNX содержит координаты,
связи стержней и четыре характеристики E A Sp Sc. LDX содержит номера
закреплённых узлов, узловые силы F и погонные нагрузки q.
'''

from decimal import Decimal, InvalidOperation
import re

from ..domain import ModelValidationError, StructuralModel, validate_model
from .formats import decimal_text


PROCESSED_FORMAT = 'sapr-bar-numeric-axial-v2'
NUMBER_PATTERN = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')
INTEGER_PATTERN = re.compile(r'[+-]?\d+\Z')
ZERO = Decimal('0')


def scientific_text(value: Decimal) -> str:
    '''Возвращает экспоненциальную запись с точным сохранением Decimal.

    Args:
        value: Конечное значение в системе СИ.

    Returns:
        Запись не менее чем с шестнадцатью дробными разрядами мантиссы.
        Более длинные значения сохраняют все значащие цифры.
    '''
    normalized = Decimal(decimal_text(value))
    if not normalized:
        return '0.0000000000000000e+00'
    precision = max(16, len(normalized.as_tuple().digits) - 1)
    mantissa, exponent = format(normalized, f'.{precision}e').split('e')
    return f'{mantissa}e{int(exponent):+03d}'


def _numbers(values: tuple[Decimal, ...]) -> str:
    '''Выравнивает строку физических величин без усечения записи.'''
    return ' '.join(scientific_text(value).rjust(24) for value in values)


def _indices(values: tuple[int, ...]) -> str:
    '''Выравнивает строку номеров элементов или размеров массивов.'''
    return ' '.join(f'{value:4d}' for value in values)


def encode_processed(model: StructuralModel) -> tuple[str, str]:
    '''Формирует проверенные числовые массивы конструкции и нагрузок.

    Args:
        model: Корректная последовательная осевая конструкция.

    Returns:
        Тексты CNX и LDX с завершающими идентификаторами формата.

    Raises:
        ModelValidationError: Исходные данные не прошли проверку.
    '''
    issues = validate_model(model)
    if issues:
        raise ModelValidationError(issues)
    count = len(model.bars)
    nodes = count + 1
    construction = ['', _indices((nodes, count, count)), '']
    construction.extend(_numbers((position, ZERO)) for position in model.node_positions_m)
    construction.append('')
    construction.extend(_indices((index + 1, index + 2, index + 1)) for index in range(count))
    construction.append('')
    construction.extend(
        _numbers((bar.modulus_pa, bar.area_m2, bar.allowable_stress_pa, bar.allowable_stress_pa))
        for bar in model.bars
    )
    construction.extend(('', 'CNX', ''))

    supports = [index + 1 for index, enabled in enumerate(model.supports) if enabled]
    forces = [(index + 1, value) for index, value in enumerate(model.nodal_forces) if value]
    loads = [(index + 1, value) for index, value in enumerate(model.distributed_loads) if value]
    loading = ['', _indices((len(supports), len(forces), len(loads))), '']
    loading.extend(_indices((node,)) for node in supports)
    loading.append('')
    loading.extend(f'{node:5d} ' + _numbers((value,)) for node, value in forces)
    loading.append('')
    loading.extend(f'{bar:5d} ' + _numbers((value,)) for bar, value in loads)
    loading.extend(('', 'LDX', ''))
    return '\n'.join(construction), '\n'.join(loading)


def processed_matches(actual: str, expected: str) -> bool:
    '''Сравнивает числовые файлы с учётом целых полей и точных величин.

    Args:
        actual: Прочитанный обработанный файл.
        expected: Ожидаемый файл для проверенных исходных данных.

    Returns:
        Истина при совпадении всех полей и завершающего идентификатора.
        Пробелы, переносы строк и эквивалентная запись Decimal несущественны.
    '''
    actual_tokens = actual.split()
    expected_tokens = expected.split()
    if len(actual_tokens) != len(expected_tokens) or not expected_tokens:
        return False
    if actual_tokens[-1] != expected_tokens[-1] or expected_tokens[-1] not in ('CNX', 'LDX'):
        return False
    for actual_token, expected_token in zip(actual_tokens[:-1], expected_tokens[:-1]):
        if len(actual_token) > 8192:
            return False
        if INTEGER_PATTERN.fullmatch(expected_token):
            if not INTEGER_PATTERN.fullmatch(actual_token) or len(actual_token) > 8:
                return False
            if int(actual_token) != int(expected_token):
                return False
        else:
            if not NUMBER_PATTERN.fullmatch(actual_token):
                return False
            try:
                actual_value = Decimal(actual_token)
            except InvalidOperation:
                return False
            if not actual_value.is_finite() or actual_value != Decimal(expected_token):
                return False
    return True
