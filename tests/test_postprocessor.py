'''Сверяет поля НДС с аналитическими задачами и равновесием раздаточных схем.'''

from dataclasses import replace
from decimal import Decimal as D, localcontext

import pytest

from src.sapr.domain import Bar, StructuralModel
from src.sapr.domain.postprocessor import AxialPostprocessor, BarResponse
from src.sapr.domain.processor import AxialProcessor, CalculationError
from test_processor_reference import CASES


def solve_one(force='0', q='0', supports=(True, False), allowable='1.6e8'):
    '''Создаёт контрольный стержень длиной два метра и жёсткостью EA = 2e8.'''
    bar = Bar(D('2'), D('0.001'), D('2e11'), D(allowable))
    model = StructuralModel((bar,), (D('0'), D(force)), (D(q),), supports)
    return AxialPostprocessor().analyze(AxialProcessor().solve(model))


@pytest.mark.parametrize('force', ['10000', '-10000'])
def test_end_force_closed_form(force):
    '''Проверяет постоянные N и sigma и линейное осевое перемещение.'''
    result = solve_one(force=force)
    for x in map(D, ('0', '0.125', '0.5', '1', '1.75', '2')):
        point = result.at(0, x)
        assert point.force_n == D(force)
        assert point.stress_pa == D(force) / D('0.001')
        assert point.displacement_m == D(force) * x / D('2e8')


@pytest.mark.parametrize('q', ['2000', '-2000'])
def test_uniform_load_free_end_closed_form(q):
    '''Сверяет консоль с интегралом распределённой нагрузки и деформации.'''
    result = solve_one(q=q)
    for x in map(D, ('0', '0.5', '1', '1.5', '2')):
        point = result.at(0, x)
        assert point.force_n == D(q) * (2 - x)
        assert point.displacement_m == D(q) * x * (4 - x) / D('4e8')


@pytest.mark.parametrize('q', ['2000', '-2000'])
def test_fixed_ends_have_internal_extremum(q):
    '''Находит внутреннюю параболу даже при нулевом векторе узловых перемещений.'''
    result = solve_one(q=q, supports=(True, True))
    bar = result.bars[0]
    assert result.processor.displacements == (D(0), D(0))
    assert bar.at(D(1)).displacement_m == D(q) / D('4e8')
    assert bar.at(D(0)).force_n == D(q)
    assert bar.at(D(2)).force_n == -D(q)
    assert D(1) in bar.sample_positions(1)
    minimum, maximum = bar.extrema('u')
    peak = maximum if D(q) > 0 else minimum
    assert peak.x_m == D(1)
    assert peak.displacement_m == D(q) / D('4e8')


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.name)
@pytest.mark.parametrize('scale', [('1', '1', '1', '1', '1'), ('2.1e11', '8e-4', '0.7', '12500', '2300')],
                         ids=['unit', 'si'])
def test_handout_fields_from_known_reactions(case, scale):
    '''Строит эталон N равновесием от известных реакций, а u интегрированием.'''
    with localcontext() as context:
        context.prec = 100
        modulus, area, length, force, q = map(D, scale)
        force_scale = q * length if case.distributed else force
        displacement_scale = force_scale * length / (modulus * area)
        model = StructuralModel(
            tuple(Bar(D(l) * length, D(a) * area, modulus, D('1.6e8')) for l, a in zip(case.lengths, case.areas)),
            tuple(D(f) * force_scale for f in case.forces),
            tuple(D(value) * q for value in case.loads), case.supports,
        )
        result = AxialPostprocessor().analyze(AxialProcessor().solve(model))
        reactions = tuple(D(value) * force_scale for value in case.reactions)
        axial = -reactions[0] - model.nodal_forces[0]
        for index, response in enumerate(result.bars):
            bar = response.geometry
            initial_u = D(case.displacements[index]) * displacement_scale
            load = model.distributed_loads[index]
            for fraction in map(D, ('0', '0.137', '0.5', '0.823', '1')):
                x = bar.length_m * fraction
                n = axial - load * x
                u = initial_u + (axial * x - load * x * x / 2) / (bar.modulus_pa * bar.area_m2)
                point = response.at(x)
                for actual, expected, magnitude in ((point.force_n, n, force_scale),
                                                     (point.stress_pa, n / bar.area_m2, force_scale / area),
                                                     (point.displacement_m, u, displacement_scale)):
                    assert abs(actual - expected) <= max(abs(magnitude), D('1e-100')) * D('1e-40')
            if index:
                left = result.bars[index - 1].at(result.bars[index - 1].geometry.length_m)
                right = response.at(D(0))
                assert left.displacement_m == right.displacement_m
                jump = right.force_n - left.force_n
                assert abs(jump + model.nodal_forces[index] + reactions[index]) <= force_scale * D('1e-40')
            axial -= load * bar.length_m + model.nodal_forces[index + 1] + reactions[index + 1]


