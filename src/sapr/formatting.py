'''Форматирует физические величины для интерфейса и текстовых отчётов.'''

from decimal import Decimal, ROUND_HALF_EVEN, localcontext


def format_result(value: Decimal, places: int = 6) -> str:
    '''Выводит одинаковое число дробных знаков, сохраняя малые порядки.

    Args:
        value: Значение в системе СИ.
        places: Число знаков после точки от 0 до 12.

    Returns:
        Обычная или экспоненциальная запись с фиксированной точностью показа.
    '''
    if not value.is_finite() or not 0 <= places <= 12:
        raise ValueError('Требуется конечное число и точность от 0 до 12')
    with localcontext() as context:
        context.rounding = ROUND_HALF_EVEN
        if value.is_zero() or -places <= value.adjusted() <= 6:
            return format(value.copy_abs() if value.is_zero() else value, f'.{places}f')
        mantissa, exponent = format(value, f'.{places}e').split('e')
        return f'{mantissa}e{int(exponent)}'


def format_quantity(value: Decimal, compact: bool = False, *, places: int | None = None) -> str:
    '''Возвращает точную или краткую запись физической величины.

    Args:
        value: Точное значение физической величины в СИ.
        compact: Признак краткой записи с округлением только для показа.
        places: Число дробных знаков для отдельного режима отображения.

    Returns:
        В точном режиме возвращается полная десятичная запись.
        Краткий режим оставляет до шести знаков после точки в мантиссе.
        Если результат помещается в четыре целых и шесть дробных разрядов,
        он выводится без экспоненты. Исходное значение не изменяется.

    Raises:
        ValueError: Передано бесконечное или неопределённое значение.
    '''
    if not value.is_finite():
        raise ValueError('Физическая величина должна быть конечной')
    if value.is_zero():
        return '0'
    if places is not None:
        if not 0 <= places <= 12:
            raise ValueError('Точность отображения должна быть от 0 до 12')
        with localcontext() as context:
            context.rounding = ROUND_HALF_EVEN
            context.prec = max(28, len(value.as_tuple().digits), value.adjusted() + places + 2)
            if -places <= value.adjusted() <= 6:
                rounded = value.quantize(Decimal(1).scaleb(-places))
                return format_quantity(rounded)
            mantissa, exponent = format(value, f'.{places}e').split('e')
        return f'{mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa}e{int(exponent)}'
    if compact:
        with localcontext() as context:
            context.rounding = ROUND_HALF_EVEN
            mantissa, exponent_text = format(value, '.6e').split('e')
        mantissa = mantissa.rstrip('0').rstrip('.')
        exponent = int(exponent_text)
        if -3 <= exponent <= 3:
            ordinary = format(Decimal(f'{mantissa}e{exponent}'), 'f')
            ordinary = ordinary.rstrip('0').rstrip('.') if '.' in ordinary else ordinary
            fractional = ordinary.partition('.')[2]
            if len(fractional) <= 6:
                return ordinary
        return f'{mantissa}e{exponent}'
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result
