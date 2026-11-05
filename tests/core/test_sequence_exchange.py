import unittest
from core.diagnostic_sequence import DiagnosticStep


class SequenceExchangeTests(unittest.TestCase):
    def test_tsv_round_trip_quoted_comment_and_informational_result(self):
        from core.sequence_exchange import export_sequence_text, parse_sequence_text, HEADERS
        step=DiagnosticStep(1,'VIN','BCM','22 F1 90',comment=' tabs\tand\nlines ')
        text=export_sequence_text([step],['Passed'])
        self.assertEqual(text.splitlines()[0],'\t'.join(HEADERS))
        result=parse_sequence_text(text,ecu_names={'BCM'})
        self.assertEqual(result.steps[0],step)
        self.assertTrue(any('Results' in note for note in result.diagnostics))
        self.assertFalse(hasattr(result.steps[0],'result'))

    def test_missing_or_odd_content_still_imports_with_warnings_instead_of_failing(self):
        from core.sequence_exchange import export_sequence_text, parse_sequence_text
        # The app's own export has blank names; they must import again.
        own = export_sequence_text([DiagnosticStep(1, '', 'BCM', '22 F1 90', 100, 1), DiagnosticStep(2, '', 'EPS', '10 03', 200, 2)])
        result = parse_sequence_text(own)
        self.assertEqual([(s.sequence_name, s.ecu, s.request, s.delay_ms, s.repeat) for s in result.steps],
                         [('', 'BCM', '22 F1 90', 100, 1), ('', 'EPS', '10 03', 200, 2)])
        # Bad numbers / HEX / short and long rows are tolerated: defaults or the typed text are kept.
        text = export_sequence_text([]) + '\n'.join([
            'x\t\tBCM\t22f190\t-5\t0\t62F190\t\tkept',            # bad step, no name, bad delay and repeat
            '2\tn\tEPS\tGG\tabc\t\tzz\t\t',                       # bad HEX, bad delay, empty repeat
            '3\tonly name',                                           # short row
            '3\tdup\tBMS\t10 01\t\t\t\t\tc\textra\tcells',          # duplicate step, too many cells
        ])
        result = parse_sequence_text(text)
        self.assertEqual(len(result.steps), 4)
        first, second, third, fourth = result.steps
        self.assertEqual((first.step, first.sequence_name, first.request, first.delay_ms, first.repeat,
                          first.expected_response, first.comment), (1, '', '22 F1 90', None, 1, '62 F1 90', 'kept'))
        self.assertEqual((second.request, second.delay_ms, second.repeat, second.expected_response), ('GG', None, 1, 'zz'))
        self.assertEqual((third.sequence_name, third.request, third.ecu), ('only name', '', ''))
        self.assertEqual([s.step for s in result.steps], [1, 2, 3, 4])  # Positions follow the source order.
        self.assertTrue(result.diagnostics)
        self.assertTrue(any('Row 2' in note for note in result.diagnostics))

    def test_header_is_optional_and_only_unreadable_input_is_refused(self):
        from core.sequence_exchange import parse_sequence_text
        result = parse_sequence_text('1\tname\tBCM\t22 F1 90\t100\t1\t\t\tc\n')
        self.assertEqual((result.steps[0].sequence_name, result.steps[0].request), ('name', '22 F1 90'))
        for bad in ('', 'Step\tTest sequence name\tECU\tPayload(HEX)\tDelay(ms)\tRepeat\tExpected Response (HEX)\tResults\tComment\n', '\n\n'):
            with self.assertRaises(ValueError):
                parse_sequence_text(bad)
        with self.assertRaises(ValueError):
            parse_sequence_text('1\t"unterminated\tBCM\n')

    def test_csv_unknown_blank_and_missing_vehicle(self):
        import csv,io
        from core.sequence_exchange import parse_sequence_text,HEADERS
        out=io.StringIO();writer=csv.writer(out)
        writer.writerow(HEADERS);writer.writerow([1,'name','unknown<>','22 F1 90','',1,'','','a,b'])
        result=parse_sequence_text(out.getvalue(),ecu_names={'BCM'})
        self.assertEqual(result.steps[0].ecu,'unknown<>')
        self.assertTrue(any('unknown<>' in note for note in result.diagnostics))
        self.assertEqual(parse_sequence_text(out.getvalue()).diagnostics,())
