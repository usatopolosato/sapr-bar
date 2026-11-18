'''Разбирает десятичный ввод одинаково на всех страницах приложения.'''

from decimal import Decimal, InvalidOperation, localcontext
import re


NUMBER_PATTERN = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')


def parse_number(text: str, positive: bool = False) -> Decimal:
    '''Читает десятичное число или дробь без преобразования в float.

    Args:
        text: Исходная строка поля ввода.
        positive: Требование строго положительного значения.

    Returns:
        Значение Decimal. Бесконечная дробь округляется минимум до 60 значащих цифр.

    Raises:
        ValueError: Неверный формат, диапазон или знак числа.
    '''
    text = text.strip().replace(',', '.')
    parts = text.split('/')
    if len(parts) > 2 or len(text) > 4096 or any(not NUMBER_PATTERN.fullmatch(part.strip()) for part in parts):
        raise ValueError('Введите число например 1.234, 1.2e8 или 3/5')
    try:
        values = [Decimal(part.strip()) for part in parts]
    except InvalidOperation as error:
        raise ValueError('Некорректное число') from error
    if any(not value.is_finite() or abs(value.as_tuple().exponent) > 1000 for value in values):
        raise ValueError('Порядок числа должен быть от -1000 до 1000')
    value = values[0]
    if len(values) == 2:
        if not values[1]:
            raise ValueError('Знаменатель дроби не может быть нулём')
        with localcontext() as context:
            context.prec = max(60, sum(len(number.as_tuple().digits) for number in values) + 30)
            value /= values[1]
    if not value.is_finite() or abs(value.as_tuple().exponent) > 1000:
        raise ValueError('Порядок числа должен быть от -1000 до 1000')
    if positive and value <= 0:
        raise ValueError('Значение должно быть больше нуля')
    return value
