'''Проверяет собранное приложение на временном проекте без пользовательских настроек.'''

import json
from pathlib import Path
import tempfile
import traceback

from PyQt6.QtCore import QEventLoop, QSettings, QTimer

from .domain import demo_model
from .metadata import AUTHOR, VERSION
from .storage import ProjectStore
from .storage.result_report import ResultReport
from .ui.main_window import MainWindow, Page
from .ui.theme import ThemeMode


def wait_for(task) -> None:
    '''Ожидает сигнал рабочего потока с ограничением времени.'''
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    task.signals.finished.connect(loop.quit)
    timer.start(15000)
    loop.exec()
    if not timer.isActive():
        raise TimeoutError('Рабочий поток не завершился за 15 секунд')
    timer.stop()


def run_smoke_test(output: Path) -> int:
    '''Проверяет формы, темы, файлы, расчёт, эпюры и отчёт в готовом EXE.

    Args:
        output: Путь к JSON с результатом проверки и соседним снимкам окна.

    Returns:
        Ноль при успехе или единица при обнаруженной ошибке.
    '''
    from .app import create_application

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    app = create_application([], persist_theme=False)
    details = {'version': VERSION, 'author': AUTHOR, 'ok': False}
    try:
        with tempfile.TemporaryDirectory(prefix='sapr-smoke-', dir=output.parent) as directory:
            root = Path(directory)
            settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
            window = MainWindow(app.theme_manager, settings)
            window.resize(1360, 850)
            window.show()
            assert not app.windowIcon().isNull(), 'Не загружена иконка'
            store = ProjectStore()
            project = store.create(root, 'Проверка сборки')
            window._activate_project(project)
            window.preprocessor_page.set_model(demo_model())
            assert window.save_project()
            assert len(list(project.path.iterdir())) == 3
            assert not window.project_page.processorButton.isEnabled()
            assert window.validate_project()
            assert window.project_page.processorButton.isEnabled()
            window.navigate(Page.PROCESSOR)
            window.calculate_project()
            wait_for(window._processor_task)
            assert window.processor_page.result is not None
            window.navigate(Page.POSTPROCESSOR)
            wait_for(window._postprocessor_task)
            assert window.postprocessor_page.result is not None
            report = ResultReport().write(window.current_project, window.postprocessor_page.result,
                                          window._processor_fingerprint)
            assert report.exists() and report.stat().st_size > 0
            for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
                app.theme_manager.set_mode(mode)
                app.processEvents()
                window.grab().save(str(output.with_name(f'{output.stem}-{mode.value}.png')))
            details.update(ok=True, nodes=len(window.processor_page.result.displacements),
                           report_bytes=report.stat().st_size)
            window.close()
            app.processEvents()
    except Exception:
        details['error'] = traceback.format_exc()
    output.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if details['ok'] else 1
