'''Готовит аналитические результаты и отчёт вне потока интерфейса.'''

from threading import Event

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ..domain.postprocessor import AxialPostprocessor
from ..storage.result_report import ResultReport


class PostprocessorSignals(QObject):
    '''Передаёт результат работы и привязку к текущему расчёту.'''

    finished = pyqtSignal(int, object, str, str)


class PostprocessorTask(QRunnable):
    '''Создаёт аналитические функции из неизменяемого результата процессора.'''

    def __init__(self, source, revision: int, fingerprint: str) -> None:
        super().__init__()
        self.source, self.revision, self.fingerprint = source, revision, fingerprint
        self.signals = PostprocessorSignals()

    def run(self) -> None:
        '''Выполняет восстановление полей и сообщает диагностируемые ошибки.'''
        try:
            result = AxialPostprocessor().analyze(self.source)
            for bar in result.bars:
                bar.critical_positions()
                bar.extrema('u')
                _ = bar.stress_ratio
        except (ValueError, ArithmeticError) as error:
            self.signals.finished.emit(self.revision, None, self.fingerprint, str(error))
            return
        self.signals.finished.emit(self.revision, result, self.fingerprint, '')


class ReportTask(QRunnable):
    '''Записывает отчёт с возможностью отмены при изменении модели.'''

    def __init__(self, project, result, revision: int, fingerprint: str, subdivisions: int) -> None:
        super().__init__()
        self.project, self.result = project, result
        self.revision, self.fingerprint, self.subdivisions = revision, fingerprint, subdivisions
        self.cancelled = Event()
        self.signals = PostprocessorSignals()

    def run(self) -> None:
        '''Записывает файл, если расчёт не был отозван за время подготовки.'''
        try:
            path = ResultReport().write(self.project, self.result, self.fingerprint, self.subdivisions,
                                        cancelled=self.cancelled.is_set)
        except (OSError, ValueError, ArithmeticError) as error:
            self.signals.finished.emit(self.revision, None, self.fingerprint, str(error))
            return
        self.signals.finished.emit(self.revision, path, self.fingerprint, '')
