'''Управляет темой приложения и согласованными цветами графической сцены.'''

import sys
from dataclasses import asdict, dataclass
from enum import Enum

from PyQt6.QtCore import QObject, QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from .loader import read_theme


class ThemeMode(str, Enum):
    '''Определяет пользовательский режим оформления.'''

    SYSTEM = 'system'
    LIGHT = 'light'
    DARK = 'dark'


@dataclass(frozen=True)
class ThemeColors:
    '''Хранит цвета элементов интерфейса и расчётной схемы.'''

    window: str
    panel: str
    surface: str
    border: str
    text: str
    muted: str
    error_background: str
    error_border: str
    error_text: str
    accent: str
    accent_text: str
    accent_hover: str
    accent_pressed: str
    hover: str
    pressed: str
    selection: str
    selection_text: str
    input_background: str
    disabled: str
    alternate: str
    scrollbar: str
    canvas: str
    grid: str
    axis: str
    dimension: str
    bar_fill: str
    bar_selected: str
    bar_border: str
    bar_selected_border: str
    bar_text: str
    bar_selected_text: str
    force: str
    distributed: str
    node_fill: str
    node_border: str


LIGHT_COLORS = ThemeColors(
    window='#f5f6f8', panel='#ffffff', surface='#f0f3f6', border='#d5dde5',
    text='#202a36', muted='#5c6b7b', accent='#187f69', accent_text='#ffffff',
    error_background='#fff2f2', error_border='#d96b6b', error_text='#9c2f2f',
    accent_hover='#116d59', accent_pressed='#0e5949', hover='#eaf0f4',
    pressed='#dfe8ee', selection='#e0f0eb', selection_text='#145c4b',
    input_background='#f8fafb', disabled='#8a95a1', alternate='#f8fafb',
    scrollbar='#aebbc7', canvas='#f8fafb', grid='#dbe3e9', axis='#91a4b5',
    dimension='#8097aa', bar_fill='#e6edf3', bar_selected='#d3eae2',
    bar_border='#8ba0b3', bar_selected_border='#187f69', bar_text='#40596d',
    bar_selected_text='#185a49', force='#a55d19', distributed='#236e88',
    node_fill='#ffffff', node_border='#a6b7c6',
)

DARK_COLORS = ThemeColors(
    window='#10151d', panel='#171f2a', surface='#121923', border='#2a3544',
    text='#e8edf5', muted='#9aa8b9', accent='#82d6bb', accent_text='#102c24',
    error_background='#352126', error_border='#b86068', error_text='#ffb8be',
    accent_hover='#9ee4cc', accent_pressed='#64bda0', hover='#233042',
    pressed='#1b2735', selection='#233e39', selection_text='#b7eddb',
    input_background='#131c27', disabled='#627083', alternate='#1b2531',
    scrollbar='#44536a', canvas='#141d28', grid='#253446', axis='#4b627a',
    dimension='#637e97', bar_fill='#243447', bar_selected='#2c5148',
    bar_border='#688096', bar_selected_border='#82d6bb', bar_text='#becfdf',
    bar_selected_text='#c5f1e1', force='#e7b37b', distributed='#82cfda',
    node_fill='#182634', node_border='#526b81',
)


