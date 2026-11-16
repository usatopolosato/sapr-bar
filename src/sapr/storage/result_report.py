'''Сохраняет отчёт НДС, проверяя актуальность результата перед записью.'''

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
from typing import Callable

from ..domain.postprocessor import PostprocessorResult
from ..formatting import format_quantity
from .project_store import Project, ProjectStore


class ResultReport:
    '''Формирует читаемый текстовый отчёт в СИ, округляя только представление.'''

    MAX_ROWS = 200000

    def write(self, project: Project, result: PostprocessorResult, fingerprint: str, subdivisions: int = 10,
              *, cancelled: Callable[[], bool] | None = None) -> Path:
        '''Атомарно записывает project.txt в UTF-8 для актуального расчёта.

        Args:
            project: Сохранённый и проверенный проект.
            result: Аналитические результаты постпроцессора.
            fingerprint: Отпечаток файлов, использованных процессором.
            subdivisions: Число интервалов табуляции каждого стержня.
            cancelled: Проверка отзыва результата при редактировании проекта.

        Returns:
            Путь к сформированному отчёту.

        Raises:
            ValueError: Результат устарел или объём таблицы слишком велик.
            OSError: Не удалось сохранить отчёт.
        '''
        if type(subdivisions) is not int or not 1 <= subdivisions <= 1000:
            raise ValueError('Число разбиений должно быть от 1 до 1000')
        if len(result.bars) * (subdivisions + 1) > self.MAX_ROWS:
            raise ValueError('Для отчёта уменьшите число разбиений. Допустимо до 200000 строк')
        store = ProjectStore()
        model, actual = store.read_for_processor(project)
        if not fingerprint or fingerprint != actual or result.processor.model != model:
            raise ValueError('Расчёт устарел. Повторите проверку и расчёт')
        target = project.path / 'project.txt'
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('project.txt должен быть обычным файлом в папке проекта')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=project.path,
                                             prefix='.report-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                for line in self.lines(project.name, result, subdivisions):
                    if cancelled is not None and cancelled():
                        raise ValueError('Отчёт отменён после изменения проекта')
                    stream.write(line + '\n')
            _, actual = store.read_for_processor(project)
            if actual != fingerprint:
                raise ValueError('Файлы изменились во время подготовки отчёта. Повторите расчёт')
            if cancelled is not None and cancelled():
                raise ValueError('Отчёт отменён после изменения проекта')
            temporary.replace(target)
            return target
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def lines(self, name: str, result: PostprocessorResult, subdivisions: int):
        '''Выдаёт строки отчёта последовательно, не накапливая таблицу в памяти.'''
        yield 'Результаты расчёта'
        yield f'Проект: {name}'
        yield f'Дата: {datetime.now(timezone.utc):%d.%m.%Y %H:%M} UTC'
        yield 'Все величины в СИ. Числа округлены только для чтения.'
        yield 'Проверка прочности выполнена без округления.'
        yield 'Положительные N и σ - растяжение, положительное u - перемещение вправо.'
        yield ''
        yield 'Стержни'
        yield from self._table(
            ('Стержень', 'L, м', 'A, м2', 'E, Па', 'Допуск, Па', 'q, Н/м'),
            ((bar.index + 1, bar.geometry.length_m, bar.geometry.area_m2, bar.geometry.modulus_pa,
              bar.geometry.allowable_stress_pa, bar.q_n_per_m) for bar in result.bars),
            (8, 13, 13, 13, 13, 13),
        )
        yield ''
        yield 'Узлы'
        source = result.processor
        yield from self._table(
            ('Узел', 'Закрепление', 'F, Н', 'Δ, м', 'Реакция, Н'),
            ((index, 'Да' if fixed else 'Нет', force, displacement, reaction)
             for index, (fixed, force, displacement, reaction) in enumerate(zip(
                 source.model.supports, source.model.nodal_forces, source.displacements, source.reactions), 1)),
            (8, 13, 13, 13, 13), left_columns=(0, 1),
        )
        yield ''
        yield 'Проверка прочности'
        yield from self._table(
            ('Стержень', 'Макс модуль σ, Па', 'Допуск, Па', 'Результат'),
            ((bar.index + 1, bar.max_abs_stress_pa, bar.geometry.allowable_stress_pa, bar.stress_status)
             for bar in result.bars),
            (8, 17, 13, 20), left_columns=(0, 3),
        )
        yield ''
        yield 'Экстремумы'
        yield 'x - расстояние от начала выбранного стержня.'
        for bar in result.bars:
            yield ''
            yield f'Стержень {bar.index + 1}'
            rows = []
            for component, label in (('N', 'N, Н'), ('sigma', 'σ, Па'), ('u', 'u, м')):
                minimum, maximum = bar.extrema(component)
                rows.append((label, minimum.value(component), minimum.x_m, maximum.value(component), maximum.x_m))
            yield from self._table(('Величина', 'Минимум', 'x минимума, м', 'Максимум', 'x максимума, м'),
                                   rows, (8, 13, 13, 13, 13))
        yield ''
        yield 'Сечения'
        yield f'Разбиений на стержень: {subdivisions}'
        yield 'Концы, экстремумы, нули и пересечения допуска добавлены в таблицу.'
        count = 0
        for bar in result.bars:
            yield ''
            yield f'Стержень {bar.index + 1}'
            widths = (13, 13, 13, 13)
            yield self._row(('x, м', 'N, Н', 'σ, Па', 'u, м'), widths)
            for x_m in bar.sample_positions(subdivisions):
                count += 1
                if count > self.MAX_ROWS:
                    raise ValueError('Для отчёта уменьшите число разбиений. Допустимо до 200000 строк')
                point = bar.at(x_m)
                yield self._row((point.x_m, point.force_n, point.stress_pa, point.displacement_m), widths)
        yield ''
        yield 'Формулы'
        yield 'N(x) = E*A/L * (Δj - Δi) + q * (L/2 - x)'
        yield 'σ(x) = N(x) / A'
        yield 'u(x) = Δi + x/L * (Δj - Δi) + q*x*(L-x)/(2*E*A)'
        yield 'Δi и Δj - перемещения начального и конечного узлов стержня.'

    @classmethod
    def _table(cls, headers, rows, widths, *, left_columns=(0,)):
        '''Выравнивает заголовки и строки одинаково, сохраняя потоковую запись.'''
        widths = tuple(max(width, len(header)) for header, width in zip(headers, widths))
        yield cls._row(headers, widths, left_columns=left_columns)
        for values in rows:
            yield cls._row(values, widths, left_columns=left_columns)

    @staticmethod
    def _row(values, widths, *, left_columns=(0,)) -> str:
        '''Записывает числа компактно и отделяет столбцы обычными пробелами.'''
        cells = []
        for index, (value, width) in enumerate(zip(values, widths)):
            text = format_quantity(value, compact=True) if isinstance(value, Decimal) else str(value)
            cells.append(text.ljust(width) if index in left_columns else text.rjust(width))
        return '  '.join(cells).rstrip()
