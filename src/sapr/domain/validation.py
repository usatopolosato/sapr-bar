"""Проверяет исходные данные задачи растяжения и сжатия."""

from dataclasses import dataclass
from decimal import Decimal

from .model import StructuralModel


@dataclass(frozen=True)
class ValidationIssue:
    """
    Описывает одну ошибку исходных данных.

    Attributes:
        message: Сообщение для пользователя.
        field: Имя проверяемого параметра.
        index: Номер элемента с нуля или отсутствие номера.
    """

    message: str
    field: str = ""
    index: int | None = None


class ModelValidationError(ValueError):
    """Передаёт ошибки, запрещающие подготовку данных для процессора."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        """Сохраняет полный список обнаруженных ошибок."""
        self.issues = issues
        super().__init__("\n".join(issue.message for issue in issues))


def validate_model(model: StructuralModel, *, ready: bool = True) -> tuple[ValidationIssue, ...]:
    """Проверяет размеры массивов, значения параметров и наличие опоры.

    Args:
        model: Исходные данные в единицах СИ.
        ready: Требовать непустую конструкцию и хотя бы одну опору для расчёта.

    Returns:
        Ошибки в порядке проверки параметров.
    """
    issues: list[ValidationIssue] = []
    count = len(model.bars)
    if count == 0 and ready:
        issues.append(ValidationIssue("Добавьте хотя бы один стержень", "bars"))
    if count > 10000:
        issues.append(ValidationIssue("Допустимо не более 10000 стержней", "bars"))
    node_count = count + 1 if count else 0
    fields = (
        ("length_m", "L"), ("area_m2", "A"), ("modulus_pa", "E"),
        ("allowable_stress_pa", "Допускаемое напряжение"),
    )
    for index, bar in enumerate(model.bars):
        for field, label in fields:
            value = getattr(bar, field)
            if not isinstance(value, Decimal) or not value.is_finite():
                issues.append(ValidationIssue(
                    f"Стержень {index + 1} - {label} должно быть конечным числом",
                    field, index,
                ))
            elif value <= 0:
                issues.append(ValidationIssue(
                    f"Стержень {index + 1} - {label} должно быть больше нуля",
                    field, index,
                ))
    for field, values, expected, label in (
            ("nodal_forces", model.nodal_forces, node_count, "Узловые силы"),
            ("distributed_loads", model.distributed_loads, count, "Погонные нагрузки"),
    ):
        if len(values) != expected:
            relation = ("Число узлов должно равняться числу стержней + 1. "
                        if field == "nodal_forces" and count else "")
            issues.append(ValidationIssue(
                f"{label} - получено {len(values)}, требуется {expected}. {relation}".rstrip(),
                field))
        for index, value in enumerate(values):
            if not isinstance(value, Decimal) or not value.is_finite():
                issues.append(ValidationIssue(
                    f"{label} {index + 1} - требуется конечное число", field, index,
                ))
    if len(model.supports) != node_count:
        issues.append(ValidationIssue(
            f"Опоры - получено {len(model.supports)} признаков, требуется {node_count}, по одному на каждый узел",
            "supports"))
    elif any(not isinstance(value, bool) for value in model.supports):
        issues.append(ValidationIssue(
            "Признак опоры должен быть логическим значением true или false для каждого узла",
            "supports"))
    elif ready and count and not any(model.supports):
        issues.append(ValidationIssue("Задайте хотя бы одну жёсткую опору", "supports"))
    return tuple(issues)
