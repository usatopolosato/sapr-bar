"""Восстанавливает осевые силы, напряжения и перемещения в сечениях."""

from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, localcontext
from functools import cached_property
from operator import attrgetter

from .model import Bar
from .processor import CalculationError, ProcessorResult
from .validation import ModelValidationError, validate_model

ZERO = Decimal("0")
TWO = Decimal("2")


def _real_roots(a: Decimal, b: Decimal, c: Decimal) -> tuple[Decimal, ...]:
    """Находит изолированные вещественные корни a*x² + b*x + c."""
    if a == 0:
        if b == 0:
            return ()
        return (-c / b,)
    discriminant = b * b - Decimal(4) * a * c
    if discriminant < 0:
        return ()
    root = discriminant.sqrt()
    # Складываем числа одного знака, чтобы сохранить точность малого корня.
    if b < 0:
        root = -root
    numerator = -(b + root) / TWO
    if numerator == 0:
        return (-b / (TWO * a),)
    return numerator / a, c / numerator


@dataclass(frozen=True, slots=True)
class SectionResult:
    """Хранит компоненты НДС выбранного сечения в единицах СИ."""

    bar_index: int
    x_m: Decimal
    force_n: Decimal
    stress_pa: Decimal
    displacement_m: Decimal

    def value(self, component: str) -> Decimal:
        """Возвращает значение компоненты N, sigma или u.

        Args:
            component: Обозначение продольной силы, напряжения или перемещения.

        Returns:
            Значение без округления для отображения.
        """
        if component == "N":
            return self.force_n
        if component == "sigma":
            return self.stress_pa
        if component == "u":
            return self.displacement_m
        raise KeyError(component)


@dataclass(frozen=True)
class BarResponse:
    """Задаёт аналитическое решение на одном стержне.

    Attributes:
        index: Индекс стержня с нуля.
        geometry: Исходные свойства стержня в СИ.
        start_m: Глобальная координата начала стержня в метрах.
        q_n_per_m: Постоянная погонная нагрузка в Н/м.
        u_left_m: Перемещение начального узла в метрах.
        u_right_m: Перемещение конечного узла в метрах.
        force_origin_n: Продольная сила в начале стержня в ньютонах.
        precision: Рабочая точность Decimal.
    """

    index: int
    geometry: Bar
    start_m: Decimal
    q_n_per_m: Decimal
    u_left_m: Decimal
    u_right_m: Decimal
    force_origin_n: Decimal
    precision: int

    def at(self, x_m: Decimal) -> SectionResult:
        """Вычисляет НДС по локальной координате без интерполяции таблицы.

        Args:
            x_m: Конечная координата Decimal в пределах от нуля до L.

        Returns:
            Значения силы, напряжения и перемещения в данном сечении.

        Raises:
            ValueError: Координата некорректна или находится вне стержня.
        """
        length = self.geometry.length_m
        if not isinstance(x_m, Decimal) or not x_m.is_finite() or not ZERO <= x_m <= length:
            raise ValueError(f"Координата x должна быть от 0 до {length} м")
        with localcontext(Context(prec=self.precision)):
            force = self.force_origin_n - self.q_n_per_m * x_m
            stress = force / self.geometry.area_m2
            if x_m == ZERO:
                displacement = self.u_left_m
            elif x_m == length:
                displacement = self.u_right_m
            else:
                rigidity = self.geometry.modulus_pa * self.geometry.area_m2
                displacement = self.u_left_m + x_m / length * (self.u_right_m - self.u_left_m)
                displacement += self.q_n_per_m * x_m * (length - x_m) / (TWO * rigidity)
            return SectionResult(self.index, x_m, force, stress, displacement)

    @cached_property
    def _critical(self) -> tuple[Decimal, ...]:
        """Находит границы, экстремум u, нули функций и пересечения допуска."""
        with localcontext(Context(prec=self.precision)):
            length, q = self.geometry.length_m, self.q_n_per_m
            points = {ZERO, length}
            candidates = []
            if q:
                candidates.append(self.force_origin_n / q)
                limit = self.geometry.allowable_stress_pa * self.geometry.area_m2
                candidates.extend(
                    ((self.force_origin_n - limit) / q, (self.force_origin_n + limit) / q))
            a = -q / TWO
            b = self.force_origin_n
            c = self.geometry.modulus_pa * self.geometry.area_m2 * self.u_left_m
            # Нули перемещения удовлетворяют уравнению EA*u(x) = 0.
            candidates.extend(_real_roots(a, b, c))
            points.update(value for value in candidates if ZERO < value < length)
            return tuple(sorted(points))

    def critical_positions(self) -> tuple[Decimal, ...]:
        """Возвращает характерные точки независимо от плотности таблицы."""
        return self._critical

    def sample_positions(self, subdivisions: int = 10) -> tuple[Decimal, ...]:
        """Дополняет равномерную сетку аналитически найденными точками.

        Args:
            subdivisions: Число интервалов от 1 до 1000.

        Returns:
            Упорядоченные уникальные локальные координаты Decimal.
        """
        if type(subdivisions) is not int or not 1 <= subdivisions <= 1000:
            raise ValueError("Число разбиений должно быть от 1 до 1000")
        with localcontext(Context(prec=self.precision)):
            points = {self.geometry.length_m * index / subdivisions for index in
                      range(subdivisions + 1)}
            points.update(self._critical)
            return tuple(sorted(points))

    @cached_property
    def _extrema(self) -> dict[str, tuple[SectionResult, SectionResult]]:
        """Сохраняет экстремумы функций без построения сетки отсчётов."""
        left, right = self.at(ZERO), self.at(self.geometry.length_m)
        points = [left, right]
        force_extrema = (min(points, key=attrgetter("force_n")),
                         max(points, key=attrgetter("force_n")))
        if self.q_n_per_m:
            with localcontext(Context(prec=self.precision)):
                root = self.force_origin_n / self.q_n_per_m
                if ZERO < root < self.geometry.length_m:
                    points.append(self.at(root))
        return {"N": force_extrema, "sigma": force_extrema,
                "u": (min(points, key=attrgetter("displacement_m")),
                      max(points, key=attrgetter("displacement_m")))}

    def extrema(self, component: str) -> tuple[SectionResult, SectionResult]:
        """Возвращает минимум и максимум функции по аналитическим кандидатам."""
        return self._extrema[component]

    @cached_property
    def max_abs_stress_pa(self) -> Decimal:
        """Возвращает наибольшее по модулю напряжение на стержне."""
        return max(point.stress_pa.copy_abs() for point in self.extrema("sigma"))

    @cached_property
    def stress_ratio(self) -> Decimal:
        """Возвращает отношение максимального напряжения к допускаемому."""
        with localcontext(Context(prec=self.precision)):
            return self.max_abs_stress_pa / self.geometry.allowable_stress_pa

    @property
    def stress_status(self) -> str:
        """Различает запас прочности, достижение допуска и превышение."""
        allowable = self.geometry.allowable_stress_pa
        if self.max_abs_stress_pa > allowable:
            return "Превышение"
        return "На пределе" if self.max_abs_stress_pa == allowable else "В пределах допуска"


