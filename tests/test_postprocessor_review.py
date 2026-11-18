'''Проверяет сетку сечений, точность показа и экспорт результатов.'''

from decimal import Decimal as D, localcontext
from pathlib import Path
from unittest.mock import patch
import os
import xml.etree.ElementTree as ET

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.sapr.domain import Bar, StructuralModel, validate_model
from src.sapr.domain.postprocessor import AxialPostprocessor
from src.sapr.domain.processor import AxialProcessor
from src.sapr.domain.sampling import BarSamples
from src.sapr.formatting import format_result
from src.sapr.storage import ProjectStore
from src.sapr.storage.json_project import read_project_json
from src.sapr.storage.result_report import ResultReport
from src.sapr.ui.pages.postprocessor import PostprocessorPage
from src.sapr.ui.widgets.response_plot import ResponsePlot
from src.sapr.ui.widgets.response_table import ResponseTableModel
from test_processor_reference import CASES, equilibrium_solution


@pytest.fixture(scope='module')
def app():
    '''Сохраняет приложение Qt на время проверок отображения.'''
    return QApplication.instance() or QApplication([])


def solution(*, length='2', force='0', load='2', limit='10', fixed=True, modulus='1'):
    '''Строит один стержень с явно заданными параметрами в СИ.'''
    source = StructuralModel((Bar(D(length), D(1), D(modulus), D(limit)),),
                             (D(0), D(force)), (D(load),), (True, fixed))
    return AxialPostprocessor().analyze(AxialProcessor().solve(source))


@pytest.mark.parametrize('step', ['0.3', '0.7', '1', '2', '10'])
def test_step_grid_contains_endpoint_and_analytic_extremum(app, step):
    '''Дополняет физический шаг концом стержня и вершиной параболы.'''
    result = solution()
    sample = BarSamples(result.bars[0], step=D(step))
    actual = [sample.position(row) for row in range(sample.count)]
    regular = [D(step) * i for i in range(int(D(2) / D(step)) + 1)]
    assert actual == sorted(set(regular + [D(0), D(1), D(2)]))
    table = ResponseTableModel(result, step=D(step))
    report_rows = list(ResultReport._section_rows(sample))
    assert [table.section(row).x_m for row in range(table.rowCount())] == actual
    assert [row[0] for row in report_rows] == actual
    assert table.index(0, 2).data(Qt.ItemDataRole.TextAlignmentRole) == Qt.AlignmentFlag.AlignCenter


def test_extrema_are_unique_and_sampling_rejects_excessive_density():
    '''Не дублирует постоянные функции и не создаёт чрезмерную сетку.'''
    bar = solution(load='0').bars[0]
    sample = BarSamples(bar, extrema_only=True)
    assert sample.count == 1
    assert sample.position(0) == 0
    for step in (D(0), D('-1'), D('NaN'), D('1e-1000')):
        with pytest.raises(ValueError):
            BarSamples(bar, step=step)
    with pytest.raises(IndexError):
        sample.position(1)


@pytest.mark.parametrize('value, expected', [
    ('0', '0.000000'), ('-0', '0.000000'), ('8.00000000002', '8.000000'),
    ('1e-16', '1.000000e-16'), ('-1e-16', '-1.000000e-16'),
    ('1.23456789e800', '1.234568e800'), ('1.23456789e-800', '1.234568e-800'),
])
def test_fixed_precision_is_independent_of_decimal_context(value, expected):
    '''Округляет только показ, сохраняя реальные малые величины в СИ.'''
    number = D(value)
    with localcontext() as context:
        context.prec = 3
        assert format_result(number) == expected
    assert number == D(value)


def test_real_small_displacement_survives_table_and_report(app):
    '''Сохраняет аналитически точное перемещение F L / EA = 1e-16 м.'''
    result = solution(length='1', force='1', load='0', fixed=False, modulus='1e16')
    assert result.processor.displacements == (D(0), D('1e-16'))
    table = ResponseTableModel(result, 1)
    assert table.index(table.rowCount() - 1, 4).data() == '1.000000e-16'
    text = '\n'.join(ResultReport().lines('Малое перемещение', result, 1))
    assert '1.000000e-16' in text
    assert '0.000000' in text