def test_two_roots_and_limit_crossings_are_not_missed():
    '''Находит два нуля u, экстремум и границы превышения допуска без сетки.'''
    bar = Bar(D(4), D(1), D(1), D(1))
    response = BarResponse(0, bar, D(0), D(-2), D(3), D(3), D(-4), 60)
    assert response.critical_positions() == tuple(map(D, ('0', '1', '1.5', '2', '2.5', '3', '4')))
    assert response.extrema('u')[0].displacement_m == D(-1)
    assert response.extrema('u')[0].x_m == D(2)
    assert response.extrema('u')[1].displacement_m == D(3)
    assert response.sample_positions(1) == response.critical_positions()


def test_stress_jumps_with_area_while_force_and_displacement_are_continuous():
    '''Различает стороны стыка двух площадей без усреднения напряжения.'''
    model = StructuralModel((Bar(D(1), D(1), D(100), D(100)), Bar(D(1), D(2), D(100), D(100))),
                            (D(0), D(0), D(10)), (D(0), D(0)), (True, False, False))
    result = AxialPostprocessor().analyze(AxialProcessor().solve(model))
    left, right = result.at(0, D(1)), result.at(1, D(0))
    assert abs(left.force_n - D(10)) < D('1e-40')
    assert abs(right.force_n - D(10)) < D('1e-40')
    assert left.displacement_m == right.displacement_m
    assert abs(left.displacement_m - D('0.1')) < D('1e-40')
    assert abs(left.stress_pa - D(10)) < D('1e-40')
    assert abs(right.stress_pa - D(5)) < D('1e-40')


@pytest.mark.parametrize('allowable,status', [('9999999.999999999999999999', 'Превышение'),
                                            ('10000000', 'На пределе'), ('10000000.000000000000000001', 'В пределах допуска')])
def test_strength_uses_unrounded_values(allowable, status):
    '''Не скрывает превышение, которое исчезло бы после округления для показа.'''
    assert solve_one(force='-10000', allowable=allowable).bars[0].stress_status == status


def test_ambient_decimal_precision_does_not_affect_postprocessing():
    '''Не позволяет глобальному контексту округлить расчёт или координаты.'''
    result = solve_one(q='1234.56789123456789123456789')
    normal = result.at(0, D('0.123456789123456789'))
    expected_stress = result.bars[0].max_abs_stress_pa
    expected_ratio = result.bars[0].stress_ratio
    with localcontext() as context:
        context.prec = 6
        assert result.at(0, D('0.123456789123456789')) == normal
        response = replace(result.bars[0])
        assert response.max_abs_stress_pa == expected_stress
        assert response.stress_ratio == expected_ratio
        assert result.bars[0].sample_positions(3)[-1] == D(2)
        assert all(isinstance(x, D) for x in result.bars[0].critical_positions())


def test_zero_loads_produce_zero_fields():
    '''Корректно обрабатывает нулевые диапазоны графиков и отсутствие корней.'''
    result = solve_one()
    assert result.bars[0].critical_positions() == (D(0), D(2))
    for x in result.bars[0].sample_positions():
        point = result.at(0, x)
        assert point.force_n == point.stress_pa == point.displacement_m == D(0)
    assert result.bars[0].stress_ratio == D(0)


@pytest.mark.parametrize('x', [D('-0.001'), D('2.001'), D('NaN'), D('Infinity'), 1.0, '1'])
def test_invalid_sections_rejected(x):
    '''Отклоняет координаты вне стержня, float и неконечные значения.'''
    with pytest.raises(ValueError):
        solve_one().at(0, x)


@pytest.mark.parametrize('count', [0, -1, 1001, True, 2.5])
def test_invalid_subdivision_counts_rejected(count):
    '''Ограничивает объём табуляции положительным целым числом интервалов.'''
    with pytest.raises(ValueError):
        solve_one().bars[0].sample_positions(count)


def test_malformed_displacement_vector_rejected():
    '''Не строит поля по неполному вектору или ненулевому закреплению.'''
    source = solve_one().processor
    for vector in ((D(0),), (D(1), D(0)), (D(0), D('NaN'))):
        with pytest.raises(CalculationError):
            AxialPostprocessor().analyze(replace(source, displacements=vector))
