'''Сохраняет минимальные отчёты TXT и HTML для актуального расчёта.'''

from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from pathlib import Path
import tempfile
from typing import Callable

from ..domain.postprocessor import PostprocessorResult
from ..domain.sampling import BarSamples
from ..formatting import format_result
from .project_store import Project, ProjectStore


class ResultReport:
    '''Формирует отчёты в СИ, округляя только отображение величин.'''

    MAX_ROWS = 200000

    def write(self, project: Project, result: PostprocessorResult, fingerprint: str, subdivisions: int = 10,
              *, cancelled: Callable[[], bool] | None = None, file_format: str = 'txt',
              places: int = 6, step: Decimal | None = None, extrema_only: bool = False,
              diagram: str = '') -> Path:
        '''Атомарно сохраняет отчёт и повторно проверяет исходные файлы.

        Args:
            project: Сохранённый проект с актуальными обработанными файлами.
            result: Аналитические результаты расчёта.
            fingerprint: Отпечаток исходных и обработанных файлов.
            subdivisions: Число интервалов таблицы на стержне.
            cancelled: Проверка отмены при редактировании проекта.
            file_format: Расширение txt или html.
            places: Число дробных знаков представления.
            step: Постоянный шаг таблицы в метрах вместо числа интервалов.
            extrema_only: Выводить в таблице только уникальные экстремумы.
            diagram: Самодостаточная схема с эпюрами в SVG для отчёта HTML.

        Returns:
            Путь к готовому отчёту в папке проекта.

        Raises:
            ValueError: Результат устарел, параметры или объём отчёта недопустимы.
            OSError: Не удалось записать файл.
        '''
        if file_format not in ('txt', 'html') or not 0 <= places <= 12:
            raise ValueError('Выберите TXT или HTML и точность от 0 до 12')
        if file_format == 'html' and not diagram.lstrip().startswith('<svg'):
            raise ValueError('Для HTML требуется изображение конструкции с эпюрами')
        count = sum(BarSamples(bar, subdivisions, step=step, extrema_only=extrema_only).count for bar in result.bars)
        if count > self.MAX_ROWS:
            raise ValueError('Уменьшите число разбиений или увеличьте шаг. Допустимо до 200000 строк')
        store = ProjectStore()
        model, actual = store.read_for_processor(project)
        if not fingerprint or fingerprint != actual or result.processor.model != model:
            raise ValueError('Расчёт устарел. Повторите проверку и расчёт')
        target = project.path / f'project.{file_format}'
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('Отчёт должен быть обычным файлом в папке проекта')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=project.path,
                                             prefix='.report-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                options = (project.name, result, subdivisions, places, step, extrema_only)
                content = self.html_lines(*options, diagram) if file_format == 'html' else self.lines(*options)
                for line in content:
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

    @staticmethod
    def conclusion(result: PostprocessorResult) -> str:
        '''Формулирует общую прочность по неокруглённым напряжениям.'''
        exceeded = [str(bar.index + 1) for bar in result.bars if bar.stress_status == 'Превышение']
        if exceeded:
            return 'Прочность не обеспечена. Превышение в стержнях: ' + ', '.join(exceeded)
        return 'Прочность обеспечена'

    @staticmethod
    def _sampling_text(subdivisions, step, extrema_only) -> str:
        '''Описывает выбранную сетку сечений одной строкой.'''
        if extrema_only:
            return 'Только экстремумы'
        return f'Шаг таблицы: {step} м' if step is not None else f'Разбиений на стержень: {subdivisions}'

    @staticmethod
    def _tables(result, subdivisions, step, extrema_only):
        '''Передаёт обоим форматам одинаковые заголовки, значения и признаки превышений.'''
        yield 'Стержни', ('Стержень', 'L, м', 'A, м2', 'E, Па', 'Допуск, Па', 'q, Н/м'), (
            (bar.index + 1, bar.geometry.length_m, bar.geometry.area_m2, bar.geometry.modulus_pa,
             bar.geometry.allowable_stress_pa, bar.q_n_per_m) for bar in result.bars), ()
        source = result.processor
        yield 'Узлы', ('Узел', 'X, м', 'Закрепление', 'F, Н', 'Δ, м', 'Реакция, Н'), (
            (i + 1, x, 'Да' if fixed else 'Нет', force, displacement, reaction)
            for i, (x, fixed, force, displacement, reaction) in enumerate(zip(
                source.model.node_positions_m, source.model.supports, source.model.nodal_forces,
                source.displacements, source.reactions))), ()
        yield 'Проверка прочности', ('Стержень', 'Макс |σ|, Па', 'Допуск, Па', 'Результат'), (
            (bar.index + 1, bar.max_abs_stress_pa, bar.geometry.allowable_stress_pa, bar.stress_status)
            for bar in result.bars), (1, 3)
        for bar in result.bars:
            extrema = []
            for component, label in (('N', 'N, Н'), ('sigma', 'σ, Па'), ('u', 'u, м')):
                for kind, point in zip(('Минимум', 'Максимум'), bar.extrema(component)):
                    flag = 'Превышение' if component == 'sigma' and point.stress_pa.copy_abs() > bar.geometry.allowable_stress_pa else ''
                    extrema.append((label, kind, point.x_m, point.value(component), flag))
            yield f'Экстремумы - стержень {bar.index + 1}', ('Величина', 'Экстремум', 'x, м', 'Значение', 'Результат'), extrema, (3, 4)
        for bar in result.bars:
            sample = BarSamples(bar, subdivisions, step=step, extrema_only=extrema_only)
            yield f'Сечения - стержень {bar.index + 1}', ('x, м', 'N, Н', 'σ, Па', 'u, м', 'Результат'), ResultReport._section_rows(sample), (2, 4)

    @staticmethod
    def _section_rows(sample):
        '''Вычисляет строки по одной, включая признак нарушения прочности.'''
        for row in range(sample.count):
            point = sample.bar.at(sample.position(row))
            flag = 'Превышение' if point.stress_pa.copy_abs() > sample.bar.geometry.allowable_stress_pa else ''
            yield point.x_m, point.force_n, point.stress_pa, point.displacement_m, flag

    def lines(self, name: str, result: PostprocessorResult, subdivisions: int,
              places: int = 6, step: Decimal | None = None, extrema_only: bool = False):
        '''Выдаёт простой текстовый отчёт с пометками превышений.'''
        yield 'Результаты расчёта'
        yield f'Проект: {name}'
        yield f'Дата: {datetime.now(timezone.utc):%d.%m.%Y %H:%M} UTC'
        yield 'Все величины в СИ. Числа округлены только для чтения.'
        yield f'Знаков после точки: {places}. Проверка прочности выполнена без округления.'
        yield self.conclusion(result)
        yield self._sampling_text(subdivisions, step, extrema_only)
        yield 'В экстремумах x отсчитывается от начала стержня; при нескольких координатах указана одна.'
        for title, headers, rows, _ in self._tables(result, subdivisions, step, extrema_only):
            yield ''
            yield title
            widths = tuple(max(13, len(header)) for header in headers)
            yield self._row(headers, widths, places)
            for values in rows:
                yield self._row(values, widths, places)
        yield ''
        yield 'Формулы'
        yield 'N(x) = E*A/L * (Δj - Δi) + q * (L/2 - x)'
        yield 'σ(x) = N(x) / A'
        yield 'u(x) = Δi + x/L * (Δj - Δi) + q*x*(L-x)/(2*E*A)'

    def html_lines(self, name, result, subdivisions, places, step, extrema_only, diagram):
        '''Выдаёт автономный HTML без внешних шрифтов, скриптов и изображений.'''
        yield '<!doctype html><html lang="ru"><meta charset="utf-8">'
        yield '<meta name="viewport" content="width=device-width, initial-scale=1">'
        yield f'<title>{escape(name)} - расчёт</title>'
        yield '<style>body{font:14px Arial,sans-serif;color:#202020;max-width:1120px;margin:32px auto;padding:0 20px}'
        yield 'h1{font-size:22px;font-weight:600}h2{font-size:17px;margin-top:28px;font-weight:600}'
        yield 'p{line-height:1.5}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}'
        yield 'td,th{text-align:center;padding:7px 8px;border-bottom:1px solid #ddd}th{font-weight:600}'
        yield '.exceeded{color:#a32020;background:#fff0f0}.table{overflow-x:auto}svg{width:100%;height:auto}'
        yield '@media print{body{margin:0}tr,svg{break-inside:avoid}thead{display:table-header-group}}</style><body>'
        yield f'<h1>{escape(name)}</h1>'
        yield f'<p>{datetime.now(timezone.utc):%d.%m.%Y %H:%M} UTC. СИ. Знаков после точки: {places}.</p>'
        yield f'<p>{escape(self.conclusion(result))}</p>'
        yield '<h2>Конструкция и эпюры</h2>'
        yield diagram
        yield f'<p>{escape(self._sampling_text(subdivisions, step, extrema_only))}. Прочность проверена без округления.</p>'
        yield '<p>В экстремумах x отсчитывается от начала стержня; при нескольких координатах указана одна.</p>'
        for title, headers, rows, marked in self._tables(result, subdivisions, step, extrema_only):
            yield f'<h2>{escape(title)}</h2><div class="table"><table><thead><tr>'
            yield ''.join(f'<th>{escape(header)}</th>' for header in headers) + '</tr></thead><tbody>'
            for values in rows:
                exceeded = values[-1] == 'Превышение'
                cells = []
                for index, value in enumerate(values):
                    css = ' class="exceeded"' if exceeded and index in marked else ''
                    text = format_result(value, places) if isinstance(value, Decimal) else str(value)
                    cells.append(f'<td{css}>{escape(text)}</td>')
                yield '<tr>' + ''.join(cells) + '</tr>'
            yield '</tbody></table></div>'
        yield '</body></html>'

    @staticmethod
    def _row(values, widths, places) -> str:
        '''Разделяет выровненные столбцы обычными пробелами.'''
        return '  '.join((format_result(value, places) if isinstance(value, Decimal) else str(value)).rjust(width)
                         for value, width in zip(values, widths)).rstrip()
