'''Проверяет числовые массивы CNX и LDX на независимых образцах.'''

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from src.sapr.domain import Bar, ModelValidationError, StructuralModel
from src.sapr.storage.processed_formats import encode_processed, processed_matches, scientific_text


REFERENCE_CNX = '''
3 2 2 0 0

1 2 3
1 2 3

0 0
1.25 0
3.75 0

1 2 1
2 3 2

1 2e11 0 0
0 0.001
0 0
0
1.5e8 1.5e8
0 0
0 0 0

1 3e11 0 0
0 0.002
0 0
0
2.4e8 2.4e8
0 0
0 0 0

CNX
'''


REFERENCE_LDX = '''
2 2 2 0

1 1 1 1 0 0 0
3 1 1 1 0 0 0

2 -1250 0 0
3 2000 0 0

1 1000 0 0 0
2 -250 0 0 0

LDX
'''


@pytest.fixture
def two_bars():
    '''Создаёт модель с разными сечениями и нагрузками обоих направлений.'''
    return StructuralModel(
        bars=(
            Bar(Decimal('1.25'), Decimal('0.001'), Decimal('2e11'), Decimal('1.5e8')),
            Bar(Decimal('2.5'), Decimal('0.002'), Decimal('3e11'), Decimal('2.4e8')),
        ),
        nodal_forces=(Decimal('0'), Decimal('-1250'), Decimal('2000')),
        distributed_loads=(Decimal('1000'), Decimal('-250')),
        supports=(True, False, True),
    )


def test_two_sections_match_independent_original_layout(two_bars):
    '''Два разных типа сечения сохраняют порядок XC11 и SC5 внутри каждого типа.'''
    for actual, expected, tag in zip(encode_processed(two_bars), (REFERENCE_CNX, REFERENCE_LDX), ('CNX', 'LDX')):
        actual_tokens = actual.split()
        expected_tokens = expected.split()
        assert actual_tokens[-1] == expected_tokens[-1] == tag
        assert [Decimal(token) for token in actual_tokens[:-1]] == [Decimal(token) for token in expected_tokens[:-1]]
        assert processed_matches(expected, actual)
        assert actual.isascii()
        assert actual.endswith(f'{tag}\n')


def test_empty_load_arrays_keep_their_zero_counts(two_bars):
    '''Нулевые воздействия не создают записей QR и QS, время не используется.'''
    model = replace(two_bars, nodal_forces=(Decimal('0'),) * 3, distributed_loads=(Decimal('0'),) * 2)
    _, loading = encode_processed(model)
    rows = [row.split() for row in loading.splitlines() if row.strip()]
    assert rows[0] == ['2', '0', '0', '0']
    assert len(rows) == 4
    assert rows[1][:4] == ['1', '1', '1', '1']
    assert rows[2][:4] == ['3', '1', '1', '1']
    assert rows[-1] == ['LDX']


def test_interior_support_retains_original_node_number(two_bars):
    '''Закрепление внутреннего узла входит в NB с исходным номером.'''
    _, loading = encode_processed(replace(two_bars, supports=(False, True, False)))
    rows = [row.split() for row in loading.splitlines() if row.strip()]
    assert rows[0] == ['1', '2', '2', '0']
    assert rows[1][:4] == ['2', '1', '1', '1']


@pytest.mark.parametrize('value', ['0', '-0', '0E-500', '-0.000'])
def test_zero_has_original_canonical_exponent(value):
    '''Любой ноль получает одинаковую мантиссу и нулевой порядок.'''
    assert scientific_text(Decimal(value)) == '0.0000000000000000e+00'


@pytest.mark.parametrize('value', [
    '1.23456789012345678901234567890123456789',
    '-123456789012345678901234567890.0123456789',
    '1e-1000',
    '1e1000',
    '0.000100000',
])
def test_scientific_values_preserve_decimal_precision(value):
    '''Разрядность сохранения не зависит от текущего контекста Decimal.'''
    with localcontext() as context:
        context.prec = 4
        encoded = scientific_text(Decimal(value))
        assert Decimal(encoded) == Decimal(value)
    mantissa, exponent = encoded.split('e')
    assert len(mantissa.split('.')[1]) >= 16
    assert exponent[0] in '+-'
    assert len(exponent) >= 3


def test_coordinate_and_load_precision_survive_low_decimal_context(two_bars):
    '''Сумма длин и нагрузки в CNX и LDX сохраняются без округления.'''
    model = replace(
        two_bars,
        bars=(
            replace(two_bars.bars[0], length_m=Decimal('12345678901234567890.123456789')),
            replace(two_bars.bars[1], length_m=Decimal('0.00000000000000123456789012345')),
        ),
        nodal_forces=(Decimal('0'), Decimal('-1.23456789012345678901234567890'), Decimal('2000')),
    )
    with localcontext() as context:
        context.prec = 4
        construction, loading = encode_processed(model)
        assert processed_matches(construction, construction)
    coordinates = construction.split()[11:17]
    assert Decimal(coordinates[4]) == Decimal('12345678901234567890.12345678900000123456789012345')
    assert Decimal(loading.split()[19]) == model.nodal_forces[1]


@pytest.mark.parametrize('kind', ['empty', 'unsupported', 'negative'])
def test_encoder_rejects_unchecked_invalid_models(two_bars, kind):
    '''Невалидная модель не получает даже текст обработанных файлов.'''
    if kind == 'empty':
        model = StructuralModel()
    elif kind == 'unsupported':
        model = replace(two_bars, supports=(False, False, False))
    else:
        model = replace(two_bars, bars=(replace(two_bars.bars[0], area_m2=Decimal('-1')), two_bars.bars[1]))
    with pytest.raises(ModelValidationError):
        encode_processed(model)


@pytest.mark.parametrize('replacement', ['true', '3.0', '3e0', 'NaN', '4'])
def test_count_field_requires_matching_integer(two_bars, replacement):
    '''Счётчик не принимает логические значения и десятичные величины.'''
    construction, _ = encode_processed(two_bars)
    tokens = construction.split()
    tokens[0] = replacement
    assert not processed_matches(' '.join(tokens), construction)


@pytest.mark.parametrize('replacement', ['Infinity', 'NaN', 'true', '1.251', '1e9999999999999999999999999999'])
def test_numeric_field_rejects_invalid_or_changed_value(two_bars, replacement):
    '''Неконечные, повреждённые и изменённые значения снимают статус проверки.'''
    construction, _ = encode_processed(two_bars)
    tokens = construction.split()
    tokens[13] = replacement
    assert not processed_matches(' '.join(tokens), construction)


@pytest.mark.parametrize('suffix', ['', 'MDX', 'CNX 0', 'cnx'])
def test_terminal_tag_and_token_count_are_checked(two_bars, suffix):
    '''Конец файла не допускает пропущенных и лишних записей.'''
    construction, _ = encode_processed(two_bars)
    damaged = ' '.join(construction.split()[:-1]) + ' ' + suffix
    assert not processed_matches(damaged, construction)
