'''Форматирует физические величины без изменения значений Decimal.'''

from decimal import Decimal


def format_quantity(value: Decimal, scientific: bool = False) -> str:
    '''Возвращает обычную или научную десятичную запись.

    Args:
        value: Точное значение физической величины в СИ.
        scientific: Признак экспоненциального представления.

    Returns:
        Запись вида 210000000000 или 2.1e11 без преобразования во float.
    '''
    if value.is_zero():
        return '0'
    if scientific:
        mantissa, exponent = format(value, 'e').split('e')
        if '.' in mantissa:
            mantissa = mantissa.rstrip('0').rstrip('.')
        return f'{mantissa}e{int(exponent)}'
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result
