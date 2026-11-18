'''Организует навигацию между независимыми страницами приложения.'''

from enum import Enum
from dataclasses import replace
from functools import partial
from pathlib import Path

from PyQt6.QtCore import QSettings, QStandardPaths, QThreadPool, QTimer, Qt, QUrl
from PyQt6.QtGui import QActionGroup, QDesktopServices, QKeySequence, QPalette, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QInputDialog, QMainWindow,
    QMenu, QMessageBox, QScrollArea, QToolButton,
)

from ..domain import StructuralModel, validate_model
from ..storage import Project, ProjectStore
from ..storage.json_project import read_project_json, write_project_json
from ..metadata import AUTHOR, NAME

from .loader import load_form
from .pages.postprocessor import PostprocessorPage
from .pages.preprocessor import PreprocessorPage
from .pages.processor import ProcessorPage
from .pages.project_hub import ProjectHubPage
from .pages.welcome import WelcomePage
from .project_dialog import ProjectDialog
from .tasks import ProcessorTask, PostprocessorTask, ReportTask
from .theme import ThemeColors, ThemeManager, ThemeMode
from .widgets.response_plot import ResponsePlot


class Page(Enum):
    '''Задаёт именованные страницы навигации.'''

    WELCOME = 'Начало работы'
    PROJECT = 'Обзор проекта'
    PREPROCESSOR = 'Препроцессор'
    PROCESSOR = 'Процессор'
    POSTPROCESSOR = 'Постпроцессор'


