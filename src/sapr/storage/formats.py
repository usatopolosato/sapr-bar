'''Преобразует осевую модель во внешние массивы CN и LD.

CN и LD содержат характеристики осевой модели, закрепления и продольные
нагрузки. Поддерживается чтение сокращённого и полного форматов массивов.
'''

from decimal import Decimal, InvalidOperation, localcontext
import re

from ..domain import Bar, StructuralModel, validate_model


NUMBER_PATTERN = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')
INTEGER_PATTERN = re.compile(r'\+?[0-9]+\Z')


class ProjectFormatError(ValueError):
    '''Сообщает о повреждённом или неподдерживаемом файле проекта.'''


def validate_source_model(model: StructuralModel) -> None:
    '''Проверяет физические параметры и размеры массивов, разрешая черновик без опор.'''
    issues = validate_model(model, ready=False)
    if issues:
        raise ProjectFormatError('\n'.join(issue.message for issue in issues))


def decimal_text(value: Decimal) -> str:
    '''Возвращает точную десятичную запись без промежуточного float.'''
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ProjectFormatError('Исходные данные должны содержать конечные Decimal')
    if abs(value.as_tuple().exponent) > 1000 or len(value.as_tuple().digits) > 4096:
        raise ProjectFormatError('Число превышает допустимую длину или диапазон записи')
    if not value:
        return '0'
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits))
        text = str(value.normalize())
    _decimal(text)
    return text


def _decimal(token: str) -> Decimal:
    '''Разбирает конечное десятичное число с защитой от чрезмерной записи.'''
    if len(token) > 4096:
        raise ProjectFormatError('Слишком длинная запись числа')
    if not NUMBER_PATTERN.fullmatch(token):
        raise ProjectFormatError(f'Некорректное число {token}. Требуется десятичная запись, например 1.25 или 2e11')
    try:
        value = Decimal(token)
    except InvalidOperation as error:
        raise ProjectFormatError(f'Некорректное число {token}') from error
    if not value.is_finite() or abs(value.as_tuple().exponent) > 1000:
        raise ProjectFormatError('Требуется конечное число с показателем от -1000 до 1000')
    return value


def _integer(token: str) -> int:
    '''Разбирает целочисленный индекс или размер массива.'''
    if len(token) > 8 or not INTEGER_PATTERN.fullmatch(token):
        raise ProjectFormatError(f'Некорректное целое число {token[:32]}')
    try:
        value = int(token)
    except ValueError as error:
        raise ProjectFormatError(f'Некорректное целое число {token}') from error
    if not 0 <= value <= 10001:
        raise ProjectFormatError('Размер массива или индекс вне допустимых границ')
    return value


def _rows(text: str, count_fields: int) -> tuple[list[int], list[list[str]]]:
    '''Читает размеченные массивы или прежнюю последовательность числовых строк.'''
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or not lines[0].strip() or len(lines[0]) > 78:
        raise ProjectFormatError('Файл должен содержать заголовок до 78 символов')
    if any(line.startswith(('*', '=')) for line in lines[1:]):
        return _marked_rows(lines, count_fields)
    counts = lines[1].split()
    if len(counts) not in (3, count_fields):
        raise ProjectFormatError('Неверная строка размеров массивов')
    rows = [line.split() for line in lines[2:]]
    return [_integer(value) for value in counts], rows