@dataclass(frozen=True)
class PostprocessorResult:
    """Связывает аналитические решения с исходным результатом процессора."""

    processor: ProcessorResult
    bars: tuple[BarResponse, ...]

    @property
    def precision(self) -> int:
        """Возвращает общую рабочую точность Decimal."""
        return self.processor.precision

    def at(self, bar_index: int, x_m: Decimal) -> SectionResult:
        """Вычисляет сечение выбранного стержня с проверкой его индекса."""
        if type(bar_index) is not int or not 0 <= bar_index < len(self.bars):
            raise ValueError("Выберите существующий стержень")
        return self.bars[bar_index].at(x_m)


class AxialPostprocessor:
    """Строит функции НДС по узловым перемещениям за линейное время."""

    def analyze(self, processor: ProcessorResult) -> PostprocessorResult:
        """Восстанавливает коэффициенты каждого стержня в арифметике Decimal.

        Args:
            processor: Результат успешного расчёта актуальной модели.

        Returns:
            Аналитические функции, сохраняющие исходную точность.

        Raises:
            CalculationError: Результат не содержит допустимый вектор перемещений.
        """
        model = processor.model
        issues = validate_model(model)
        if issues:
            raise ModelValidationError(issues)
        if (len(processor.displacements) != len(model.supports)
                or any(not isinstance(value, Decimal) or not value.is_finite() for value in
                       processor.displacements)
                or any(
                    value != ZERO for value, fixed in zip(processor.displacements, model.supports)
                    if fixed)):
            raise CalculationError("Некорректный вектор перемещений. Повторите расчёт")
        try:
            with localcontext(Context(prec=processor.precision)):
                starts = model.node_positions_m
                bars = []
                for index, (bar, q) in enumerate(zip(model.bars, model.distributed_loads)):
                    left, right = processor.displacements[index:index + 2]
                    force = processor.stiffnesses[index] * (right - left) + processor.end_loads[
                        index]
                    bars.append(BarResponse(index, bar, starts[index], q, left, right, force,
                                            processor.precision))
                return PostprocessorResult(processor, tuple(bars))
        except DecimalException as error:
            raise CalculationError(
                "Числовой диапазон превышает возможности постпроцессора") from error
