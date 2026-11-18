'''Проверяет физический смысл и согласованность импортируемых массивов.'''

from dataclasses import replace
from decimal import Decimal as D, localcontext
import json

import pytest

from src.sapr.domain import Bar, StructuralModel, demo_model, validate_model
from src.sapr.domain.processor import AxialProcessor
from src.sapr.formatting import format_quantity
from src.sapr.storage import ProjectStore
from src.sapr.storage.formats import ProjectFormatError, decode_sources, encode_sources
from src.sapr.storage.json_project import read_project_json, write_project_json
from src.sapr.storage.processed_formats import decode_processed, encode_processed
from test_source_formats import AXIAL_CN, COMPACT_LD, MARKED_CN, MARKED_LD, PLAIN_CN, PLAIN_LD


@pytest.fixture
def json_data(tmp_path):
    path = tmp_path / 'Проверка.json'
    write_project_json(path, demo_model())
    return path, json.loads(path.read_text(encoding='utf-8'))


def read_changed(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')
    return read_project_json(path)


@pytest.mark.parametrize('field', ['L', 'A', 'E', 'sigma'])
@pytest.mark.parametrize('value', ['0', '-0', '-1', 'NaN', 'Infinity', '1e1001', None, True])
def test_json_rejects_nonphysical_bar_parameters(json_data, field, value):
    path, data = json_data
    data['bars'][1][field] = value
    with pytest.raises(ProjectFormatError, match='Стержень 2'):
        read_changed(path, data)


@pytest.mark.parametrize('amount', [-1, 1])
def test_json_node_count_must_equal_bars_plus_one(json_data, amount):
    path, data = json_data
    if amount < 0:
        data['nodes'].pop()
    else:
        data['nodes'].append({'F': '0', 'fixed': False})
    with pytest.raises(ProjectFormatError, match=r'число узлов.*числу стержней \+ 1'):
        read_changed(path, data)


@pytest.mark.parametrize('field, value', [('name', 12), ('name', True), ('name', None),
                                        ('version', '1'), ('version', 1.0), ('version', True),
                                        ('nodes', {}), ('bars', None)])
def test_json_checks_metadata_types(json_data, field, value):
    path, data = json_data
    data[field] = value
    with pytest.raises(ProjectFormatError):
        read_changed(path, data)


@pytest.mark.parametrize('group, field', [
    *((None, key) for key in ('version', 'name', 'units', 'bars', 'nodes')),
    *(('bars', key) for key in ('L', 'A', 'E', 'sigma', 'q')),
    *(('nodes', key) for key in ('F', 'fixed')),
])
def test_json_rejects_each_missing_required_field(json_data, group, field):
    path, data = json_data
    record = data if group is None else data[group][0]
    del record[field]
    with pytest.raises(ProjectFormatError, match='нужны поля'):
        read_changed(path, data)


@pytest.mark.parametrize('group', ['bars', 'nodes'])
@pytest.mark.parametrize('value', [None, False, 12, '12', [], [1, 2]])
def test_json_rejects_record_replaced_by_another_type(json_data, group, value):
    path, data = json_data
    data[group][0] = value
    with pytest.raises(ProjectFormatError, match='нужны поля'):
        read_changed(path, data)


@pytest.mark.parametrize('group, field', [('bars', 'L'), ('bars', 'A'), ('bars', 'E'),
                                       ('bars', 'sigma'), ('bars', 'q'), ('nodes', 'F')])
@pytest.mark.parametrize('value', [[], {}, 'два', '2 м'])
def test_json_rejects_wrong_type_or_text_in_each_numeric_field(json_data, group, field, value):
    path, data = json_data
    data[group][0][field] = value
    with pytest.raises(ProjectFormatError, match=f', {field}'):
        read_changed(path, data)


@pytest.mark.parametrize('text', ['', '{', '{"version": 1,}', '[1, 2]', 'null', 'true', '12',
                                '{"version": 1} extra', '{"version": 1 // comment\n}',
                                '<project version="1"/>'])
def test_json_rejects_broken_syntax_or_different_file_format(tmp_path, text):
    path = tmp_path / 'broken.json'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(ProjectFormatError):
        read_project_json(path)


@pytest.mark.parametrize('group, field', [('bars', 'A'), ('nodes', 'fixed')])
def test_json_rejects_duplicate_fields_inside_records(json_data, group, field):
    path, data = json_data
    text = json.dumps(data)
    token = f'"{field}": {json.dumps(data[group][0][field])}'
    path.write_text(text.replace(token, f'{token}, {token}', 1), encoding='utf-8')
    with pytest.raises(ProjectFormatError, match=f'Повторяется поле {field}'):
        read_project_json(path)


@pytest.mark.parametrize('value', ['true', 'false', '1', 0, 1, None])
def test_json_support_is_boolean(json_data, value):
    path, data = json_data
    data['nodes'][2]['fixed'] = value
    with pytest.raises(ProjectFormatError, match='Узел 3, fixed'):
        read_changed(path, data)


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity'])
def test_json_rejects_nonstandard_constants_even_in_name(json_data, token):
    path, data = json_data
    data['name'] = '__constant__'
    path.write_text(json.dumps(data).replace('"__constant__"', token), encoding='utf-8')
    with pytest.raises(ProjectFormatError, match='JSON не допускает'):
        read_project_json(path)


@pytest.mark.parametrize('field', ['F', 'q'])
@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', '1_000', '1e1001', None, False, [], {}])
def test_json_rejects_invalid_load_values(json_data, field, value):
    path, data = json_data
    data['nodes' if field == 'F' else 'bars'][0][field] = value
    with pytest.raises(ProjectFormatError, match=f', {field}'):
        read_changed(path, data)


@pytest.mark.parametrize('construction, loading, old, new', [
    (AXIAL_CN, COMPACT_LD, '2  1  1', '3 1 1'),
    (PLAIN_CN, PLAIN_LD, '4 3 3 0 0', '3 3 3 0 0'),
    (PLAIN_CN, PLAIN_LD, '4 3 3 0 0', '5 3 3 0 0'),
    (PLAIN_CN, PLAIN_LD, '4 3 3 0 0', '4 3 2 0 0'),
    (PLAIN_CN, PLAIN_LD, '4 3 3 0 0', '4 3 4 0 0'),
])
def test_cn_checks_node_and_material_counts(construction, loading, old, new):
    assert old in construction
    with pytest.raises(ProjectFormatError):
        decode_sources(construction.replace(old, new, 1), loading)


@pytest.mark.parametrize('construction, loading', [(AXIAL_CN, COMPACT_LD), (MARKED_CN, MARKED_LD),
                                                (PLAIN_CN, PLAIN_LD)])
@pytest.mark.parametrize('old, field', [('2e11', 'E'), ('1e-3', 'A'), ('1e8', 'Допускаемое напряжение')])
@pytest.mark.parametrize('value', ['0', '-1'])
def test_cn_rejects_nonphysical_characteristics(construction, loading, old, field, value):
    if construction == PLAIN_CN:
        old = {'2e11': '2.1e11', '1e-3': '8e-4', '1e8': '1.6e8'}[old]
    assert old in construction
    with pytest.raises(ProjectFormatError, match=f'Стержень 1 - {field} должно быть больше нуля'):
        decode_sources(construction.replace(old, value), loading)


@pytest.mark.parametrize('old, new', [('0 0\n2 0', '1 0\n2 0'), ('2 0\n5 0', '0 0\n5 0'),
                                   ('2 0\n5 0', '-1 0\n5 0'), ('2 0\n5 0', '5 0\n2 0'),
                                   ('2 0\n5 0', '2 1\n5 0'), ('1 2 1', '1 1 1'),
                                   ('1 2 1', '2 1 1'), ('1 2 1', '1 3 1'),
                                   ('2 3 2', '1 2 2'), ('1 2 1', '1 2 4')])
def test_cn_rejects_collapsed_reversed_disconnected_or_unsupported_geometry(old, new):
    with pytest.raises(ProjectFormatError):
        decode_sources(PLAIN_CN.replace(old, new, 1), PLAIN_LD)


@pytest.mark.parametrize('old, new', [('1 2 1 0', '5 2 1 0'), ('1 2 1 0', '1 5 1 0'),
                                   ('1 2 1 0', '1 2 4 0'), ('1 2 1 0', '1 2 1 1'),
                                   ('2 -6000 0 0', '0 -6000 0 0'),
                                   ('2 -6000 0 0', '5 -6000 0 0'),
                                   ('2 2000 0 0 0', '4 2000 0 0 0'),
                                   ('2 -6000 0 0', '2 NaN 0 0'),
                                   ('2 -6000 0 0', '2 -6000 1 0'),
                                   ('2 2000 0 0 0', '2 2000 0 0 1'),
                                   ('1 1 1 1 0 0 0', '1 1 1 1 1 0 0')])
def test_ld_checks_counts_references_and_axial_static_components(old, new):
    with pytest.raises(ProjectFormatError):
        decode_sources(PLAIN_CN, PLAIN_LD.replace(old, new, 1))


@pytest.mark.parametrize('old, new', [('4 3 3 0 0', '0_4 3 3 0 0'), ('4 3 3 0 0', '4.0 3 3 0 0'),
                                   ('1 2 1', '1 2e0 1'), ('2.1e11', '2.1_e11'),
                                   ('2.1e11', 'NaN'), ('2.1e11', '1e1001')])
def test_cn_requires_explicit_decimal_numbers_and_integer_indices(old, new):
    with pytest.raises(ProjectFormatError):
        decode_sources(PLAIN_CN.replace(old, new, 1), PLAIN_LD)


@pytest.mark.parametrize('field', ['length_m', 'area_m2', 'modulus_pa', 'allowable_stress_pa'])
def test_invalid_export_does_not_damage_previous_files(tmp_path, field):
    store = ProjectStore()
    model = demo_model()
    project = store.save(store.create(tmp_path, 'Защита записи'), model, validate=True)
    path = project.path / 'copy.json'
    write_project_json(path, model)
    before = {item.name: item.read_bytes() for item in project.path.iterdir()}
    invalid = replace(model, bars=(replace(model.bars[0], **{field: D(-1)}), *model.bars[1:]))
    with pytest.raises(ProjectFormatError):
        store.save(project, invalid)
    with pytest.raises(ProjectFormatError):
        write_project_json(path, invalid)
    assert {item.name: item.read_bytes() for item in project.path.iterdir()} == before


@pytest.mark.parametrize('model', [StructuralModel(), replace(demo_model(), supports=(False,) * 4)])
def test_drafts_remain_editable_but_cannot_be_calculated(tmp_path, model):
    path = tmp_path / 'draft.json'
    write_project_json(path, model)
    assert read_project_json(path) == decode_sources(*encode_sources('Черновик', model)) == model
    assert validate_model(model)
    with pytest.raises(ValueError):
        AxialProcessor().solve(model)


@pytest.mark.parametrize('forces, loads, supports', [
    ((D(0),) * 4, (D(0),) * 3, (True,) * 4),
    ((D(-10), D(-20), D(30), D(0)), (D(-2), D(0), D(3)), (True, False, True, False)),
])
def test_signed_zero_and_support_loads_are_physically_valid(tmp_path, forces, loads, supports):
    model = replace(demo_model(), nodal_forces=forces, distributed_loads=loads, supports=supports)
    path = tmp_path / 'valid.json'
    write_project_json(path, model)
    assert not validate_model(model)
    assert read_project_json(path) == decode_sources(*encode_sources('Допустимые нагрузки', model)) == model
    assert len(AxialProcessor().solve(model).displacements) == len(model.bars) + 1


def test_processed_files_require_same_coordinate_origin():
    construction, loading = encode_processed(demo_model())
    tokens = construction.split()
    tokens[3:7] = [str(D(value) + 1) for value in tokens[3:7]]
    with pytest.raises(ProjectFormatError, match='первый узел'):
        decode_processed(' '.join(tokens), loading)


@pytest.mark.parametrize('value, expected', [('1.23456789', '1.234568'), ('1.23000000', '1.23'),
                                           ('1.23456789e8', '1.234568e8'), ('-1.230000e-8', '-1.23e-8'),
                                           ('1.000000e800', '1e800'), ('1.23456789e-800', '1.234568e-800'),
                                           ('9.9999999e8', '1e9'), ('1.000001', '1.000001'),
                                           ('0', '0'), ('-0', '0')])
def test_compact_mantissa_has_six_places_without_trailing_zeros(value, expected):
    original = D(value)
    with localcontext() as context:
        context.prec = 3
        assert format_quantity(original, compact=True) == expected
    assert original.as_tuple() == D(value).as_tuple()
