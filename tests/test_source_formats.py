'''Проверяет разметку внешних массивов и чтение прежних файлов.'''

from dataclasses import replace
from decimal import Decimal, localcontext
import re

import pytest

from src.sapr.domain import Bar, StructuralModel, demo_model
from src.sapr.storage import ProjectStore
from src.sapr.storage.formats import ProjectFormatError, decode_sources, encode_sources


PLAIN_CN = '''Пример
4 3 3 0 0
0 0
2 0
5 0
6 0
1 2 1
2 3 2
3 4 3
1 2.1e11 0 0 8e-4 0 0 0 1.6e8 1.6e8
1 2.1e11 0 0 1.4e-3 0 0 0 1.6e8 1.6e8
1 2.1e11 0 0 1e-3 0 0 0 1.6e8 1.6e8
'''

PLAIN_LD = '''Пример
1 2 1 0
1 1 1 1 0 0 0
2 -6000 0 0
4 12000 0 0
2 2000 0 0 0
'''


MARKED_CN = '''CN: AXIAL MODEL
************* NR    NS    NC    ND    NM ***********************************
                2     1     1     0     0
******** XR(NR,1:2) *********************************************************
*       X1           X2                                                     *
*****************************************************************************
=01     0            0
=02     1.234        0
******** XS(NS,1:3) *********************************************************
*        I       J       Ig                                                 *
*****************************************************************************
=01      1       2        1
******** XC(NC,0:9) *********************************************************
*  *1*  E      Ro     aT       A        Iz      y-      y+     [Sp]   [Sc]  *
*****************************************************************************
=01  1  2e11    0     0       1e-3       0       0       0     1e8    1e8
******** XD(ND,0:2) *********************************************************
*    I       Kb     Ke                                                      *
*****************************************************************************

******** XM(NM,0:2) *********************************************************
*    I       M      Im                                                      *
*****************************************************************************

*** CN: End *****************************************************************
'''

MARKED_LD = '''LD: AXIAL MODEL
************* NA   NQR   NQS    NT ******************************************
                1     1     1     0
******** NB(NA,0:6) *********************************************************
*     I      K1   K2   K3         U       V       F                         *
*****************************************************************************
=01   1       1    1    1        0.0     0.0     0.0
******** QR(NQR,0:3) ********************************************************
*     I        F1       F2        M                                         *
*****************************************************************************
=01   2       -1.2e4     0        0
******** QS(NQS,0:4) ********************************************************
*     I      qx       qy       mz       T                                   *
*****************************************************************************
=01   1      2.1e3     0        0       0
******** FT(NT,0:1) *********************************************************
*     t      F(t)                                                           *
*****************************************************************************

*** LD: End *****************************************************************
'''


COMPACT_CN = '''CN: AXIAL
************* NR    NS    NC ***********************************************
                2     1     1
******** XR(NR,1:2) *********************************************************
*       X1           X2                                                     *
*****************************************************************************
=01     0            0
=02     1.234        0
******** XS(NS,1:3) *********************************************************
*        I       J       Ig                                                 *
*****************************************************************************
=01      1       2        1
******** XC(NC,0:3) *********************************************************
*       E          A         [Sp]       [Sc]                                *
*****************************************************************************
=01     2e11       1e-3       1e8        1e8

*** CN: End *****************************************************************
'''


COMPACT_LD = '''LD: AXIAL
************* NA   NQR   NQS ***********************************************
                1     1     1
******** NB(NA,0:0) *********************************************************
*     I                                                                    *
*****************************************************************************
=01   1
******** QR(NQR,0:1) ********************************************************
*     I        F                                                           *
*****************************************************************************
=01   2       -1.2e4
******** QS(NQS,0:1) ********************************************************
*     I        q                                                           *
*****************************************************************************
=01   1       2.1e3

*** LD: End *****************************************************************
'''


AXIAL_CN = '''CN: AXIAL
************* NR NS NC ******************************************************
               2  1  1
******** XR(NR,1:1) *********************************************************
*       X1                                                                  *
*****************************************************************************
=01     0
=02     1.234
******** XS(NS,1:3) *********************************************************
*       I J Ig                                                              *
*****************************************************************************
=01     1 2 1
******** XC(NC,0:3) *********************************************************
*       E A [Sp] [Sc]                                                       *
*****************************************************************************
=01     2e11 1e-3 1e8 1e8
*** CN: End *****************************************************************
'''


