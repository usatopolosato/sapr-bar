'''Проверяет разметку внешних массивов и чтение прежних файлов.'''

from dataclasses import replace
from decimal import Decimal
import re

import pytest

from src.sapr.domain import Bar, StructuralModel, demo_model
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


MARKED_CN = '''CN: LECTURE AXIAL
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

MARKED_LD = '''LD: LECTURE AXIAL
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


def test_reads_existing_unmarked_sources():
    '''Сохранённые раньше CN и LD открываются без миграции.'''
    assert decode_sources(PLAIN_CN, PLAIN_LD) == demo_model()


def test_reads_independent_fixture_in_lecture_file_style():
    '''Ручной осевой пример использует настоящую разметку файлов преподавателя.'''
    expected = StructuralModel(
        bars=(Bar(Decimal('1.234'), Decimal('1e-3'), Decimal('2e11'), Decimal('1e8')),),
        nodal_forces=(Decimal('0'), Decimal('-1.2e4')),
        distributed_loads=(Decimal('2.1e3'),),
        supports=(True, False),
    )
    assert decode_sources(MARKED_CN, MARKED_LD) == expected


def test_marked_sources_contain_named_arrays_and_original_row_markers():
    '''Новые файлы имеют массивы и нумерацию в оформлении примера САПР BAR.'''
    construction, loading = encode_sources('Учебный проект', demo_model())
    assert construction.startswith('CN: Учебный проект\n')
    assert loading.startswith('LD: Учебный проект\n')
    for title in ('XR(NR,1:2)', 'XS(NS,1:3)', 'XC(NC,0:9)', 'XD(ND,0:2)', 'XM(NM,0:2)'):
        assert title in construction
    for title in ('NB(NA,0:6)', 'QR(NQR,0:3)', 'QS(NQS,0:4)', 'FT(NT,0:1)'):
        assert title in loading
    assert len(re.findall(r'^=01\s', construction, flags=re.MULTILINE)) == 3
    assert len(re.findall(r'^=01\s', loading, flags=re.MULTILINE)) == 3
    assert '*** CN: End ' in construction and '*** LD: End ' in loading
    assert decode_sources(construction, loading) == demo_model()


def test_empty_marked_sources_preserve_all_array_headers():
    '''Пустой черновик содержит структуру массивов без фиктивных строк.'''
    construction, loading = encode_sources('Пустой', StructuralModel())
    assert not re.search(r'^=', construction + loading, flags=re.MULTILINE)
    assert 'XD(ND,0:2)' in construction and 'FT(NT,0:1)' in loading
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


@pytest.mark.parametrize('change', [
    lambda text: text.replace('XR(NR,1:2)', 'XS(NS,1:3)', 1),
    lambda text: text.replace('XR(NR,1:2)', 'XR(NR,1:3)', 1),
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


def test_out_of_scope_lateral_coordinates_are_rejected():
    '''Оформление внешнего файла не разрешает неподдерживаемую плоскую схему.'''
    construction, loading = encode_sources('Поперечная координата', demo_model())
    construction = re.sub(r'(?m)^=01\s+0\s+0$', '=01 0 1', construction, count=1)
    with pytest.raises(ProjectFormatError, match='общей оси'):
        decode_sources(construction, loading)
