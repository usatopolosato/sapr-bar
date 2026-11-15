'''Проверяет сохранность чисел и жизненный цикл файлов проекта.'''

from dataclasses import replace
from decimal import Decimal, localcontext
import json
from pathlib import Path
import re

import pytest

from src.sapr.domain import Bar, ModelValidationError, StructuralModel, demo_model, validate_model
from src.sapr.storage import ProjectFormatError, ProjectStore


def test_empty_project_and_validated_round_trip(tmp_path):
    '''Черновик становится проверенным проектом и открывается без потерь.'''
    store = ProjectStore()
    project = store.create(tmp_path, 'Балка 1')
    assert project.model == StructuralModel()
    assert not project.validated
    assert {path.suffix for path in project.path.iterdir()} == {'.cn', '.ld', '.kpr'}
    model = replace(demo_model(), supports=(False, True, False, True))
    project = store.save(project, model, validate=True)
    restored = store.load(project.project_file)
    assert restored == project
    assert restored.model.supports == (False, True, False, True)
    assert {path.suffix for path in project.path.iterdir()} == {'.cn', '.ld', '.kpr', '.cnx', '.ldx'}


def test_create_builds_missing_parent_directories(tmp_path, monkeypatch):
    '''Вложенная папка с пробелами и кириллицей создаётся по введённому пути.'''
    monkeypatch.chdir(tmp_path)
    parent = Path('Мои расчёты') / 'Учебный семестр' / 'Новая папка'
    project = ProjectStore().create(parent, 'Стержень 1')
    assert project.path.is_absolute()
    assert project.path == (tmp_path / parent / 'Стержень 1').resolve()
    assert project.project_file.is_file()
    assert ProjectStore().load(project.path) == project


@pytest.mark.parametrize('suffix', ['', 'Вложенная папка'])
def test_create_rejects_file_in_parent_path(tmp_path, suffix):
    '''Файл в родительском пути не изменяется при попытке создать проект.'''
    occupied = tmp_path / 'Занятый путь'
    occupied.write_bytes(b'keep unchanged')
    parent = occupied / suffix if suffix else occupied
    with pytest.raises(ProjectFormatError, match='заняты файлом'):
        ProjectStore().create(parent, 'Проект')
    assert occupied.read_bytes() == b'keep unchanged'
    assert list(tmp_path.iterdir()) == [occupied]


def test_failed_create_removes_only_empty_project_folder(tmp_path, monkeypatch):
    '''После сбоя записи остаются созданные родительские каталоги.'''
    store = ProjectStore()
    parent = tmp_path / 'Новые расчёты' / 'Семестр 1'

    def fail_save(*args, **kwargs):
        '''Имитирует ошибку записи до создания файлов проекта.'''
        raise OSError('Сбой записи')

    monkeypatch.setattr(store, 'save', fail_save)
    with pytest.raises(OSError, match='Сбой записи'):
        store.create(parent, 'Проект')
    assert parent.is_dir()
    assert list(parent.iterdir()) == []


def test_failed_create_preserves_nonempty_project_folder(tmp_path, monkeypatch):
    '''Появившиеся в новой папке файлы не удаляются при ошибке сохранения.'''
    store = ProjectStore()

    def fail_save(project, model):
        '''Имитирует появление постороннего файла перед ошибкой записи.'''
        (project.path / 'пользователь.txt').write_text('Сохранить', encoding='utf-8')
        raise OSError('Сбой записи')

    monkeypatch.setattr(store, 'save', fail_save)
    with pytest.raises(OSError, match='Сбой записи'):
        store.create(tmp_path, 'Проект')
    assert (tmp_path / 'Проект' / 'пользователь.txt').read_text(encoding='utf-8') == 'Сохранить'


def test_decimal_precision_survives_coordinate_serialization(tmp_path):
    '''Длины с разными порядками и завершающими нулями не округляются.'''
    store = ProjectStore()
    project = store.create(tmp_path, 'Точность')
    model = StructuralModel(
        bars=(
            Bar(Decimal('123456789012345678901234567890.123456789'), Decimal('0.00100'), Decimal('2.100e11'), Decimal('1.6e8')),
            Bar(Decimal('0.000000000000000000000000000000000123400'), Decimal('0.0020'), Decimal('2.1e11'), Decimal('1.600e8')),
        ),
        nodal_forces=(Decimal('0'), Decimal('-1.2345678901234567890123456789'), Decimal('1000.00')),
        distributed_loads=(Decimal('0'), Decimal('0.12345678901234567890123456789')),
        supports=(True, False, False),
    )
    with localcontext() as context:
        context.prec = 6
        project = store.save(project, model, validate=True)
        restored = store.load(project.path)
    assert restored.validated
    assert restored.model == model
    assert isinstance(restored.model.bars[1].length_m, Decimal)