def test_reads_existing_unmarked_sources():
    '''Сохранённые раньше CN и LD открываются без миграции.'''
    assert decode_sources(PLAIN_CN, PLAIN_LD) == demo_model()


@pytest.mark.parametrize('construction', [MARKED_CN, COMPACT_CN, AXIAL_CN])
@pytest.mark.parametrize('loading', [MARKED_LD, COMPACT_LD])
def test_reads_independent_fixtures_in_full_and_compact_style(construction, loading):
    '''Ручные полный и сокращённый примеры задают одинаковую осевую модель.'''
    expected = StructuralModel(
        bars=(Bar(Decimal('1.234'), Decimal('1e-3'), Decimal('2e11'), Decimal('1e8')),),
        nodal_forces=(Decimal('0'), Decimal('-1.2e4')),
        distributed_loads=(Decimal('2.1e3'),),
        supports=(True, False),
    )
    assert decode_sources(construction, loading) == expected


def test_old_project_migrates_to_compact_sources_only_when_saved(tmp_path):
    '''Открывает старые исходные файлы без изменения и сокращает их при сохранении.'''
    store = ProjectStore()
    project = store.create(tmp_path, 'Миграция')
    construction = project.path / 'project.cn'
    loading = project.path / 'project.ld'
    construction.write_text(MARKED_CN, encoding='utf-8')
    loading.write_text(MARKED_LD, encoding='utf-8')
    original = (construction.read_bytes(), loading.read_bytes())
    restored = store.load(project.path)
    assert (construction.read_bytes(), loading.read_bytes()) == original
    assert restored.model.supports == (True, False)
    assert restored.model.nodal_forces == (Decimal('0'), Decimal('-1.2e4'))
    assert restored.model.distributed_loads == (Decimal('2.1e3'),)
    saved = store.save(restored, restored.model, validate=True)
    assert 'XR(NR,1:1)' in construction.read_text(encoding='utf-8')
    assert 'X2' not in construction.read_text(encoding='utf-8')
    assert 'XC(NC,0:3)' in construction.read_text(encoding='utf-8')
    assert 'QR(NQR,0:1)' in loading.read_text(encoding='utf-8')
    assert 'FT(' not in loading.read_text(encoding='utf-8')
    assert store.load(project.path) == saved
    assert saved.validated


def test_marked_sources_contain_named_arrays_and_original_row_markers():
    '''Новые файлы имеют массивы и нумерацию в оформлении примера САПР BAR.'''
    construction, loading = encode_sources('Учебный проект', demo_model())
    assert construction.startswith('CN: Учебный проект\n')
    assert loading.startswith('LD: Учебный проект\n')
    for title in ('XR(NR,1:1)', 'XS(NS,1:3)', 'XC(NC,0:3)'):
        assert title in construction
    coordinates = construction.split('XR(NR,1:1)', 1)[1].split('XS(', 1)[0]
    assert 'X2' not in construction
    assert [line.split()[1:] for line in coordinates.splitlines() if line.startswith('=')] == [['0'], ['2'], ['5'], ['6']]
    assert all(token not in construction for token in ('XD(', 'XM(', 'ND', 'NM', 'Type', 'Ro', 'aT', 'Iz', 'y-', 'y+'))
    assert construction.splitlines()[2].split() == ['4', '3', '3']
    characteristic_lines = construction.split('XC(NC,0:3)', 1)[1].splitlines()
    assert characteristic_lines[1].strip('* ').split() == ['E', 'A', '[Sp]', '[Sc]']
    assert all(len(line.split()) == 5 for line in characteristic_lines if line.startswith('='))
    for title in ('NB(NA,0:0)', 'QR(NQR,0:1)', 'QS(NQS,0:1)'):
        assert title in loading
    assert loading.splitlines()[2].split() == ['1', '2', '1']
    assert all(token not in loading for token in ('FT(', 'NT', 'K1', 'K2', 'K3', 'F1', 'F2', 'qx', 'qy', 'mz', 'F(t)'))
    for section, labels in (('NB(NA,0:0)', ['I']), ('QR(NQR,0:1)', ['I', 'F']), ('QS(NQS,0:1)', ['I', 'q'])):
        lines = loading.split(section, 1)[1].splitlines()
        assert lines[1].strip('* ').split() == labels
    assert len(re.findall(r'^=01\s', construction, flags=re.MULTILINE)) == 3
    assert len(re.findall(r'^=01\s', loading, flags=re.MULTILINE)) == 3
    assert '*** CN: End ' in construction and '*** LD: End ' in loading
    assert decode_sources(construction, loading) == demo_model()


