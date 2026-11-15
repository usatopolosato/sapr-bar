'''Загружает формы Qt Designer и общую тему приложения.'''

from pathlib import Path
from string import Template
from collections.abc import Mapping

from PyQt6 import uic
from PyQt6.QtWidgets import QWidget


RESOURCE_ROOT = Path(__file__).resolve().parents[1] / 'resources'


def load_form(name: str, target: QWidget) -> None:
    '''Загружает форму в существующий экземпляр виджета.

    Args:
        name: Имя файла формы внутри каталога ресурсов.
        target: Виджет, которому принадлежат элементы формы.
    '''
    uic.loadUi(str(RESOURCE_ROOT / 'forms' / name), target)


def read_theme(colors: Mapping[str, str]) -> str:
    '''Подставляет цвета в общую таблицу стилей.

    Args:
        colors: Именованные цвета выбранной темы.

    Returns:
        Строка QSS в кодировке UTF-8.
    '''
    source = (RESOURCE_ROOT / 'styles' / 'theme.qss').read_text(encoding='utf-8')
    return Template(source).substitute(colors)
