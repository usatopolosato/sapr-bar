'''Организует навигацию между независимыми страницами приложения.'''

from enum import Enum
from functools import partial

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation
from PyQt6.QtGui import QActionGroup, QKeySequence, QShortcut
from PyQt6.QtWidgets import QButtonGroup, QDialog, QGraphicsOpacityEffect, QMainWindow, QMenu, QToolButton

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
    '''

    def __init__(self, theme_manager: ThemeManager) -> None:
        super().__init__()
        load_form('main_window.ui', self)
        self._theme_manager = theme_manager
        self.project_names = ['Демонстрационный проект']
        self.current_project = ''
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
        for page in self._pages.values():
            self.pageStack.addWidget(page)
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
        self.welcome_page.createRequested.connect(self.create_project)
        self.welcome_page.openRequested.connect(self.open_project)
        self.project_page.preprocessorRequested.connect(partial(self.navigate, Page.PREPROCESSOR))
        self.project_page.processorRequested.connect(partial(self.navigate, Page.PROCESSOR))
        self.project_page.postprocessorRequested.connect(partial(self.navigate, Page.POSTPROCESSOR))
        self.project_page.homeRequested.connect(partial(self.navigate, Page.WELCOME))
        self.processor_page.backRequested.connect(partial(self.navigate, Page.PROJECT))
        self.postprocessor_page.backRequested.connect(partial(self.navigate, Page.PROJECT))
        self.homeButton.clicked.connect(partial(self.navigate, Page.WELCOME))
        self._fade_effect = QGraphicsOpacityEffect(self.pageStack)
        self._fade_effect.setOpacity(1)
        self.pageStack.setGraphicsEffect(self._fade_effect)
        self._transition = QPropertyAnimation(self._fade_effect, b'opacity', self)
        self._transition.setDuration(160)
        self._transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._shortcuts = []
        for sequence, action in (
            ('Ctrl+N', self.create_project),
            ('Ctrl+O', self.open_project),
            ('Escape', self._go_back),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(action)
            self._shortcuts.append(shortcut)
        self.navigate(Page.WELCOME, animate=False)

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

    def navigate(self, page: Page, checked: bool = False, *, animate: bool = True) -> None:
        '''Переключает страницу и согласует элементы навигации.

        Args:
            page: Целевая страница.
            checked: Состояние кнопки из сигнала Qt.
            animate: Признак плавного появления страницы.
        '''
        self._transition.stop()
        self.current_page = page
        self.sidebar.setVisible(page is not Page.WELCOME)
        self.breadcrumbLabel.setText(page.value)
        self.pageStack.setCurrentWidget(self._pages[page])
        if page in self._nav_buttons:
            self._nav_buttons[page].setChecked(True)
        self._fade_effect.setOpacity(1)
        if animate and self.isVisible():
            self._transition.setStartValue(0.3)
            self._transition.setEndValue(1)
            self._transition.start()

    def _activate_project(self, name: str) -> None:
        '''Выбирает рабочее пространство текущего сеанса.

        Args:
            name: Имя проекта для отображения в интерфейсе.
        '''
        self.current_project = name
        if name not in self.project_names:
            self.project_names.append(name)
        self.project_page.set_project_name(name)
        self.sidebarProjectLabel.setText(name)
        self.navigate(Page.PROJECT)

    def create_project(self) -> None:
        '''Открывает диалог имени нового рабочего пространства.'''
        dialog = ProjectDialog(self.project_names, create=True, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._activate_project(dialog.project_name())

    def open_project(self) -> None:
        '''Открывает список проектов текущего сеанса.'''
        dialog = ProjectDialog(self.project_names, create=False, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._activate_project(dialog.project_name())

    def _go_back(self) -> None:
        '''Возвращает пользователя к меню проекта или стартовому экрану.'''
        target = Page.WELCOME if self.current_page in (Page.PROJECT, Page.WELCOME) else Page.PROJECT
        self.navigate(target)