def test_coordinates_with_hundreds_of_digits_round_trip(tmp_path):
    '''Далёкие порядки длин сохраняются в общих координатах без потерь.'''
    store = ProjectStore()
    model = demo_model()
    model = replace(model, bars=(
        replace(model.bars[0], length_m=Decimal('1e200')),
        replace(model.bars[1], length_m=Decimal('1e-100')),
        model.bars[2],
    ))
    project = store.save(store.create(tmp_path, 'Порядки'), model, validate=True)
    assert store.load(project.path) == project


def test_failed_check_keeps_draft_and_removes_stale_prepared_files(tmp_path):
    '''Ошибки модели не оставляют проверенные данные предыдущей редакции.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Проверка'), demo_model(), validate=True)
    unrelated = project.path / 'заметки.txt'
    unrelated.write_text('Сохранить', encoding='utf-8')
    invalid = replace(project.model, supports=(False,) * 4)
    with pytest.raises(ModelValidationError):
        store.save(project, invalid, validate=True)
    restored = store.load(project.path)
    assert restored.model == invalid
    assert not restored.validated
    assert not (project.path / 'project.cnx').exists()
    assert not (project.path / 'project.ldx').exists()
    assert unrelated.read_text(encoding='utf-8') == 'Сохранить'


def test_saving_valid_draft_does_not_prepare_processor_files(tmp_path):
    '''Корректные данные становятся проверенными только по явному запросу.'''
    store = ProjectStore()
    project = store.create(tmp_path, 'Черновик')
    project = store.save(project, demo_model())
    assert not project.validated
    assert {item.suffix for item in project.path.iterdir()} == {'.cn', '.ld', '.kpr'}
    project = store.save(project, project.model, validate=True)
    assert project.validated
    project = store.save(project, project.model)
    assert not store.load(project.path).validated
    assert {item.suffix for item in project.path.iterdir()} == {'.cn', '.ld', '.kpr'}


def test_external_change_invalidates_prepared_data(tmp_path):
    '''Изменение исходного файла не наследует прежний статус проверки.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Внешняя правка'), demo_model(), validate=True)
    source = project.path / 'project.ld'
    source.write_text(source.read_text(encoding='utf-8').replace('-6E+3', '-7E+3'), encoding='utf-8')
    restored = store.load(project.path)
    assert restored.model.nodal_forces[1] == Decimal('-7000')
    assert not restored.validated


def test_missing_or_tampered_prepared_data_is_not_validated(tmp_path):
    '''Повреждённый внутренний файл не объявляется готовым для расчёта.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Внутренние данные'), demo_model(), validate=True)
    derived = project.path / 'project.cnx'
    data = derived.read_text(encoding='ascii').split()
    data[0] = '42'
    derived.write_text(' '.join(data), encoding='ascii')
    assert not store.load(project.path).validated
    derived.unlink()
    assert not store.load(project.path).validated


@pytest.mark.parametrize('filename', ['project.cnx', 'project.ldx'])
def test_boolean_cannot_impersonate_integer_count(tmp_path, filename):
    '''Логическое значение не заменяет целый размер числового массива.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Типы полей'), demo_model(), validate=True)
    derived = project.path / filename
    data = derived.read_text(encoding='ascii').split()
    data[0] = 'true'
    derived.write_text(' '.join(data), encoding='ascii')
    assert not store.load(project.path).validated


