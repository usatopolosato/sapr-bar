'''Разбирает десятичный ввод одинаково на всех страницах приложения.'''

from decimal import Decimal, InvalidOperation
import re


NUMBER_PATTERN = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')


def parse_number(text: str, positive: bool = False) -> Decimal:
    '''Читает конечное число с точкой или запятой без преобразования в float.

    Args:
        text: Исходная строка поля ввода.
        positive: Требование строго положительного значения.

    Returns:
        Точное значение Decimal.

    Raises:
        ValueError: Неверный формат, диапазон или знак числа.
    '''
    text = text.strip().replace(',', '.')
    if len(text) > 4096 or not NUMBER_PATTERN.fullmatch(text):
        raise ValueError('Введите число например 1.234 или 1.2e8')
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise ValueError('Некорректное число') from error
    if not value.is_finite() or abs(value.as_tuple().exponent) > 1000:
        raise ValueError('Порядок числа должен быть от -1000 до 1000')
    if positive and value <= 0:
        raise ValueError('Значение должно быть больше нуля')
    return value