class ThemeManager(QObject):
    '''Применяет выбранную тему и отслеживает оформление системы.

    Args:
        app: Приложение Qt, получающее палитру и стили.
        settings: Хранилище выбора темы или стандартные настройки приложения.
        persist: Признак чтения и сохранения пользовательского выбора.
    '''

    changed = pyqtSignal(object)

    def __init__(self, app: QApplication, settings: QSettings | None = None, persist: bool = True) -> None:
        super().__init__(app)
        self._app = app
        self._settings = settings if settings is not None else QSettings('usatopolosato', 'sapr-bar')
        self._persist = persist
        self._fallback = ThemeMode.DARK if app.palette().color(QPalette.ColorRole.Window).lightness() < 128 else ThemeMode.LIGHT
        stored = self._settings.value('appearance/theme', ThemeMode.SYSTEM.value) if persist else ThemeMode.SYSTEM.value
        try:
            self._mode = ThemeMode(stored)
        except ValueError:
            self._mode = ThemeMode.SYSTEM
        self._system = self._read_system_mode()
        self._resolved_mode = self._system if self._mode is ThemeMode.SYSTEM else self._mode
        self._colors = DARK_COLORS if self._resolved_mode is ThemeMode.DARK else LIGHT_COLORS
        app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        self._apply()

    @property
    def mode(self) -> ThemeMode:
        '''Возвращает пользовательский режим оформления.'''
        return self._mode

    @property
    def resolved_mode(self) -> ThemeMode:
        '''Возвращает фактически применённую светлую или тёмную тему.'''
        return self._resolved_mode

    @property
    def colors(self) -> ThemeColors:
        '''Возвращает текущие цвета интерфейса и сцены.'''
        return self._colors

    def set_mode(self, mode: ThemeMode) -> None:
        '''Меняет тему и при необходимости сохраняет выбор.

        Args:
            mode: Системное, светлое или тёмное оформление.
        '''
        mode = ThemeMode(mode)
        if mode is self._mode:
            return
        self._mode = mode
        if mode is ThemeMode.SYSTEM:
            self._system = self._read_system_mode()
        if self._persist:
            self._settings.setValue('appearance/theme', mode.value)
            self._settings.sync()
        self._apply()

    def refresh_system_theme(self) -> None:
        '''Повторно считывает системную тему без изменения явного выбора.'''
        self._system = self._read_system_mode()
        if self._mode is ThemeMode.SYSTEM:
            self._apply()

    def _read_system_mode(self) -> ThemeMode:
        '''Определяет тему системы независимо от палитры приложения.

        Returns:
            Светлая или тёмная системная тема.
        '''
        scheme = self._app.styleHints().colorScheme()
        if scheme is Qt.ColorScheme.Dark:
            return ThemeMode.DARK
        if scheme is Qt.ColorScheme.Light:
            return ThemeMode.LIGHT
        if sys.platform == 'win32':
            try:
                import winreg

                path = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                    value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
                return ThemeMode.LIGHT if value else ThemeMode.DARK
            except OSError:
                pass
        return self._fallback

    def _on_system_scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        '''Обрабатывает смену системной темы.

        Args:
            scheme: Новая цветовая схема платформы.
        '''
        if scheme is Qt.ColorScheme.Dark:
            self._system = ThemeMode.DARK
        elif scheme is Qt.ColorScheme.Light:
            self._system = ThemeMode.LIGHT
        else:
            self._system = self._read_system_mode()
        if self._mode is ThemeMode.SYSTEM:
            self._apply()

    def _apply(self) -> None:
        '''Обновляет палитру, стили и подписчиков графической сцены.'''
        self._resolved_mode = self._system if self._mode is ThemeMode.SYSTEM else self._mode
        self._colors = DARK_COLORS if self._resolved_mode is ThemeMode.DARK else LIGHT_COLORS
        colors = self._colors
        palette = QPalette()
        for role, color in (
            (QPalette.ColorRole.Window, colors.window),
            (QPalette.ColorRole.WindowText, colors.text),
            (QPalette.ColorRole.Base, colors.panel),
            (QPalette.ColorRole.AlternateBase, colors.alternate),
            (QPalette.ColorRole.Text, colors.text),
            (QPalette.ColorRole.Button, colors.surface),
            (QPalette.ColorRole.ButtonText, colors.text),
            (QPalette.ColorRole.Highlight, colors.selection),
            (QPalette.ColorRole.HighlightedText, colors.selection_text),
            (QPalette.ColorRole.ToolTipBase, colors.panel),
            (QPalette.ColorRole.ToolTipText, colors.text),
            (QPalette.ColorRole.Link, colors.accent),
            (QPalette.ColorRole.PlaceholderText, colors.muted),
            (QPalette.ColorRole.Light, colors.panel),
            (QPalette.ColorRole.Midlight, colors.surface),
            (QPalette.ColorRole.Mid, colors.border),
            (QPalette.ColorRole.Dark, colors.border),
            (QPalette.ColorRole.Shadow, colors.border),
        ):
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors.disabled))
        self._app.setPalette(palette)
        self._app.setStyleSheet(read_theme(asdict(colors)))
        self.changed.emit(colors)
