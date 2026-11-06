import unittest

from core.advanced_sequence import AdvancedRow, render_advanced_steps


class RenderAdvancedStepsTests(unittest.TestCase):
    def rows(self):
        return [AdvancedRow('Read VIN', '22 F1 90', '100', '1', '62 F1 90', 'vin'),
                AdvancedRow('Gear', '22 01 44', '250', '2', '62 01 44', 'gear')]

    def test_every_ecu_gets_the_whole_template_one_ecu_after_the_other(self):
        steps = render_advanced_steps(self.rows(), ['BCM', 'BMS', 'EPS'])
        self.assertEqual([(s.step, s.ecu, s.sequence_name) for s in steps],
                         [(1, 'BCM', 'Read VIN'), (2, 'BCM', 'Gear'), (3, 'BMS', 'Read VIN'), (4, 'BMS', 'Gear'),
                          (5, 'EPS', 'Read VIN'), (6, 'EPS', 'Gear')])
        gear = steps[1]
        self.assertEqual((gear.request, gear.delay_ms, gear.repeat, gear.expected_response, gear.comment),
                         ('22 01 44', 250, 2, '62 01 44', 'gear'))

    def test_six_ecus_and_two_rows_make_twelve_steps(self):
        steps = render_advanced_steps(self.rows(), [f'ECU{i}' for i in range(6)])
        self.assertEqual(len(steps), 12)
        self.assertEqual([s.step for s in steps], list(range(1, 13)))

    def test_lenient_values_like_the_import_and_blank_rows_are_skipped(self):
        rows = [AdvancedRow('a', '22f190', '', '', '62F190', ''),        # compact HEX, blank delay and repeat
                AdvancedRow('b', 'GG', 'abc', '0', 'zz', 'c'),           # bad HEX, delay and repeat
                AdvancedRow('', '', '100', '1', '', ''),                  # nothing typed: not a step
                AdvancedRow('d', '', '-5', 'x', '', '')]
        first, second, third = render_advanced_steps(rows, ['BCM'])
        self.assertEqual((first.request, first.delay_ms, first.repeat, first.expected_response),
                         ('22 F1 90', None, 1, '62 F1 90'))
        self.assertEqual((second.request, second.delay_ms, second.repeat, second.expected_response),
                         ('GG', None, 1, 'zz'))
        self.assertEqual((third.sequence_name, third.request, third.delay_ms, third.repeat), ('d', '', None, 1))

    def test_nothing_is_rendered_without_ecus_or_without_typed_rows(self):
        self.assertEqual(render_advanced_steps(self.rows(), []), ())
        self.assertEqual(render_advanced_steps([AdvancedRow()], ['BCM']), ())
        self.assertTrue(AdvancedRow().is_blank)
        self.assertFalse(AdvancedRow(request='10 03').is_blank)


if __name__ == '__main__':
    unittest.main()
