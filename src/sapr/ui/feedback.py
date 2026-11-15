'''Оформляет сообщения и ошибочный ввод независимо от выбранной темы.'''

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QLineEdit, QWidget


def _set_property(widget: QWidget, name: str, value: object) -> None:
    '''Обновляет стиль виджета после изменения свойства.

    Args:
        widget: Виджет с динамическим оформлением.
        name: Название свойства таблицы стилей.
        value: Новое значение свойства.
    '''
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.updateGeometry()
    widget.update()


def show_feedback(label: QLabel, text: str, *, error: bool = False) -> None:
    '''Показывает сообщение с явным признаком ошибки.

    Args:
        label: Область сообщения.
        text: Сообщение или пустая строка для скрытия области.
        error: Признак ошибки ввода, проверки или вычисления.
    '''
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    _set_property(label, 'role', 'error' if error and text else 'muted')
    label.setText(text)
    label.setVisible(bool(text))


def set_input_error(field: QLineEdit, error: bool) -> None:
    '''Выделяет поле до исправления или отмены неверного значения.

    Args:
        field: Поле ввода исходного значения.
        error: Наличие ошибки в этом поле.
    '''
    _set_property(field, 'invalid', error)
