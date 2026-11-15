'''Организует навигацию между независимыми страницами приложения.'''

from enum import Enum
from functools import partial
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QActionGroup, QKeySequence, QPalette, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QMainWindow,
    QMenu, QMessageBox, QScrollArea, QToolButton,
)

from ..domain import StructuralModel, validate_model
from ..storage import Project, ProjectStore

from .loader import load_form
from .pages.placeholder import PlaceholderPage
from .pages.preprocessor import PreprocessorPage
from .pages.project_hub import ProjectHubPage
from .pages.welcome import WelcomePage
from .project_dialog import ProjectDialog
from .theme import ThemeColors, ThemeManager, ThemeMode


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
        self.current_page = Page.WELCOME
        self.welcome_page = WelcomePage(self)
        self.project_page = ProjectHubPage(self)
        self.preprocessor_page = PreprocessorPage(self)
        self.processor_page = PlaceholderPage(
            'Этап 2', 'Процессор',
            'Расчёт перемещений узлов', self,
        )
        self.postprocessor_page = PlaceholderPage(
            'Этап 3', 'Постпроцессор',
            'Усилия напряжения и перемещения\nЭпюры и отчёт', self,
        )
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
        self.project_page.preprocessorRequested.connect(partial(self.navigate, Page.PREPROCESSOR))
        self.project_page.processorRequested.connect(partial(self.navigate, Page.PROCESSOR))
        self.project_page.postprocessorRequested.connect(partial(self.navigate, Page.POSTPROCESSOR))
        self.project_page.homeRequested.connect(partial(self.navigate, Page.WELCOME))
        self.processor_page.backRequested.connect(partial(self.navigate, Page.PROJECT))
        self.postprocessor_page.backRequested.connect(partial(self.navigate, Page.PROJECT))
        self.homeButton.clicked.connect(partial(self.navigate, Page.WELCOME))
        self.preprocessor_page.modelChanged.connect(self._model_changed)
        self.preprocessor_page.saveRequested.connect(self.save_project)
        self.preprocessor_page.validateRequested.connect(self.validate_project)
        self._shortcuts = []
        for sequence, action in (
            ('Ctrl+N', self.create_project),
            ('Ctrl+O', self.open_project),
            ('Ctrl+S', self.save_project),
            ('Escape', self._go_back),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(action)
            self._shortcuts.append(shortcut)
        self.navigate(Page.WELCOME)

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

    def _activate_project(self, project: Project) -> None:
        '''Загружает сохранённую модель в рабочее пространство.

        Args:
            project: Проект с расположением и исходными данными.
        '''
        self.current_project = project
        self._dirty = False
        self.preprocessor_page.set_model(project.model)
        self.project_page.set_project_name(project.name)
        self.sidebarProjectLabel.setText(project.name)
        self.sidebarProjectLabel.setToolTip(str(project.path))
        self._settings.setValue('projects/directory', str(project.path.parent))
        self._update_title()
        self.navigate(Page.PROJECT)

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
        '''Сохраняет исходные данные и проверенные данные процессора.

        Returns:
            Признак успешной записи текущей модели.
        '''
        if self.current_project is None or not self.preprocessor_page.commit_pending_edits():
            return False
        model = self.preprocessor_page.model
        issues = validate_model(model)
        try:
            self.current_project = self._store.save(self.current_project, model, validate=not issues)
        except (OSError, ValueError) as error:
            self._show_error('Не удалось сохранить проект', error)
            return False
        self._dirty = False
        self._update_title()
        self.preprocessor_page.show_status('Черновик сохранён' if issues else 'Проект проверен и сохранён')
        return True

    def validate_project(self) -> None:
        '''Записывает проверенные данные для последующего расчёта.'''
        self.save_project()

    def _model_changed(self, model: StructuralModel) -> None:
        '''Отмечает изменения относительно последнего сохранения.

        Args:
            model: Новое состояние редактируемой конструкции.
        '''
        self._dirty = self.current_project is not None and model != self.current_project.model
        self._update_title()

    def _update_title(self) -> None:
        '''Показывает название и наличие несохранённых изменений.'''
        parts = ['САПР BAR']
        if self.current_project is not None:
            parts.append(self.current_project.name)
        if self._dirty:
            parts.append('Не сохранено')
        parts.append('usatopolosato')
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
