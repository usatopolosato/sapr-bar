'''Сохраняет отчёт НДС, проверяя актуальность результата перед записью.'''

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Callable

from ..domain.postprocessor import PostprocessorResult
from .project_store import Project, ProjectStore


class ResultReport:
    '''Формирует текстовый отчёт в СИ без округления значений Decimal.'''

    MAX_ROWS = 200000

    def write(self, project: Project, result: PostprocessorResult, fingerprint: str, subdivisions: int = 10,
              *, cancelled: Callable[[], bool] | None = None) -> Path:
        '''Атомарно записывает project.res для актуального расчёта.

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
        target = project.path / 'project.res'
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('project.res должен быть обычным файлом в папке проекта')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=project.path,
                                             prefix='.report-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                for line in self.lines(project.name, result, fingerprint, subdivisions):
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

    def lines(self, name: str, result: PostprocessorResult, fingerprint: str, subdivisions: int):
        '''Выдаёт строки отчёта последовательно, не накапливая таблицу в памяти.'''
        yield 'САПР BAR - Результаты расчёта'
        yield f'Проект: {name}'
        yield f'Создано UTC: {datetime.now(timezone.utc).isoformat(timespec="seconds")}'
        yield f'Отпечаток исходного расчёта: {fingerprint}'
        yield f'Точность Decimal: {result.precision} значащих цифр'
        yield 'Единицы СИ: длина и перемещение м, сила Н, напряжение Па, погонная нагрузка Н/м'
        yield 'Положительные N и sigma означают растяжение, положительное u - перемещение вправо'
        yield 'Все числовые значения записаны без округления для отображения'
        yield ''
        yield 'ИСХОДНЫЕ ДАННЫЕ'
        yield 'Стержень  L, м  A, м2  E, Па  Допуск, Па  q, Н/м'
        for response in result.bars:
            bar = response.geometry
            yield self._row(response.index + 1, bar.length_m, bar.area_m2, bar.modulus_pa,
                            bar.allowable_stress_pa, response.q_n_per_m)
        yield ''
        yield 'УЗЛОВЫЕ ПЕРЕМЕЩЕНИЯ И РЕАКЦИИ'
        yield 'Узел  Закрепление  F, Н  Delta, м  Реакция, Н'
        source = result.processor
        for index, (fixed, force, displacement, reaction) in enumerate(zip(
                source.model.supports, source.model.nodal_forces, source.displacements, source.reactions), 1):
            yield self._row(index, int(fixed), force, displacement, reaction)
        yield ''
        yield 'ФОРМУЛЫ'
        yield 'N(x) = EA/L * (Delta_right - Delta_left) + q * (L/2 - x)'
        yield 'sigma(x) = N(x) / A'
        yield 'u(x) = Delta_left + x/L * (Delta_right - Delta_left) + q*x*(L-x)/(2*EA)'
        yield 'x - локальная координата стержня от 0 до L'
        yield ''
        yield 'ЭКСТРЕМУМЫ И ПРОВЕРКА ПРОЧНОСТИ'
        for bar in result.bars:
            yield f'Стержень {bar.index + 1}'
            for component, units in (('N', 'Н'), ('sigma', 'Па'), ('u', 'м')):
                minimum, maximum = bar.extrema(component)
                yield f'{component}, {units}: min {minimum.value(component)} при x = {minimum.x_m} м'
                yield f'{component}, {units}: max {maximum.value(component)} при x = {maximum.x_m} м'
            yield f'Максимум модуля sigma: {bar.max_abs_stress_pa} Па'
            yield f'Допуск: {bar.geometry.allowable_stress_pa} Па'
            yield f'Отношение к допуску: {bar.stress_ratio}'
            yield f'Состояние: {bar.stress_status}'
            yield ''
        yield f'ТАБЛИЦА СЕЧЕНИЙ - разбиений на стержень {subdivisions}'
        yield 'Концы, экстремумы, нули функций и пересечения допуска включены дополнительно'
        yield 'Стержень  x, м  N, Н  sigma, Па  u, м'
        rows = 0
        for bar in result.bars:
            for x_m in bar.sample_positions(subdivisions):
                rows += 1
                if rows > self.MAX_ROWS:
                    raise ValueError('Для отчёта уменьшите число разбиений. Допустимо до 200000 строк')
                point = bar.at(x_m)
                yield self._row(point.bar_index + 1, point.x_m, point.force_n, point.stress_pa, point.displacement_m)

    @staticmethod
    def _row(*values) -> str:
        '''Разделяет точные числовые значения столбцами текстовой таблицы.'''
        return '  '.join(str(value).rjust(24) for value in values)