def test_old_json_prepared_data_requires_a_new_check(tmp_path):
    '''Старый проект открывает исходные данные и обновляется после проверки.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Старая версия'), demo_model(), validate=True)
    manifest = json.loads(project.project_file.read_text(encoding='utf-8'))
    manifest.pop('prepared_format')
    project.project_file.write_text(json.dumps(manifest), encoding='utf-8')
    for filename in ('project.cnx', 'project.ldx'):
        (project.path / filename).write_text('{"version": 1, "units": "SI"}', encoding='utf-8')
    original = {item.name: item.read_bytes() for item in project.path.iterdir()}
    restored = store.load(project.path)
    assert restored.model == project.model
    assert not restored.validated
    assert {item.name: item.read_bytes() for item in project.path.iterdir()} == original
    checked = store.save(restored, restored.model, validate=True)
    assert store.load(checked.path).validated
    assert (checked.path / 'project.cnx').read_text(encoding='ascii').rstrip().endswith('CNX')
    assert (checked.path / 'project.ldx').read_text(encoding='ascii').rstrip().endswith('LDX')
    assert not (checked.path / 'project.mdx').exists()


def test_prepared_numeric_layout_tolerates_whitespace_and_equivalent_numbers(tmp_path):
    '''Статус проверки зависит от чисел и полей, а не от выравнивания текста.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Выравнивание'), demo_model(), validate=True)
    for filename in ('project.cnx', 'project.ldx'):
        derived = project.path / filename
        text = derived.read_text(encoding='ascii').replace('0.0000000000000000e+00', '0.0')
        derived.write_text('\n\t'.join(text.split()), encoding='ascii')
    assert store.load(project.path).validated


@pytest.mark.parametrize('name', ['..', '../outside', 'CON', 'LPT1.txt', 'bad/name', 'name.', ' name'])
def test_project_name_cannot_escape_or_use_reserved_names(tmp_path, name):
    '''Недопустимые имена отклоняются до создания папки.'''
    with pytest.raises(ProjectFormatError):
        ProjectStore().create(tmp_path, name)
    assert list(tmp_path.iterdir()) == []


def test_duplicate_project_does_not_overwrite_existing_data(tmp_path):
    '''Повторное имя не перезаписывает существующий проект.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Проект'), demo_model(), validate=True)
    original = {item.name: item.read_bytes() for item in project.path.iterdir()}
    with pytest.raises(ProjectFormatError, match='уже существует'):
        store.create(tmp_path, 'Проект')
    assert {item.name: item.read_bytes() for item in project.path.iterdir()} == original
    assert store.load(project.path) == project


def test_failed_file_replacement_rolls_back_original_project(tmp_path, monkeypatch):
    '''Ошибка записи между файлами восстанавливает исходную редакцию.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Откат'), demo_model(), validate=True)
    original = {item.name: item.read_bytes() for item in project.path.iterdir()}
    native_replace = Path.replace
    failed = False

    def failing_replace(source, target):
        '''Имитирует единственную ошибку замены файла нагрузок.'''
        nonlocal failed
        if source.name == 'project.ld' and not failed:
            failed = True
            raise OSError('Сбой записи')
        return native_replace(source, target)

    monkeypatch.setattr(Path, 'replace', failing_replace)
    with pytest.raises(OSError):
        store.save(project, replace(project.model, supports=(False, True, False, False)))
    assert {item.name: item.read_bytes() for item in project.path.iterdir()} == original
    assert store.load(project.path) == project


@pytest.mark.parametrize('value', [Decimal('NaN'), Decimal('Infinity'), Decimal('0'), Decimal('-1')])
def test_invalid_bar_values_are_diagnosed(value):
    '''Нулевые отрицательные и неконечные характеристики запрещают расчёт.'''
    model = demo_model()
    model = replace(model, bars=(replace(model.bars[0], area_m2=value), *model.bars[1:]))
    assert any(issue.field == 'area_m2' and issue.index == 0 for issue in validate_model(model))


def test_corrupt_topology_and_unknown_version_are_rejected(tmp_path):
    '''Неподдерживаемая топология и версия не загружаются молча.'''
    store = ProjectStore()
    project = store.save(store.create(tmp_path, 'Формат'), demo_model(), validate=True)
    source = project.path / 'project.cn'
    text = source.read_text(encoding='utf-8')
    boundary = text.index('XS(NS,1:3)')
    corrupted = text[:boundary] + re.sub(r'(?m)^=01\s+1\s+2\s+1$', '=01 1 3 1', text[boundary:], count=1)
    source.write_text(corrupted, encoding='utf-8')
    with pytest.raises(ProjectFormatError):
        store.load(project.path)
    project = store.save(project, demo_model(), validate=True)
    manifest = json.loads(project.project_file.read_text(encoding='utf-8'))
    manifest['version'] = 2
    project.project_file.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ProjectFormatError):
        store.load(project.path)
