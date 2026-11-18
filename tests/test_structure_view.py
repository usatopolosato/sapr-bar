'''Проверяет направление нагрузок и геометрию расчётной схемы.'''

import os
import unittest
from decimal import Decimal

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QGraphicsLineItem

from src.sapr.domain import Bar, StructuralModel
from src.sapr.ui.theme import LIGHT_COLORS
from src.sapr.ui.widgets.structure_view import StructureView


class StructureViewTests(unittest.TestCase):
    '''Проверяет отображение модели независимо от страницы редактора.'''

    @classmethod
    def setUpClass(cls) -> None:
        '''Создаёт приложение Qt для проверки графической сцены.'''
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        '''Создаёт схему с исходными значениями Decimal.'''
        self.model = StructuralModel(
            bars=(
                Bar(Decimal('1'), Decimal('0.001'), Decimal('2e11'), Decimal('1e8')),
                Bar(Decimal('2'), Decimal('0.002'), Decimal('2e11'), Decimal('1e8')),
            ),
            nodal_forces=(Decimal('3'), Decimal('0'), Decimal('-4')),
            distributed_loads=(Decimal('-2'), Decimal('5')),
            supports=(True, False, True),
        )
        self.view = StructureView()
        self.view.resize(1000, 440)
        self.view.set_model(self.model)

    def tearDown(self) -> None:
        '''Освобождает графические элементы после проверки.'''
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def test_dimensions_follow_si_values(self) -> None:
        '''Проверяет пропорции стержней и точность исходных величин.'''
        first, second = (bar.rect() for bar in self.view._bars)
        self.assertAlmostEqual(second.width() / first.width(), 2)
        self.assertAlmostEqual(second.height() / first.height(), 2)
        self.assertEqual(self.model.bars[0].length_m, Decimal('1'))
        labels = [item.text() for item in self.view.scene().items() if hasattr(item, 'text')]
        self.assertIn('L = 1 м', labels)
        self.assertEqual(sum(text.startswith('L = ') for text in labels), len(self.model.bars))
        self.assertIn('F = 4 Н', labels)
        self.assertIn('q = 2 Н/м', labels)
        self.assertIn('E = 2e11 Па', labels)
        self.assertIn('A = 0.001 м2', labels)

    def test_support_hatches_keep_one_slope(self) -> None:
        '''Проверяет одинаковый наклон и внешнюю сторону заделок.'''
        hatches = [item.line() for item in self.view.scene().items() if isinstance(item, QGraphicsLineItem) and item.data(0) == 'support_hatch']
        left = self.view._bars[0].rect().left()
        right = self.view._bars[-1].rect().right()
        self.assertTrue(hatches)
        self.assertTrue(any(line.x2() == left for line in hatches))
        self.assertTrue(any(line.x1() == right for line in hatches))
        self.assertTrue(all(line.dx() > 0 and line.dy() < 0 for line in hatches))

    def test_load_arrows_follow_sign(self) -> None:
        '''Проверяет направление стрелок для обоих знаков нагрузки.'''
        forces = [item.line() for item in self.view._load_items if isinstance(item, QGraphicsLineItem) and item.pen().color().name() == self.view._colors.force]
        self.assertEqual(len(forces), 2)
        self.assertGreater(forces[0].dx(), 0)
        self.assertLess(forces[1].dx(), 0)
        self.assertEqual(forces[0].x1(), self.view._bars[0].rect().left())
        self.assertEqual(forces[1].x1(), self.view._bars[-1].rect().right())
        distributed = [item.line() for item in self.view._load_items if isinstance(item, QGraphicsLineItem) and item.pen().color().name() == self.view._colors.distributed]
        self.assertTrue(any(line.dx() < 0 for line in distributed))
        self.assertTrue(any(line.dx() > 0 for line in distributed))
        self.assertTrue(all(line.y1() == line.y2() == 150 for line in (*forces, *distributed)))

    def test_theme_preserves_selection_and_zoom(self) -> None:
        '''Проверяет сохранение состояния схемы при смене оформления.'''
        self.view.select_bar(1)
        self.view.zoom_by(1.5)
        scale = self.view.transform().m11()
        self.view.set_theme(LIGHT_COLORS)
        self.assertTrue(self.view._bars[1].isSelected())
        self.assertEqual(self.view.transform().m11(), scale)
        self.assertEqual(self.view._model, self.model)

    def test_empty_and_extreme_models_remain_visible(self) -> None:
        '''Проверяет пустую модель и очень разные длины и площади.'''
        self.view.set_model(StructuralModel())
        self.assertEqual(len(self.view._bars), 0)
        extreme = StructuralModel(
            bars=(
                Bar(Decimal('1e-120'), Decimal('1e-120'), Decimal('1'), Decimal('1')),
                Bar(Decimal('1e120'), Decimal('1e120'), Decimal('1'), Decimal('1')),
            ),
            nodal_forces=(Decimal('0'),) * 3,
            distributed_loads=(Decimal('0'),) * 2,
            supports=(False, True, True),
        )
        self.view.set_model(extreme)
        self.assertTrue(all(bar.rect().width() >= 120 and bar.rect().height() >= 18 for bar in self.view._bars))
        self.assertTrue(self.view.sceneRect().isValid())

    def test_invalid_draft_does_not_create_infinite_geometry(self) -> None:
        '''Не допускает бесконечных координат при открытии ошибочного черновика.'''
        draft = StructuralModel(
            bars=tuple(
                Bar(Decimal(length), Decimal('1'), Decimal('1'), Decimal('1'))
                for length in ('1e1000', '-1e1000', '1e-1000')
            ),
            nodal_forces=(Decimal('0'),) * 4,
            distributed_loads=(Decimal('0'),) * 3,
            supports=(True, False, False, False),
        )
        self.view.set_model(draft)
        self.assertLess(self.view.sceneRect().width(), 2000)
        self.assertEqual(len(self.view._bars), 3)

    def test_zoom_keeps_text_size_in_screen_pixels(self) -> None:
        '''Не увеличивает шрифт подписей вместе с геометрией стержней.'''
        self.view.show()
        self.app.processEvents()
        label = next(item for item, *_ in self.view._quantity_labels if item.text() == 'L = 1 м')
        before = label.deviceTransform(self.view.viewportTransform()).mapRect(label.boundingRect()).size()
        self.view.zoom_by(2)
        after = label.deviceTransform(self.view.viewportTransform()).mapRect(label.boundingRect()).size()
        self.assertEqual(before, after)

    def test_force_labels_stay_above_bar_at_every_zoom(self) -> None:
        '''Сохраняет экранный отступ подписи F над гранью стержня.'''
        self.view.show()
        self.app.processEvents()
        for factor in (1, 2, 0.4):
            self.view.zoom_by(factor)
            for item in self.view._load_items:
                top = item.data(1)
                if top is None or not item.isVisible():
                    continue
                label = item.deviceTransform(self.view.viewportTransform()).mapRect(item.boundingRect())
                edge = self.view.viewportTransform().map(0.0, top)[1]
                self.assertAlmostEqual(edge - label.bottom(), 8, places=5)

    def test_forty_bars_fit_without_flattening_height(self) -> None:
        '''Вписывает длинную цепочку по ширине, сохраняя читаемую высоту.'''
        model = StructuralModel((Bar(Decimal(1), Decimal(1), Decimal(1), Decimal(1)),) * 40,
                                (Decimal(0),) * 40 + (Decimal(1),), (Decimal(-1),) * 40,
                                (True,) + (False,) * 40)
        self.view.show()
        self.view.set_model(model)
        self.app.processEvents()
        self.view.fit_model()
        self.assertEqual(len(self.view._bars), 40)
        first = self.view.mapFromScene(self.view._bars[0].rect()).boundingRect()
        last = self.view.mapFromScene(self.view._bars[-1].rect()).boundingRect()
        self.assertGreater(first.height(), 30)
        self.assertGreaterEqual(first.left(), 0)
        self.assertLessEqual(last.right(), self.view.viewport().width())

    def test_tiny_bar_has_multiple_distributed_arrows(self) -> None:
        '''Сохраняет видимость короткого стержня и характер погонной нагрузки.'''
        from dataclasses import replace

        model = replace(self.model, bars=(replace(self.model.bars[0], length_m=Decimal('1e-1000')),
                                         replace(self.model.bars[1], length_m=Decimal('1e1000'))))
        self.view.set_model(model)
        first = self.view._bars[0].rect()
        arrows = [item.line() for item in self.view._load_items
                  if isinstance(item, QGraphicsLineItem) and item.pen().color().name() == self.view._colors.distributed
                  and first.left() < item.line().x1() < first.right()]
        self.assertGreaterEqual(len(arrows), 2)


if __name__ == '__main__':
    unittest.main()
