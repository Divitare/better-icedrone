"""Comprehensive parser tests using realistic Makerfabs serial output."""

import unittest
from uwb_web.parser import parse_line, normalize_short_addr, parse_short_addr_int


class TestNormalization(unittest.TestCase):

    def test_normalize_upper(self):
        self.assertEqual(normalize_short_addr('1786'), '1786')
        self.assertEqual(normalize_short_addr('2a3f'), '2A3F')
        self.assertEqual(normalize_short_addr('  7eff '), '7EFF')

    def test_parse_addr_int(self):
        self.assertEqual(parse_short_addr_int('1786'), 0x1786)
        self.assertEqual(parse_short_addr_int('2A3F'), 0x2A3F)
        self.assertIsNone(parse_short_addr_int('ZZZZ'))
        self.assertIsNone(parse_short_addr_int(None))


class TestMeasurementLines(unittest.TestCase):

    def test_tab_separated(self):
        line = 'from: 1786\tRange: 2.43 m\tRX power: -75.31 dBm'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'measurement')
        self.assertEqual(r.short_addr_hex, '1786')
        self.assertEqual(r.short_addr_int, 0x1786)
        self.assertAlmostEqual(r.range_m, 2.43)
        self.assertAlmostEqual(r.rx_power_dbm, -75.31)

    def test_space_separated(self):
        line = 'from: 2A3F    Range: 3.15 m    RX power: -78.52 dBm'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'measurement')
        self.assertEqual(r.short_addr_hex, '2A3F')
        self.assertAlmostEqual(r.range_m, 3.15)
        self.assertAlmostEqual(r.rx_power_dbm, -78.52)

    def test_mixed_whitespace(self):
        line = 'from: 4B01  \t Range: 5.02 m \t RX power: -82.10 dBm'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'measurement')
        self.assertEqual(r.short_addr_hex, '4B01')

    def test_lowercase_addr(self):
        line = 'from: 7eff\tRange: 4.38 m\tRX power: -80.22 dBm'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'measurement')
        self.assertEqual(r.short_addr_hex, '7EFF')

    def test_trailing_crlf(self):
        line = 'from: 1786\tRange: 2.43 m\tRX power: -75.31 dBm\r\n'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'measurement')
        self.assertEqual(r.short_addr_hex, '1786')

    def test_negative_range(self):
        # Unlikely but parser shouldn't crash
        line = 'from: 1786\tRange: -0.12 m\tRX power: -75.31 dBm'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'measurement')
        self.assertAlmostEqual(r.range_m, -0.12)

    def test_zero_range(self):
        line = 'from: 1786\tRange: 0.00 m\tRX power: -75.31 dBm'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'measurement')
        self.assertAlmostEqual(r.range_m, 0.0)


class TestDeviceAddedLines(unittest.TestCase):

    def test_ranging_init(self):
        line = 'ranging init; 1 device added ! ->  short:1786'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'device_added')
        self.assertEqual(r.short_addr_hex, '1786')
        self.assertEqual(r.event_type, 'device_added')

    def test_blink_added(self):
        line = 'blink; 1 device added ! ->  short:2A3F'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'device_added')
        self.assertEqual(r.short_addr_hex, '2A3F')

    def test_multiple_devices_number(self):
        line = 'blink; 3 device added ! ->  short:4B01'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'device_added')
        self.assertEqual(r.short_addr_hex, '4B01')


class TestDeviceInactiveLines(unittest.TestCase):

    def test_delete_inactive(self):
        line = 'delete inactive device: 4B01'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'device_inactive')
        self.assertEqual(r.short_addr_hex, '4B01')
        self.assertEqual(r.event_type, 'device_inactive')

    def test_lowercase(self):
        line = 'delete inactive device: 7eff'
        r = parse_line(line)
        self.assertEqual(r.line_type, 'device_inactive')
        self.assertEqual(r.short_addr_hex, '7EFF')


class TestDebugNoiseLines(unittest.TestCase):

    def test_add_link(self):
        r = parse_line('add_link:find struct Link end')
        self.assertEqual(r.line_type, 'debug_noise')

    def test_find_link(self):
        r = parse_line('find_link:Link is empty')
        self.assertEqual(r.line_type, 'debug_noise')

    def test_fresh_link(self):
        r = parse_line('fresh_link:Fresh fail')
        self.assertEqual(r.line_type, 'debug_noise')

    def test_bare_hex(self):
        r = parse_line('1786')
        self.assertEqual(r.line_type, 'debug_noise')

    def test_bare_float(self):
        r = parse_line('2.43')
        self.assertEqual(r.line_type, 'debug_noise')

    def test_bare_negative_float(self):
        r = parse_line('-75.31')
        self.assertEqual(r.line_type, 'debug_noise')


class TestBlankAndUnknownLines(unittest.TestCase):

    def test_blank(self):
        r = parse_line('')
        self.assertEqual(r.line_type, 'blank')

    def test_whitespace_only(self):
        r = parse_line('   \t  ')
        self.assertEqual(r.line_type, 'blank')

    def test_unknown(self):
        r = parse_line('something unexpected here')
        self.assertEqual(r.line_type, 'unknown')
        self.assertIn('something', r.event_text)

    def test_garbage(self):
        r = parse_line('\x00\xff\xfe garbage bytes')
        self.assertEqual(r.line_type, 'unknown')

    def test_partial_measurement(self):
        # Truncated line — should not crash
        r = parse_line('from: 1786\tRange: ')
        self.assertEqual(r.line_type, 'unknown')

    def test_raw_text_preserved(self):
        original = 'from: 1786\tRange: 2.43 m\tRX power: -75.31 dBm\r\n'
        r = parse_line(original)
        self.assertEqual(r.raw_text, original)


class TestFullSampleFile(unittest.TestCase):
    """Parse every line from the sample file and ensure no crashes."""

    def test_parse_all_lines(self):
        import os
        sample = os.path.join(os.path.dirname(__file__), 'sample_serial_output.txt')
        if not os.path.exists(sample):
            self.skipTest('sample file not found')

        with open(sample, 'r') as f:
            for i, line in enumerate(f, 1):
                try:
                    r = parse_line(line)
                    self.assertIn(r.line_type, (
                        'measurement', 'device_added', 'device_inactive',
                        'debug_noise', 'blank', 'unknown',
                    ), f"Line {i}: unexpected type '{r.line_type}'")
                except Exception as e:
                    self.fail(f"Line {i} raised {e}: {line!r}")


if __name__ == '__main__':
    unittest.main()
