'''Измеряет время и память вычислений на воспроизводимой осевой модели.'''

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
import tracemalloc

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from sapr.domain import Bar, StructuralModel
from sapr.domain.processor import AxialProcessor
from sapr.domain.postprocessor import AxialPostprocessor
from sapr.ui.widgets.response_table import ResponseTableModel


def measure(action, repeats):
    '''Возвращает медианное время и пиковую память отдельного запуска.'''
    times = []
    for _ in range(repeats):
        start = perf_counter()
        action()
        times.append(perf_counter() - start)
    tracemalloc.start()
    action()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {'seconds': median(times), 'peak_mib': peak / 1024 ** 2}


def main():
    '''Проверяет одинаковые сценарии до и после изменения кода.'''
    parser = argparse.ArgumentParser()
    parser.add_argument('--bars', type=int, default=10000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.bars <= 10000 or args.repeats < 1:
        parser.error('Требуется от 1 до 10000 стержней и хотя бы один повтор')
    app = QApplication.instance() or QApplication([])
    count = args.bars
    bar = Bar(Decimal('1'), Decimal('0.001'), Decimal('2e11'), Decimal('1.6e8'))
    model = StructuralModel((bar,) * count, (Decimal(0),) * count + (Decimal('10000'),),
                            (Decimal('100'),) * count, (True,) + (False,) * count)
    processor = AxialProcessor()
    solution = processor.solve(model)
    postprocessor = AxialPostprocessor()

    def prepare_fields():
        '''Воспроизводит подготовку функций и характерных точек рабочего потока.'''
        result = postprocessor.analyze(solution)
        for response in result.bars:
            response.critical_positions()
            response.extrema('u')
            _ = response.stress_ratio
        return result

    result = prepare_fields()

    def repaint_table():
        '''Запрашивает роли Qt для видимых строк при повторных перерисовках.'''
        table = ResponseTableModel(result, subdivisions=1000)
        for _ in range(8):
            for row in range(40):
                for column in range(5):
                    index = table.index(row, column)
                    for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole,
                                 Qt.ItemDataRole.BackgroundRole):
                        table.data(index, role)
        table.deleteLater()
        app.processEvents()

    measurements = {
        'bars': count,
        'repeats': args.repeats,
        'solve': measure(lambda: processor.solve(model), args.repeats),
        'postprocess': measure(prepare_fields, args.repeats),
        'table': measure(repaint_table, args.repeats),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(measurements, indent=2), encoding='utf-8')
    print(json.dumps(measurements, indent=2))


if __name__ == '__main__':
    main()