def test_empty_marked_sources_preserve_required_array_headers():
    '''Пустой черновик содержит структуру массивов без фиктивных строк.'''
    construction, loading = encode_sources('Пустой', StructuralModel())
    assert not re.search(r'^=', construction + loading, flags=re.MULTILINE)
    assert all(title in construction for title in ('XR(NR,1:1)', 'XS(NS,1:3)', 'XC(NC,0:3)'))
    assert 'XD(' not in construction and 'XM(' not in construction
    assert all(title in loading for title in ('NB(NA,0:0)', 'QR(NQR,0:1)', 'QS(NQS,0:1)'))
    assert 'FT(' not in loading and 'NT' not in loading
    assert decode_sources(construction, loading) == StructuralModel()


def test_marked_sources_accept_original_doubled_cr_line_endings():
    '''Разделители CR CR LF из реального примера не меняют содержание.'''
    construction, loading = encode_sources('Переносы', demo_model())
    assert decode_sources(construction.replace('\n', '\r\r\n'), loading.replace('\n', '\r\r\n')) == demo_model()


def test_marked_source_does_not_round_numeric_columns():
    '''Выравнивание столбцов не меняет точные значения параметров.'''
    model = demo_model()
    model = replace(model, bars=(replace(model.bars[0], area_m2=Decimal('0.00012345678901234567890123456789')), *model.bars[1:]))
    construction, loading = encode_sources('Точность', model)
    assert '0.00012345678901234567890123456789' in construction
    assert decode_sources(construction, loading) == model


def test_compact_loading_preserves_signed_decimal_values():
    '''Сохраняет знак и все значащие цифры сил и нагрузок при малой точности контекста.'''
    model = replace(
        demo_model(),
        nodal_forces=(Decimal('0'), Decimal('-1.2345678901234567890123456789e8'), Decimal('0'), Decimal('2.1e-40')),
        distributed_loads=(Decimal('-0.12345678901234567890123456789'), Decimal('0'), Decimal('1e40')),
    )
    with localcontext() as context:
        context.prec = 6
        construction, loading = encode_sources('Точные нагрузки', model)
        restored = decode_sources(construction, loading)
    assert restored == model
    assert restored.nodal_forces[1].as_tuple() == model.nodal_forces[1].as_tuple()
    assert restored.distributed_loads[0].as_tuple() == model.distributed_loads[0].as_tuple()


@pytest.mark.parametrize('supports', [(False, False, False, False), (False, True, False, True)])
def test_compact_loading_omits_zero_loads_and_lists_only_fixed_nodes(supports):
    '''Пустые нагрузки не создают записей, а NB перечисляет только закреплённые узлы.'''
    model = replace(demo_model(), nodal_forces=(Decimal('0'),) * 4,
                    distributed_loads=(Decimal('0'),) * 3, supports=supports)
    construction, loading = encode_sources('Без нагрузок', model)
    assert loading.splitlines()[2].split() == [str(sum(supports)), '0', '0']
    records = [line.split()[1:] for line in loading.splitlines() if line.startswith('=')]
    assert records == [[str(index + 1)] for index, fixed in enumerate(supports) if fixed]
    assert decode_sources(construction, loading) == model


@pytest.mark.parametrize('change', [
    lambda text: text.replace('1     1     1', '1     1     1     0', 1),
    lambda text: text.replace('QR(NQR,0:1)', 'QR(NQR,0:3)'),
    lambda text: text.replace('=01   1\n', '=01   1 1\n', 1),
    lambda text: text.replace('=01   2       -1.2e4', '=01   2'),
    lambda text: text.replace('=01   1       2.1e3', '=01   1 2.1e3 0'),
    lambda text: text.replace('=01   1\n', '=01   0\n', 1),
    lambda text: text.replace('=01   2       -1.2e4', '=01   3 -1.2e4'),
    lambda text: text.replace('=01   1       2.1e3', '=01   2 2.1e3'),
    lambda text: text.replace('=01   2       -1.2e4', '=01   2 NaN'),
    lambda text: text.replace('*** LD: End', '******** FT(NT,0:1) ********\n*** LD: End'),
    lambda text: text.replace('LD: End', 'LD: Missing'),
])
def test_invalid_compact_loading_is_rejected(change):
    '''Проверяет размерности, номера элементов, числа и запрет смешения двух форматов LD.'''
    with pytest.raises(ProjectFormatError):
        decode_sources(COMPACT_CN, change(COMPACT_LD))