def _marked_rows(lines: list[str], count_fields: int) -> tuple[list[int], list[list[str]]]:
    '''Проверяет порядок разделов, размеры массивов и нумерацию записей.'''
    if count_fields == 5:
        kind = 'CN'
        sections = (('XR', 'NR,1:2', 0, 2), ('XS', 'NS,1:3', 1, 3),
                    ('XC', 'NC,0:9', 2, 10), ('XD', 'ND,0:2', 3, 3),
                    ('XM', 'NM,0:2', 4, 3))
    else:
        kind = 'LD'
        sections = (('NB', 'NA,0:6', 0, 7), ('QR', 'NQR,0:3', 1, 4),
                    ('QS', 'NQS,0:4', 2, 5), ('FT', 'NT,0:1', 3, 2))
    if not lines[0].startswith(f'{kind}:'):
        raise ProjectFormatError(f'Заголовок размеченного файла должен начинаться с {kind}')
    counts: list[int] | None = None
    rows: list[list[str]] = []
    section = -1
    section_rows = 0
    ended = False
    for line in lines[1:]:
        if ended:
            raise ProjectFormatError(f'После завершения файла {kind} обнаружены лишние строки')
        if line.startswith('*'):
            label = line.strip('* ').strip()
            if label == f'{kind}: End':
                if section != len(sections) - 1 or counts is None:
                    raise ProjectFormatError(f'В файле {kind} отсутствуют обязательные разделы')
                if section_rows != counts[sections[section][2]]:
                    raise ProjectFormatError(f'Число строк {sections[section][0]} не совпадает с размером массива')
                ended = True
                continue
            match = re.fullmatch(r'([A-Za-z]+)\s*\(([^)]+)\)', label)
            if match:
                next_section = section + 1
                if counts is None or next_section >= len(sections):
                    raise ProjectFormatError(f'Неверный порядок разделов файла {kind}')
                expected_name, expected_dimensions, _, _ = sections[next_section]
                dimensions = re.sub(r'\s+', '', match.group(2))
                if kind == 'CN' and len(counts) == 3 and next_section == 0 and dimensions in ('NR,1:1', 'NR,1:2'):
                    expected_dimensions = dimensions
                    sections = (('XR', dimensions, 0, int(dimensions[-1])), *sections[1:])
                if match.group(1) != expected_name or dimensions != expected_dimensions:
                    raise ProjectFormatError(f'Ожидается раздел {expected_name} с размерностью {expected_dimensions}')
                if section >= 0 and section_rows != counts[sections[section][2]]:
                    raise ProjectFormatError(f'Число строк {sections[section][0]} не совпадает с размером массива')
                section = next_section
                section_rows = 0
            elif '(' in label and label.split('(', 1)[0].strip() in {'XR', 'XS', 'XC', 'XD', 'XM', 'NB', 'QR', 'QS', 'FT'}:
                raise ProjectFormatError(f'Некорректный заголовок раздела файла {kind}')
            continue
        if counts is None:
            values = line.split()
            if len(values) not in (3, count_fields):
                raise ProjectFormatError('Неверная строка размеров массивов')
            counts = [_integer(value) for value in values]
            if kind == 'CN' and len(counts) == 3:
                sections = (('XR', 'NR,1:1', 0, 1), ('XS', 'NS,1:3', 1, 3),
                            ('XC', 'NC,0:3', 2, 4))
            elif kind == 'LD' and len(counts) == 3:
                sections = (('NB', 'NA,0:0', 0, 1), ('QR', 'NQR,0:1', 1, 2),
                            ('QS', 'NQS,0:1', 2, 2))
            continue
        if section < 0:
            raise ProjectFormatError(f'Перед данными должен быть указан раздел файла {kind}')
        match = re.fullmatch(r'=(\d+)\s+(.+)', line)
        if match is None:
            raise ProjectFormatError('Строка массива должна начинаться с номера вида =01')
        section_rows += 1
        if _integer(match.group(1)) != section_rows:
            raise ProjectFormatError(f'Нарушена последовательность номеров в разделе {sections[section][0]}')
        values = match.group(2).split()
        if len(values) != sections[section][3] or section_rows > counts[sections[section][2]]:
            raise ProjectFormatError(f'Неверное число значений в разделе {sections[section][0]}')
        rows.append(values)
    if counts is None or not ended:
        raise ProjectFormatError(f'Файл {kind} не содержит отметку завершения')
    return counts, rows


def _section_text(name: str, dimensions: str, columns: tuple[str, ...], rows: list[list[str]]) -> list[str]:
    '''Выравнивает столбцы одного именованного массива.'''
    widths = [len(label) for label in columns]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    digits = max(2, len(str(len(rows))))
    heading = '* ' + ' ' * (digits + 1) + '  '.join(
        label.rjust(width) for label, width in zip(columns, widths)
    )
    width = max(77, len(heading) + 2)
    lines = [f'******** {name}({dimensions}) '.ljust(width, '*'), heading.ljust(width - 1) + '*', '*' * width]
    for index, row in enumerate(rows, start=1):
        values = '  '.join(value.rjust(width) for value, width in zip(row, widths))
        lines.append(f'={index:0{digits}d}  {values}')
    return lines


