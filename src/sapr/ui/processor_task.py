'''Выполняет расчёт в рабочем потоке и возвращает неизменяемый результат.'''

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ..domain.processor import AxialProcessor
from ..storage import Project, ProjectStore


class ProcessorSignals(QObject):
    '''Передаёт результат в основной поток интерфейса.'''

    finished = pyqtSignal(int, object, str, str)


class ProcessorTask(QRunnable):
    '''Читает проверенный снимок и решает его без обращения к виджетам.'''

    def __init__(self, project: Project, revision: int) -> None:
        super().__init__()
        self.project, self.revision = project, revision
        self.signals = ProcessorSignals()

    def run(self) -> None:
        '''Проверяет файлы до и после вычисления, затем передаёт результат.'''
        try:
            store = ProjectStore()
            model, fingerprint = store.read_for_processor(self.project)
            result = AxialProcessor().solve(model)
            _, actual = store.read_for_processor(self.project)
            if fingerprint != actual:
                raise ValueError('Данные изменились во время расчёта. Повторите проверку')
        except (OSError, ValueError, ArithmeticError) as error:
            self.signals.finished.emit(self.revision, None, '', str(error))
            return
        self.signals.finished.emit(self.revision, result, fingerprint, '')
