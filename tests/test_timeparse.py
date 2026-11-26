"""时间窗与潮位条件解析测试。"""

import unittest
from datetime import datetime

from storm_nlp.models import Language
from storm_nlp.timeparse import parse_condition, parse_window

REF = datetime(2026, 11, 26, 14, 0)


class TimeParseTest(unittest.TestCase):
    def test_chinese_absolute_window(self):
        window = parse_window("北湾避护中心自11月26日18:00起开放", REF, Language.ZH)
        self.assertEqual(window.start, datetime(2026, 11, 26, 18, 0))
        self.assertIsNone(window.end)

    def test_end_time_from_last_boat(self):
        window = parse_window("轮渡码头末班船时间为23:00", REF, Language.ZH)
        self.assertEqual(window.end, datetime(2026, 11, 26, 23, 0))

    def test_tide_below_condition_value(self):
        cond = parse_condition("东堤闸口仅在潮位低于一米二后开放", Language.ZH)
        self.assertEqual(cond.kind, "tide_below")
        self.assertEqual(cond.value, 1.2)

    def test_tide_recede_is_condition_not_clock_time(self):
        cond = parse_condition("开放至潮位回落", Language.ZH)
        self.assertEqual(cond.kind, "tide_recede")
        window = parse_window("开放至潮位回落", REF, Language.ZH)
        self.assertIsNotNone(window.end_condition)
        self.assertIsNone(window.end)

    def test_english_tide_and_time(self):
        cond = parse_condition("open when the tide falls below 1.2 m", Language.EN)
        self.assertEqual(cond.value, 1.2)
        window = parse_window("the last boat is at 23:00", REF, Language.EN)
        self.assertEqual(window.end, datetime(2026, 11, 26, 23, 0))

    def test_no_time_returns_none(self):
        self.assertIsNone(parse_window("临港大桥即刻起封闭", REF, Language.ZH))


if __name__ == "__main__":
    unittest.main()