def _source_text(kind: str, name: str, labels: tuple[str, ...], counts: tuple[int, ...], sections: tuple) -> str:
    '''Собирает внешний файл в табличном оформлении САПР BAR.'''
    widths = [max(len(label), len(str(value))) for label, value in zip(labels, counts)]
    heading = '  '.join(label.rjust(width) for label, width in zip(labels, widths))
    values = '  '.join(str(value).rjust(width) for value, width in zip(counts, widths))
    lines = [f'{kind}: {name}'[:78], f'************* {heading} '.ljust(77, '*'), ' ' * 14 + values, '']
    for section in sections:
        lines.extend(_section_text(*section))
        lines.append('')
    lines.append(f'*** {kind}: End '.ljust(77, '*'))
    return '\n'.join(lines) + '\n'


def encode_sources(name: str, model: StructuralModel) -> tuple[str, str]:
    '''Формирует текстовые массивы CN и LD в единицах СИ.

    Args:
        name: Название проекта для заголовка.
        model: Сохраняемые исходные данные.

    Returns:
        Тексты конструкции и внешних воздействий.
    '''
    validate_source_model(model)
    count = len(model.bars)
    nodes = count + 1 if count else 0
    for value in (*model.nodal_forces, *model.distributed_loads):
        decimal_text(value)
    coordinates = [[decimal_text(position)] for position in model.node_positions_m]
    topology = [[str(index + 1), str(index + 2), str(index + 1)] for index in range(count)]
    characteristics: list[list[str]] = []
    for bar in model.bars:
        modulus = decimal_text(bar.modulus_pa)
        area = decimal_text(bar.area_m2)
        stress = decimal_text(bar.allowable_stress_pa)
        characteristics.append([modulus, area, stress, stress])
    supports = [index + 1 for index, value in enumerate(model.supports) if value]
    forces = [(index + 1, value) for index, value in enumerate(model.nodal_forces) if value]
    loads = [(index + 1, value) for index, value in enumerate(model.distributed_loads) if value]
    construction = _source_text('CN', name, ('NR', 'NS', 'NC'), (nodes, count, count), (
        ('XR', 'NR,1:1', ('X1',), coordinates),
        ('XS', 'NS,1:3', ('I', 'J', 'Ig'), topology),
        ('XC', 'NC,0:3', ('E', 'A', '[Sp]', '[Sc]'), characteristics),
    ))
    loading = _source_text('LD', name, ('NA', 'NQR', 'NQS'), (len(supports), len(forces), len(loads)), (
        ('NB', 'NA,0:0', ('I',), [[str(node)] for node in supports]),
        ('QR', 'NQR,0:1', ('I', 'F'),
         [[str(node), decimal_text(force)] for node, force in forces]),
        ('QS', 'NQS,0:1', ('I', 'q'),
         [[str(bar), decimal_text(load)] for bar, load in loads]),
    ))
    return construction, loading


def decode_sources(construction: str, loading: str) -> StructuralModel:
    '''Восстанавливает осевую модель из массивов CN и LD.

    Args:
        construction: Текст файла конструкции.
        loading: Текст файла нагрузок.

    Returns:
        Физически допустимая модель, включая черновик без опор.

    Raises:
        ProjectFormatError: Формат повреждён или содержит другую постановку задачи.
    '''
    bars = _read_construction(construction)
    node_count = len(bars) + 1 if bars else 0
    forces, loads, supports = _read_loading(loading, node_count, len(bars))
    model = StructuralModel(bars, forces, loads, supports)
    validate_source_model(model)
    return model


def lengths_from_coordinates(coordinates: list[Decimal]) -> list[Decimal]:
    '''Вычитает координаты соседних узлов с точностью исходных данных.'''
    if not coordinates:
        return []
    highest_digit = max(x.adjusted() for x in coordinates)
    lowest_digit = min(x.as_tuple().exponent for x in coordinates)
    with localcontext() as context:
        context.prec = max(28, highest_digit - lowest_digit + 4)
        return [right - left for left, right in zip(coordinates, coordinates[1:])]


