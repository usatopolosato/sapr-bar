'''Выполняет вычисления и запись отчёта вне основного потока Qt.'''

from threading import Event

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ..domain.processor import AxialProcessor
from ..domain.postprocessor import AxialPostprocessor
from ..storage import Project, ProjectStore
from ..storage.result_report import ResultReport


class TaskSignals(QObject):
    '''Передаёт результат, версию модели, отпечаток файлов и ошибку.'''

    finished = pyqtSignal(int, object, str, str)


class BackgroundTask(QRunnable):
    '''Объединяет отправку результата и обработку ожидаемых ошибок.'''

    def __init__(self, revision: int, fingerprint: str = '') -> None:
        super().__init__()
        self.revision = revision
        self.fingerprint = fingerprint
        self.signals = TaskSignals()

    def run(self) -> None:
        '''Возвращает результат в поток интерфейса через единый сигнал.'''
        try:
            result, fingerprint = self.execute()
        except (OSError, ValueError, ArithmeticError) as error:
            self.signals.finished.emit(self.revision, None, self.fingerprint, str(error))
            return
        self.signals.finished.emit(self.revision, result, fingerprint, '')

    def execute(self) -> tuple[object, str]:
        '''Определяет работу подкласса без доступа к виджетам.'''
        raise NotImplementedError


class ProcessorTask(BackgroundTask):
    '''Решает проверенную модель и повторно сверяет файлы после расчёта.'''

    def __init__(self, project: Project, revision: int) -> None:
        super().__init__(revision)
        self.project = project

    def execute(self) -> tuple[object, str]:
        '''Возвращает решение только для неизменившегося снимка файлов.'''
        store = ProjectStore()
        model, fingerprint = store.read_for_processor(self.project)
        result = AxialProcessor().solve(model)
        _, actual = store.read_for_processor(self.project)
        if fingerprint != actual:
            raise ValueError('Данные изменились во время расчёта. Повторите проверку')
        return result, fingerprint


class PostprocessorTask(BackgroundTask):
    '''Готовит функции и характерные точки для эпюр и таблиц.'''

    def __init__(self, source, revision: int, fingerprint: str) -> None:
        super().__init__(revision, fingerprint)
        self.source = source

    def execute(self) -> tuple[object, str]:
        '''Заранее вычисляет общие данные отображения в рабочем потоке.'''
        result = AxialPostprocessor().analyze(self.source)
        for bar in result.bars:
            bar.critical_positions()
            bar.extrema('u')
            _ = bar.stress_ratio
        return result, self.fingerprint


class ReportTask(BackgroundTask):
    '''Записывает отчёт с отменой при изменении исходной модели.'''

    def __init__(self, project, result, revision: int, fingerprint: str, subdivisions: int) -> None:
        super().__init__(revision, fingerprint)
        self.project = project
        self.result = result
        self.subdivisions = subdivisions
        self.cancelled = Event()

    def execute(self) -> tuple[object, str]:
        '''Атомарно записывает актуальный результат в текстовый файл.'''
        path = ResultReport().write(self.project, self.result, self.fingerprint, self.subdivisions,
                                    cancelled=self.cancelled.is_set)
        return path, self.fingerprint
