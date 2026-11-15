'''Оформляет обозначения расчёта с нижними индексами в тексте Qt.'''

from html import escape
import re


def formula_html(text: str) -> str:
    '''Преобразует обозначения узлов и коэффициентов в математическую запись.

    Args:
        text: Обычный текст формулы с обозначениями Δ2, b2 и A2,3.

    Returns:
        Безопасный HTML с нижними индексами. Двузначные номера матрицы
        разделяются запятой, чтобы пары 1 и 23, 12 и 3 различались.
    '''
    escaped = escape(text)

    def coefficient(match: re.Match) -> str:
        '''Разделяет номера строки и столбца при неоднозначной записи.'''
        row, column = match.groups()
        index = row + column if len(row) == len(column) == 1 else f'{row},{column}'
        return f'<i>a</i><sub>{index}</sub>'

    escaped = re.sub(r'\bA(\d+),(\d+)\b', coefficient, escaped)
    escaped = re.sub(r'(?<![\w])([ΔbkqFL])(\d+)\b', r'\1<sub>\2</sub>', escaped)
    return '<div style="line-height: 125%;">' + escaped.replace('\n', '<br>') + '</div>'