def _read_construction(construction: str) -> tuple[Bar, ...]:
    '''Читает координаты, связи и характеристики стержней из CN.'''
    counts, rows = _rows(construction, 5)
    compact = len(counts) == 3
    nr, ns, nc = counts[:3]
    if ns > 10000:
        raise ProjectFormatError('CN: допустимо не более 10000 стержней')
    if nr != (ns + 1 if ns else 0):
        raise ProjectFormatError(f'CN: число узлов {nr}, стержней {ns}. '
                                 'Для непустой цепочки число узлов должно равняться числу стержней + 1; '
                                 'для пустого проекта оба числа должны быть равны 0')
    if nc != ns:
        raise ProjectFormatError(f'CN: наборов характеристик {nc}, требуется {ns}, по одному на каждый стержень')
    if any(counts[3:]):
        raise ProjectFormatError('Поддерживается последовательная осевая цепочка без масс')
    if len(rows) != nr + ns + nc:
        raise ProjectFormatError('Число строк CN не совпадает с размерами массивов')
    coordinates: list[Decimal] = []
    coordinate_width = len(rows[0]) if nr else 1
    allowed_widths = (1, 2) if compact else (2,)
    for row in rows[:nr]:
        if len(row) != coordinate_width or coordinate_width not in allowed_widths:
            raise ProjectFormatError('Узлы должны лежать на общей оси x')
        if coordinate_width == 2 and _decimal(row[1]) != 0:
            raise ProjectFormatError('Узлы должны лежать на общей оси x')
        coordinates.append(_decimal(row[0]))
    if coordinates and coordinates[0] != 0:
        raise ProjectFormatError('Первый узел должен иметь координату 0')
    if any(right <= left for left, right in zip(coordinates, coordinates[1:])):
        raise ProjectFormatError('Координаты узлов должны строго возрастать. Длина стержня должна быть больше нуля')
    for index, row in enumerate(rows[nr:nr + ns]):
        if len(row) != 3 or [_integer(value) for value in row] != [index + 1, index + 2, index + 1]:
            raise ProjectFormatError('Стержни должны последовательно соединять соседние узлы')
    bars: list[Bar] = []
    lengths = lengths_from_coordinates(coordinates)
    for length, row in zip(lengths, rows[nr + ns:]):
        if len(row) != (4 if compact else 10):
            raise ProjectFormatError('Неверное число характеристик стержня')
        values = [_decimal(value) for value in row]
        if compact:
            modulus, area, tension_stress, compression_stress = values
        else:
            if values[0] != 1 or any(values[item] != 0 for item in (2, 3, 5, 6, 7)):
                raise ProjectFormatError('Поддерживаются только L A E и допускаемое напряжение')
            modulus, area = values[1], values[4]
            tension_stress, compression_stress = values[8:10]
        if tension_stress != compression_stress:
            raise ProjectFormatError('Допускаемое напряжение должно быть одинаковым при растяжении и сжатии')
        bars.append(Bar(length, area, modulus, tension_stress))
    return tuple(bars)


def _read_loading(loading: str, nr: int, ns: int) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...], tuple[bool, ...]]:
    '''Читает закрепления, узловые силы и погонные нагрузки из LD.'''
    counts, rows = _rows(loading, 4)
    compact = len(counts) == 3
    na, nqr, nqs = counts[:3]
    if na > nr or nqr > nr or nqs > ns:
        raise ProjectFormatError(f'LD: опор {na} и узловых сил {nqr} должно быть не больше числа узлов {nr}; '
                                 f'погонных нагрузок {nqs} - не больше числа стержней {ns}')
    if any(counts[3:]) or len(rows) != na + nqr + nqs:
        raise ProjectFormatError('Поддерживаются статические нагрузки с заданными размерами массивов')
    supports = [False] * nr
    for row in rows[:na]:
        if len(row) != (1 if compact else 7):
            raise ProjectFormatError('Неверное число параметров закрепления')
        if not compact and [_decimal(value) for value in row[1:]] != [1, 1, 1, 0, 0, 0]:
            raise ProjectFormatError('Поддерживаются жёсткие опоры с нулевыми перемещениями')
        index = _integer(row[0]) - 1
        if not 0 <= index < nr or supports[index]:
            raise ProjectFormatError('Неверный или повторяющийся узел опоры')
        supports[index] = True
    forces = _read_load_values(rows[na:na + nqr], nr, 2 if compact else 4, 'узловой силы')
    loads = _read_load_values(rows[na + nqr:], ns, 2 if compact else 5, 'погонной нагрузки')
    return forces, loads, tuple(supports)


def _read_load_values(rows: list[list[str]], count: int, width: int, label: str) -> tuple[Decimal, ...]:
    '''Расставляет продольные нагрузки по номерам узлов или стержней.'''
    values = [Decimal('0')] * count
    seen = set()
    for row in rows:
        if len(row) != width or any(_decimal(value) != 0 for value in row[2:]):
            raise ProjectFormatError(f'Неверные компоненты {label}')
        index = _integer(row[0]) - 1
        if not 0 <= index < count or index in seen:
            raise ProjectFormatError(f'Неверный или повторяющийся номер {label}')
        seen.add(index)
        values[index] = _decimal(row[1])
    return tuple(values)