class MainWindow(QMainWindow):
    '''Связывает страницы и оформление рабочего пространства.

    Args:
        theme_manager: Менеджер общей темы приложения.
        settings: Хранилище расположения проектов.
    '''

    def __init__(self, theme_manager: ThemeManager, settings: QSettings | None = None) -> None:
        super().__init__()
        load_form('main_window.ui', self)
        self._theme_manager = theme_manager
        self._settings = settings if settings is not None else QSettings('usatopolosato', 'sapr-bar')
        self._store = ProjectStore()
        self.current_project: Project | None = None
        self._dirty = False
        self._processor_revision = 0
        self._processor_fingerprint = ''
        self._processor_signature = None
        self._processor_task = None
        self._postprocessor_task = None
        self._report_task = None
        self.current_page = Page.WELCOME
        self.welcome_page = WelcomePage(self)
        self.project_page = ProjectHubPage(self)
        self.preprocessor_page = PreprocessorPage(self)
        self.processor_page = ProcessorPage(self)
        self.postprocessor_page = PostprocessorPage(self)
        self._pages = {
            Page.WELCOME: self.welcome_page,
            Page.PROJECT: self.project_page,
            Page.PREPROCESSOR: self.preprocessor_page,
            Page.PROCESSOR: self.processor_page,
            Page.POSTPROCESSOR: self.postprocessor_page,
        }
        self._page_containers = {}
        for key, page in self._pages.items():
            page.setProperty('role', 'page')
            page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            container = QScrollArea(self.pageStack)
            container.viewport().setBackgroundRole(QPalette.ColorRole.Window)
            container.setWidgetResizable(True)
            container.setFrameShape(QScrollArea.Shape.NoFrame)
            container.setWidget(page)
            self._page_containers[key] = container
            self.pageStack.addWidget(container)
        self._setup_theme_menu()
        self._theme_manager.changed.connect(self._apply_theme)
        self._apply_theme(self._theme_manager.colors)
        self._nav_buttons = {
            Page.PROJECT: self.hubNavButton,
            Page.PREPROCESSOR: self.preprocessorNavButton,
            Page.PROCESSOR: self.processorNavButton,
            Page.POSTPROCESSOR: self.postprocessorNavButton,
        }
        self._navigation_group = QButtonGroup(self)
        for page, button in self._nav_buttons.items():
            self._navigation_group.addButton(button)
            button.clicked.connect(partial(self.navigate, page))
        section_menu = QMenu(self.sectionButton)
        for page in self._nav_buttons:
            action = section_menu.addAction(page.value)
            action.triggered.connect(partial(self.navigate, page))
        section_menu.addAction('Главное меню').triggered.connect(partial(self.navigate, Page.WELCOME))
        self.sectionButton.setMenu(section_menu)
        self.sectionButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.welcome_page.createRequested.connect(self.create_project)
        self.welcome_page.openRequested.connect(self.open_project)
        self.welcome_page.importRequested.connect(self.import_project)
        self._setup_project_menu()
        self.project_page.preprocessorRequested.connect(partial(self.navigate, Page.PREPROCESSOR))
        self.project_page.processorRequested.connect(partial(self.navigate, Page.PROCESSOR))
        self.project_page.postprocessorRequested.connect(partial(self.navigate, Page.POSTPROCESSOR))
        self.project_page.homeRequested.connect(partial(self.navigate, Page.WELCOME))
        self.processor_page.preprocessorRequested.connect(partial(self.navigate, Page.PREPROCESSOR))
        self.processor_page.calculateRequested.connect(self.calculate_project)
        self.postprocessor_page.processorRequested.connect(partial(self.navigate, Page.PROCESSOR))
        self.postprocessor_page.reportRequested.connect(self.export_report)
        self.homeButton.clicked.connect(partial(self.navigate, Page.WELCOME))
        self.preprocessor_page.modelChanged.connect(self._model_changed)
        self.preprocessor_page.saveRequested.connect(self.save_project)
        self.preprocessor_page.validateRequested.connect(self.validate_project)
        self._processor_watch = QTimer(self)
        self._processor_watch.setInterval(1000)
        self._processor_watch.timeout.connect(self._watch_processor_files)
        self._processor_watch.start()
        self._shortcuts = []
        for sequence, action in (
            ('Ctrl+N', self.create_project),
            ('Ctrl+O', self.open_project),
            ('Ctrl+S', self.save_project),
            ('Ctrl+Shift+S', self.save_project_as),
            ('Escape', self._go_back),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(action)
            self._shortcuts.append(shortcut)
        self.navigate(Page.WELCOME)

    def _setup_project_menu(self) -> None:
        '''Объединяет файловые операции в доступное на всех страницах меню.'''
        menu = QMenu(self.projectButton)
        menu.addAction('Создать проект').triggered.connect(self.create_project)
        menu.addAction('Открыть проект').triggered.connect(self.open_project)
        menu.addAction('Импорт JSON').triggered.connect(self.import_project)
        menu.addSeparator()
        self._project_actions = []
        for title, callback in (
            ('Сохранить', self.save_project), ('Сохранить как JSON', self.save_project_as),
            ('Переименовать', self.rename_project),
        ):
            action = menu.addAction(title)
            action.triggered.connect(callback)
            self._project_actions.append(action)
        menu.aboutToShow.connect(self._sync_project_actions)
        self.projectButton.setMenu(menu)
        self.projectButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

    def _sync_project_actions(self) -> None:
        '''Разрешает операции сохранения и переименования для открытого проекта.'''
        for action in self._project_actions:
            action.setEnabled(self.current_project is not None)

    def _setup_theme_menu(self) -> None:
        '''Создаёт меню выбора системной светлой или тёмной темы.'''
        self._theme_actions = {}
        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)
        menu = QMenu(self.themeButton)
        for mode, title in (
            (ThemeMode.SYSTEM, 'Системная'),
            (ThemeMode.LIGHT, 'Светлая'),
            (ThemeMode.DARK, 'Тёмная'),
        ):
            action = menu.addAction(title)
            action.setCheckable(True)
            self._theme_action_group.addAction(action)
            action.triggered.connect(partial(self._choose_theme, mode))
            self._theme_actions[mode] = action
        self.themeButton.setMenu(menu)
        self.themeButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

    def _choose_theme(self, mode: ThemeMode, checked: bool = False) -> None:
        '''Применяет выбранный пользователем режим оформления.

        Args:
            mode: Выбранная тема или следование системе.
            checked: Состояние действия меню из сигнала Qt.
        '''
        self._theme_manager.set_mode(mode)
        self._sync_theme_menu()

    def _sync_theme_menu(self) -> None:
        '''Согласует отметку меню с выбранным режимом оформления.'''
        current = self._theme_actions[self._theme_manager.mode]
        current.setChecked(True)
        self.themeButton.setToolTip(f'Тема - {current.text()}')

    def _apply_theme(self, colors: ThemeColors) -> None:
        '''Обновляет графические сцены при смене общей палитры.

        Args:
            colors: Цвета активной темы.
        '''
        self.welcome_page.structure_view.set_theme(colors)
        self.preprocessor_page.structure_view.set_theme(colors)
        self.postprocessor_page.set_theme(colors)
        self._sync_theme_menu()

    def navigate(self, page: Page, checked: bool = False) -> None:
        '''Переключает страницу и согласует элементы навигации.

        Args:
            page: Целевая страница.
            checked: Состояние кнопки из сигнала Qt.
        '''
        self.current_page = page
        self._update_layout()
        self.breadcrumbLabel.setText(page.value)
        self.pageStack.setCurrentWidget(self._page_containers[page])
        if page in self._nav_buttons:
            self._nav_buttons[page].setChecked(True)
        if page in (Page.PROCESSOR, Page.POSTPROCESSOR):
            self.preprocessor_page.commit_pending_edits()
            if page is Page.POSTPROCESSOR:
                self._refresh_postprocessor()
            else:
                self._refresh_processor()
        elif page is Page.PROJECT:
            self._refresh_processor()

    def _activate_project(self, project: Project) -> None:
        '''Загружает сохранённую модель в рабочее пространство.

        Args:
            project: Проект с расположением и исходными данными.
        '''
        self.current_project = project
        self._invalidate_processor()
        self._dirty = False
        self.preprocessor_page.set_model(project.model)
        self.project_page.set_project_name(project.name)
        self.sidebarProjectLabel.setText(project.name)
        self.sidebarProjectLabel.setToolTip(str(project.path))
        self._settings.setValue('projects/directory', str(project.path.parent))
        self._update_title()
        self.navigate(Page.PREPROCESSOR)

    def create_project(self) -> None:
        '''Создаёт папку проекта и начальные файлы исходных данных.'''
        if not self._confirm_project_change():
            return
        directory = self._settings.value('projects/directory', '', type=str)
        dialog = ProjectDialog(Path(directory) if directory else None, parent=self, store=self._store)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.project is not None:
            self._activate_project(dialog.project)

    def open_project(self) -> None:
        '''Выбирает папку существующего проекта и читает исходные данные.'''
        if not self._confirm_project_change():
            return
        directory = QFileDialog.getExistingDirectory(
            self, 'Выбрать папку проекта', self._settings.value('projects/directory', '', type=str),
        )
        if directory:
            try:
                project = self._store.load(Path(directory))
            except (OSError, ValueError) as error:
                self._show_error('Не удалось открыть проект', error)
                return
            self._activate_project(project)

    def save_project(self) -> bool:
        '''Сохраняет только CN, LD и KPR без подготовки данных процессора.

        Returns:
            Признак успешной записи текущей модели.
        '''
        return self._write_project(validate=False)

    def import_project(self) -> None:
        '''Открывает JSON и создаёт отдельную папку непроверенного проекта.'''
        if not self._confirm_project_change():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, 'Импорт проекта', self._settings.value('projects/directory', '', type=str),
            'Проекты JSON (*.json)',
        )
        if not filename:
            return
        path = Path(filename)
        try:
            model = read_project_json(path)
        except (OSError, ValueError) as error:
            self._show_error('Не удалось импортировать проект', error)
            return
        root = self._import_directory()
        folder = path.stem
        suffix = 2
        while (root / folder).exists():
            folder = f'{path.stem[:68]} {suffix}'
            suffix += 1
        try:
            project = self._store.create(root, path.stem, model=model, folder_name=folder)
        except (OSError, ValueError) as error:
            self._show_error('Не удалось создать импортированный проект', error)
            return
        self._activate_project(project)

    @staticmethod
    def _import_directory() -> Path:
        '''Возвращает постоянную папку импортированных проектов в AppData.'''
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / AUTHOR / NAME / 'projects'

    def save_project_as(self) -> bool:
        '''Сохраняет отдельную копию исходных данных в выбранный JSON.'''
        if self.current_project is None or not self.preprocessor_page.commit_pending_edits():
            return False
        directory = Path(self._settings.value('projects/directory', str(self.current_project.path.parent), type=str))
        filename, _ = QFileDialog.getSaveFileName(
            self, 'Сохранить как', str(directory / f'{self.current_project.name}.json'),
            'Проекты JSON (*.json)',
        )
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.lower() != '.json':
            path = path.with_suffix('.json')
        try:
            write_project_json(path, self.preprocessor_page.model)
        except (OSError, ValueError) as error:
            self._show_error('Не удалось сохранить JSON', error)
            return False
        self._settings.setValue('projects/directory', str(path.parent))
        self.preprocessor_page.show_status(f'Копия сохранена - {path.name}')
        return True

    def rename_project(self) -> None:
        '''Меняет название проекта и сохраняет текущие исходные данные.'''
        if self.current_project is None or not self.preprocessor_page.commit_pending_edits():
            return
        name, accepted = QInputDialog.getText(self, 'Переименовать проект', 'Название', text=self.current_project.name)
        if not accepted or name.strip() == self.current_project.name:
            return
        try:
            project = self._store.save(replace(self.current_project, name=name.strip()), self.preprocessor_page.model)
        except (OSError, ValueError) as error:
            self._show_error('Не удалось переименовать проект', error)
            return
        self._activate_project(project)

    def validate_project(self) -> bool:
        '''Сохраняет модель и формирует CNX и LDX после успешной проверки.

        Returns:
            Признак успешной проверки и записи обработанных файлов.
        '''
        return self._write_project(validate=True)

    def _write_project(self, *, validate: bool) -> bool:
        '''Записывает исходные данные и согласует доступность расчётных модулей.

        Args:
            validate: Требование проверить модель и подготовить файлы процессора.

        Returns:
            Признак успешного выполнения выбранного действия.
        '''
        if self.current_project is None or not self.preprocessor_page.commit_pending_edits():
            return False
        model = self.preprocessor_page.model
        issues = validate_model(model) if validate else ()
        try:
            self.current_project = self._store.save(self.current_project, model, validate=validate and not issues)
        except (OSError, ValueError) as error:
            self._show_error('Не удалось сохранить проект', error)
            return False
        self._dirty = False
        self._update_title()
        self._refresh_processor()
        if issues:
            self.preprocessor_page.show_status('\n'.join(issue.message for issue in issues[:4]), error=True)
        else:
            self.preprocessor_page.show_status('Проект проверен и сохранён' if validate else 'Исходные данные сохранены')
        return not issues

    def _model_changed(self, model: StructuralModel) -> None:
        '''Отмечает изменения относительно последнего сохранения.

        Args:
            model: Новое состояние редактируемой конструкции.
        '''
        self._dirty = self.current_project is not None and model != self.current_project.model
        self._invalidate_processor()
        self._update_title()

    def _invalidate_processor(self) -> None:
        '''Отзывает результат и выполняющийся запрос при изменении проекта.'''
        self._processor_revision += 1
        self._processor_fingerprint = ''
        self._processor_signature = None
        self._processor_task = None
        self.processor_page.set_availability(False, 'Проверьте проект в препроцессоре', reset=True)
        self._clear_postprocessor('Проверьте проект и выполните расчёт')
        self._sync_module_availability(False, 'Проверьте проект в препроцессоре')

    def _sync_module_availability(self, processor_ready: bool, message: str) -> None:
        '''Обновляет карточки по проверке файлов и результату текущего расчёта.

        Args:
            processor_ready: Признак успешной проверки актуальности исходных данных.
            message: Состояние процессора или причина недоступности.
        '''
        postprocessor_ready = processor_ready and self._processor_task is None and self.processor_page.result is not None
        if not processor_ready:
            postprocessor_message = message
        elif self._processor_task is not None:
            postprocessor_message = 'Дождитесь завершения расчёта'
        elif self.processor_page.result is None:
            postprocessor_message = 'Выполните расчёт в процессоре'
        else:
            postprocessor_message = 'Расчёт текущей модели выполнен'
        self.project_page.set_availability(processor_ready, postprocessor_ready, message, postprocessor_message)

    def _refresh_processor(self) -> bool:
        '''Проверяет актуальность файлов и отсутствие несохранённого ввода.'''
        if self.current_project is None:
            self.processor_page.set_availability(False, 'Выберите проект')
            self._clear_postprocessor('Выберите проект')
            self._sync_module_availability(False, 'Выберите проект')
            return False
        if self._dirty or self.preprocessor_page.has_pending_edits:
            self.processor_page.set_availability(False, 'Данные изменены. Проверьте проект в препроцессоре')
            self._clear_postprocessor('Данные изменены. Повторите проверку и расчёт')
            self._sync_module_availability(False, 'Данные изменены. Проверьте проект в препроцессоре')
            return False
        try:
            _, fingerprint = self._store.read_for_processor(self.current_project)
            self._processor_signature = self._store.file_signature(self.current_project.path)
        except (OSError, ValueError) as error:
            self._processor_revision += 1
            self._processor_task = None
            prepared_exists = any((self.current_project.path / name).exists() for name in ('project.cnx', 'project.ldx'))
            self.processor_page.set_availability(False, str(error), error=self.current_project.validated or prepared_exists)
            self._clear_postprocessor(str(error), error=self.current_project.validated or prepared_exists)
            self._sync_module_availability(False, str(error))
            return False
        changed = bool(self._processor_fingerprint and fingerprint != self._processor_fingerprint)
        self._processor_fingerprint = fingerprint
        self.processor_page.set_availability(True, 'CNX и LDX проверены', reset=changed)
        if changed:
            self._processor_revision += 1
            self._processor_task = None
            self._clear_postprocessor('Файлы изменены. Повторите расчёт')
        if self._processor_task is not None:
            self.processor_page.set_busy()
        self._sync_module_availability(True, 'CNX и LDX проверены')
        return True

    def calculate_project(self) -> None:
        '''Запускает расчёт актуального снимка в рабочем потоке.'''
        if self._processor_task is not None or not self._refresh_processor():
            return
        self._processor_revision += 1
        self._clear_postprocessor('Выполняется расчёт процессора')
        task = ProcessorTask(self.current_project, self._processor_revision)
        task.signals.finished.connect(self._processor_finished)
        self._processor_task = task
        self.processor_page.set_busy()
        self._sync_module_availability(True, 'CNX и LDX проверены')
        QThreadPool.globalInstance().start(task)

    def _processor_finished(self, revision: int, result, fingerprint: str, error: str) -> None:
        '''Публикует результат только для неизменённого текущего проекта.'''
        if revision != self._processor_revision:
            return
        self._processor_task = None
        if error:
            self.processor_page.set_availability(False, error, reset=True, error=True)
            self._clear_postprocessor(error, error=True)
            self._sync_module_availability(False, error)
            return
        if not self._refresh_processor():
            return
        if fingerprint != self._processor_fingerprint:
            self.processor_page.set_availability(False, 'Данные изменились. Повторите проверку', reset=True)
            self._clear_postprocessor('Данные изменились. Повторите проверку и расчёт')
            self._sync_module_availability(False, 'Данные изменились. Повторите проверку')
            return
        self.processor_page.set_result(result)
        self._sync_module_availability(True, 'CNX и LDX проверены')
        if self.current_page is Page.POSTPROCESSOR:
            self._refresh_postprocessor()

    def _clear_postprocessor(self, message: str, *, error: bool = False) -> None:
        '''Скрывает поля НДС и отзывает запись отчёта устаревшей модели.'''
        self._postprocessor_task = None
        if self._report_task is not None:
            self._report_task.cancelled.set()
            self._report_task = None
        self.postprocessor_page.set_unavailable(message, error=error)

    def _refresh_postprocessor(self) -> bool:
        '''Разрешает показ НДС только для актуального успешного расчёта.'''
        if not self._refresh_processor():
            return False
        if self._processor_task is not None:
            self._clear_postprocessor('Выполняется расчёт процессора')
            return False
        source = self.processor_page.result
        if source is None:
            self._clear_postprocessor('Выполните расчёт в процессоре')
            return False
        result = self.postprocessor_page.result
        if result is not None and result.processor is source:
            return True
        if self._postprocessor_task is not None and self._postprocessor_task.source is source:
            return False
        self.postprocessor_page.set_unavailable('Подготовка эпюр')
        task = PostprocessorTask(source, self._processor_revision, self._processor_fingerprint)
        task.signals.finished.connect(self._postprocessor_finished)
        self._postprocessor_task = task
        QThreadPool.globalInstance().start(task)
        return False

    def _postprocessor_finished(self, revision: int, result, fingerprint: str, error: str) -> None:
        '''Отбрасывает запоздалые функции после изменения модели или файлов.'''
        if revision != self._processor_revision or self._postprocessor_task is None:
            return
        self._postprocessor_task = None
        if error:
            self._clear_postprocessor(error, error=True)
            return
        if not self._refresh_processor():
            return
        if fingerprint != self._processor_fingerprint or result.processor is not self.processor_page.result:
            self._clear_postprocessor('Данные изменены. Повторите расчёт')
            return
        self.postprocessor_page.set_result(result)

    def export_report(self) -> None:
        '''Запускает запись отчёта после повторной проверки актуальности файлов.'''
        if self._report_task is not None or not self._refresh_postprocessor():
            return
        page = self.postprocessor_page
        if not page._refresh_table():
            page.viewsBar.setCurrentIndex(2)
            return
        file_format = page.reportFormatCombo.currentText().lower()
        diagram = ResponsePlot.report_svg(page.result) if file_format == 'html' else ''
        task = ReportTask(self.current_project, page.result, self._processor_revision,
                          self._processor_fingerprint, page.subdivisionsSpin.value(), file_format=file_format,
                          places=page.precisionSpin.value(), step=page.sampling_step(),
                          extrema_only=bool(page.tableModeCombo.currentIndex()), diagram=diagram)
        task.signals.finished.connect(self._report_finished)
        self._report_task = task
        self.postprocessor_page.show_status('Сохранение отчёта')
        QThreadPool.globalInstance().start(task)

    def _report_finished(self, revision: int, path, fingerprint: str, error: str) -> None:
        '''Показывает результат записи только в том проекте, который её запустил.'''
        if revision != self._processor_revision or self._report_task is None:
            return
        self._report_task = None
        if not self._refresh_postprocessor():
            return
        self.postprocessor_page.show_status(error if error else f'Отчёт сохранён - {path.name}', error=bool(error))
        if not error and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.postprocessor_page.show_status(f'Отчёт сохранён - {path}. Не удалось открыть автоматически')

    def _watch_processor_files(self) -> None:
        '''Скрывает старые результаты после внешнего изменения файлов.'''
        if self.current_page not in (Page.PROJECT, Page.PROCESSOR, Page.POSTPROCESSOR) or self.current_project is None:
            return
        try:
            signature = self._store.file_signature(self.current_project.path)
        except ValueError:
            signature = None
        if signature != self._processor_signature:
            self._processor_revision += 1
            self._processor_task = None
            self._processor_signature = signature
            self.processor_page.set_availability(False, 'Файлы изменены. Проверьте проект в препроцессоре', reset=True)
            self._clear_postprocessor('Файлы изменены. Повторите проверку и расчёт')
            self._refresh_processor()

    def _update_title(self) -> None:
        '''Показывает название и наличие несохранённых изменений.'''
        parts = [NAME]
        if self.current_project is not None:
            parts.append(self.current_project.name)
        if self._dirty:
            parts.append('Не сохранено')
        parts.append(AUTHOR)
        self.setWindowTitle(' - '.join(parts))

    def _confirm_project_change(self) -> bool:
        '''Защищает текущие данные при закрытии или смене проекта.

        Returns:
            Разрешение продолжить действие после выбора пользователя.
        '''
        valid_input = self.current_project is None or self.preprocessor_page.commit_pending_edits()
        if not self._dirty and valid_input:
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Изменения проекта')
        dialog.setText('Сохранить изменения проекта')
        save = dialog.addButton('Сохранить', QMessageBox.ButtonRole.AcceptRole)
        discard = dialog.addButton('Не сохранять', QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(save)
        dialog.setEscapeButton(cancel)
        save.setEnabled(valid_input)
        if not valid_input:
            dialog.setInformativeText('Исправьте введённые значения для сохранения')
            dialog.setDefaultButton(cancel)
        dialog.exec()
        if dialog.clickedButton() is save:
            return self.save_project()
        return dialog.clickedButton() is discard

    def _show_error(self, title: str, error: Exception) -> None:
        '''Выводит причину ошибки чтения или записи.

        Args:
            title: Название неудавшейся операции.
            error: Исключение хранилища проекта.
        '''
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setText(title)
        dialog.setInformativeText(str(error))
        dialog.addButton('Закрыть', QMessageBox.ButtonRole.AcceptRole)
        dialog.exec()

    def _update_layout(self) -> None:
        '''Заменяет боковую навигацию компактным меню на узком экране.'''
        compact = self.width() < 1180
        active = self.current_page is not Page.WELCOME
        self.sidebar.setVisible(active and not compact)
        self.sectionButton.setVisible(active and compact)
        self.breadcrumbLabel.setVisible(self.width() >= 760)

    def resizeEvent(self, event) -> None:
        '''Обновляет компоновку под доступную ширину окна.

        Args:
            event: Событие изменения геометрии окна.
        '''
        super().resizeEvent(event)
        if hasattr(self, 'current_page'):
            self._update_layout()

    def closeEvent(self, event) -> None:
        '''Сохраняет возможность отменить закрытие с изменёнными данными.

        Args:
            event: Событие закрытия главного окна.
        '''
        if self._confirm_project_change():
            event.accept()
        else:
            event.ignore()

    def _go_back(self) -> None:
        '''Возвращает пользователя к меню проекта или стартовому экрану.'''
        target = Page.WELCOME if self.current_page in (Page.PROJECT, Page.WELCOME) else Page.PROJECT
        self.navigate(target)