@pytest.mark.parametrize(('counts', 'old_row', 'new_rows'), [
    ('2     1     1', '=01   1\n', '=01   1\n=02   1\n'),
    ('1     2     1', '=01   2       -1.2e4', '=01   2 -1.2e4\n=02   2 5'),
    ('1     1     2', '=01   1       2.1e3', '=01   1 2.1e3\n=02   1 5'),
])
def test_duplicate_compact_loading_elements_are_rejected(counts, old_row, new_rows):
    '''Не позволяет дважды задать закрепление, узловую силу или нагрузку стержня.'''
    loading = COMPACT_LD.replace('1     1     1', counts, 1).replace(old_row, new_rows, 1)
    with pytest.raises(ProjectFormatError, match='повторяющийся'):
        decode_sources(COMPACT_CN, loading)


@pytest.mark.parametrize('change', [
    lambda text: text.replace('0.0     0.0     0.0', '1.0     0.0     0.0', 1),
    lambda text: text.replace('-1.2e4     0        0', '-1.2e4     1        0'),
    lambda text: text.replace('2.1e3     0        0       0', '2.1e3     0        0       5'),
])
def test_legacy_loading_does_not_drop_unsupported_components(change):
    '''Старый LD с заданным перемещением, поперечной силой или температурой отклоняется.'''
    with pytest.raises(ProjectFormatError):
        decode_sources(COMPACT_CN, change(MARKED_LD))


@pytest.mark.parametrize('change', [
    lambda text: text.replace('XR(NR,1:1)', 'XS(NS,1:3)', 1),
    lambda text: text.replace('XR(NR,1:1)', 'XR(NR,1:3)', 1),
    lambda text: text.replace('XR(NR,1:1)', 'XR(NR,1:2)', 1),
    lambda text: re.sub(r'(?m)^=01\s+0$', '=01 0 0', text, count=1),
    lambda text: text.replace('=01', '=02', 1),
    lambda text: re.sub(r'(?m)^=02[^\n]*\n', '', text, count=1),
    lambda text: text.replace('CN: End', 'CN: Missing'),
    lambda text: text + '=01 1 2\n',
])
def test_corrupted_array_markup_is_rejected(change):
    '''Номера строк размерности и порядок разделов проверяются при чтении.'''
    construction, loading = encode_sources('Повреждённый', demo_model())
    with pytest.raises(ProjectFormatError):
        decode_sources(change(construction), loading)


@pytest.mark.parametrize('change', [
    lambda text: text.replace('2     1     1', '2     1     1     0     0', 1),
    lambda text: text.replace('2     1     1', '2     1     2', 1),
    lambda text: text.replace('XC(NC,0:3)', 'XC(NC,0:9)'),
    lambda text: text.replace('2e11       1e-3       1e8        1e8', '2e11 1e-3 1e8'),
    lambda text: text.replace('2e11       1e-3       1e8        1e8', '1 2e11 0 0 1e-3 0 0 0 1e8 1e8'),
    lambda text: text.replace('2e11       1e-3       1e8        1e8', '2e11 1e-3 1e8 2e8'),
    lambda text: text.replace('2e11       1e-3       1e8        1e8', 'NaN 1e-3 1e8 1e8'),
    lambda text: text.replace('*** CN: End', '******** XD(ND,0:2) ********\n*** CN: End'),
])
def test_inconsistent_compact_characteristics_are_rejected(change):
    '''Не допускает смешение форматов, потерю полей или неподдерживаемые допуски.'''
    with pytest.raises(ProjectFormatError):
        decode_sources(change(COMPACT_CN), MARKED_LD)


def test_legacy_full_characteristics_still_reject_unused_values():
    '''Чтение прежних проектов не теряет ненулевые неподдерживаемые свойства.'''
    construction = MARKED_CN.replace('2e11    0     0', '2e11    1     0')
    with pytest.raises(ProjectFormatError, match='Поддерживаются только'):
        decode_sources(construction, MARKED_LD)


def test_out_of_scope_lateral_coordinates_are_rejected():
    '''Оформление внешнего файла не разрешает неподдерживаемую плоскую схему.'''
    construction = re.sub(r'(?m)^=01\s+0\s+0$', '=01 0 1', COMPACT_CN, count=1)
    with pytest.raises(ProjectFormatError, match='общей оси'):
        decode_sources(construction, COMPACT_LD)