def test_html_marks_actual_exceedance_even_when_display_equals_limit(app, tmp_path):
    '''Выделяет превышения по точному значению, включая экстремумы и сечения.'''
    result = solution(length='1', force='10', load='0', fixed=False,
                      limit='9.999999999999999999999999999999')
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Прочность'), result.processor.model, validate=True)
    _, fingerprint = store.read_for_processor(project)
    diagram = ResponsePlot.report_svg(result)
    path = ResultReport().write(project, result, fingerprint, 2, file_format='html', diagram=diagram)
    text = path.read_text(encoding='utf-8')
    assert '<td class="exceeded">10.000000</td>' in text
    assert '<td class="exceeded">Превышение</td>' in text
    assert 'Прочность не обеспечена. Превышение в стержнях: 1' in text
    assert 'Узлы' in text and 'Реакция, Н' in text
    assert '<svg' in text and 'src=' not in text
    escaped = '\n'.join(ResultReport().html_lines('<script> &', result, 2, 6, None, False, diagram))
    assert '&lt;script&gt; &amp;' in escaped and '<script>' not in escaped
    previous = path.read_bytes()
    with pytest.raises(ValueError, match='отменён'):
        ResultReport().write(project, result, fingerprint, file_format='html', diagram=diagram, cancelled=lambda: True)
    assert path.read_bytes() == previous
    source = project.path / 'project.ld'
    source.write_bytes(source.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        ResultReport().write(project, result, fingerprint, file_format='html', diagram=diagram)
    assert path.read_bytes() == previous
    assert not list(project.path.glob('.report-*.tmp'))


def test_plot_density_and_visibility_are_independent_of_table(app):
    '''Сохраняет параболу при смене таблицы и допускает отключение всех эпюр.'''
    page = PostprocessorPage()
    page.resize(1200, 900)
    page.set_result(solution())
    page.show()
    app.processEvents()
    before = page.epures_view.grab().toImage()
    page.subdivisionsSpin.setValue(1)
    assert page.epures_view.grab().toImage() == before
    page.subdivisionsSpin.setValue(1000)
    assert page.epures_view.grab().toImage() == before
    page.viewsBar.setCurrentIndex(1)
    page.componentCombo.setCurrentIndex(2)
    page.viewsBar.setCurrentIndex(0)
    assert page.epures_view.grab().toImage() == before
    for check in (page.forceCheck, page.stressCheck, page.displacementCheck):
        check.setChecked(False)
    assert page.epures_view.components == ()
    with patch.object(page.epures_view, '_draw_component') as draw:
        page.epures_view.grab()
        draw.assert_not_called()
    page.forceCheck.setChecked(True)
    assert page.epures_view.components == ('N',)
    page.samplingCombo.setCurrentIndex(1)
    page.stepInput.setText('1/0')
    assert not page._refresh_table()
    assert page.stepInput.property('invalid')
    assert page.resultsTable.model() is None
    page.stepInput.setText('3/5')
    assert page._refresh_table()
    assert not page.stepInput.property('invalid')
    page.close()
    page.deleteLater()


def test_load_arrow_at_fixed_support_does_not_recolor_displacement(app):
    '''Сила на закреплённом конце меняет реакцию, а эпюра u остаётся прежней.'''
    view = ResponsePlot()
    view.resize(800, 520)
    view.set_components(('u',))
    view.set_result(solution(load='-2'))
    view.grab()
    plot_area = view._component_rects['u'].toAlignedRect()
    without_arrow = view.grab(plot_area).toImage()

    view.set_result(solution(load='-2', force='-1'))
    assert view.grab(plot_area).toImage() == without_arrow
    view.deleteLater()


def test_svg_contains_curved_path_and_vertical_hatching(app):
    '''Экспортирует параболу кривой и штрихует только пространство до оси.'''
    svg = ResponsePlot.report_svg(solution())
    root = ET.fromstring(svg)
    ns = {'s': 'http://www.w3.org/2000/svg'}
    assert any('C' in node.get('d', '') for node in root.findall('.//s:path', ns))
    hatch = root.findall('.//s:g[@stroke-width="0.7"]/s:polyline', ns)
    assert len(hatch) > 50
    for line in hatch:
        points = line.get('points').strip().split()
        if len(points) == 2:
            first, second = [tuple(map(float, point.split(','))) for point in points]
            assert first[0] == second[0]
            assert abs(first[1] - second[1]) <= 80


def test_labels_do_not_overlap_on_narrow_diagrams(app):
    '''Размещает экстремумы без наложений при недостатке ширины.'''
    view = ResponsePlot()
    view.set_result(solution())
    for width in (240, 450, 900):
        view.resize(width, 520)
        view.grab()
        boxes = view._label_boxes
        assert all(not box.intersects(other) for index, box in enumerate(boxes) for other in boxes[index + 1:])
    view.deleteLater()


@pytest.mark.parametrize('group, base', [('Единичные', ('1', '1', '1', '1', '1')),
                                        ('СИ', ('1', '0.001', '2e11', '10000', '1.6e8'))])
@pytest.mark.parametrize('case', CASES, ids=lambda case: case.name)
def test_json_examples_match_reference_sources_and_solutions(group, base, case):
    '''Сверяет исходные JSON с эталонными коэффициентами и независимым решением.'''
    root = Path(__file__).resolve().parents[1]
    name = f'{"Простая задача" if case.name.startswith("simple") else "Задача"} {int(case.name.rsplit("_", 1)[1]):02d}'
    model = read_project_json(root / 'Проекты JSON' / group / f'{name}.json')
    length, area, modulus, load, allowable = map(D, base)
    expected = StructuralModel(tuple(Bar(D(l) * length, D(a) * area, modulus, allowable)
                                     for l, a in zip(case.lengths, case.areas)),
                               tuple(D(f) * load for f in case.forces), tuple(D(q) * load for q in case.loads), case.supports)
    assert model == expected
    assert not validate_model(model)
    result = AxialProcessor().solve(model)
    with localcontext() as context:
        context.prec = 100
        scale = load * length / (area * modulus)
        for actual, value, exact in zip(result.displacements, case.displacements, equilibrium_solution(model)):
            assert abs(actual - D(value) * scale) < D('1e-40') * scale
            assert abs(actual - D(exact.numerator) / D(exact.denominator)) < D('1e-40') * scale
        for actual, value in zip(result.reactions, case.reactions):
            assert abs(actual - D(value) * load) < D('1e-40') * load


def test_json_control_task():
    '''Проверяет длины, площади, нагрузки и решение контрольной конструкции.'''
    root = Path(__file__).resolve().parents[1]
    files = list((root / 'Проекты JSON').rglob('*.json'))
    assert len(files) == 23
    model = read_project_json(root / 'Проекты JSON' / 'Единичные' / 'Задача КР.json')
    expected = StructuralModel(tuple(Bar(D(l), D(a), D(1), D(1)) for l, a in ((2, 1), (3, 3), (3, 2))),
                               (D(0), D(3), D(-3), D(0)), (D(-3), D(0), D(3)), (True, False, False, True))
    assert model == expected
    result = AxialProcessor().solve(model)
    assert result.displacements == (D(0), D(1), D('1.5'), D(0))
    assert result.reactions == (D('2.5'), D(0), D(0), D('-5.5'))
