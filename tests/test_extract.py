"""要素抽取：效力等级、否定、对象、条件、结构完整性。"""

import unittest
from datetime import datetime

from storm_nlp.dataio import load_network, load_registry
from storm_nlp.extract import extract_notice
from storm_nlp.models import (
    ActionType,
    Audience,
    ForceLevel,
    Language,
    Notice,
    SourceKind,
)

REF = datetime(2026, 11, 26, 14, 0)
DATA = "data/drill"


class ExtractionTest(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(DATA)
        self.network = load_network(DATA, self.registry)

    def _extract(self, text, kind=SourceKind.OFFICIAL, language=Language.ZH):
        notice = Notice(id="T-1", language=language, kind=kind, text=text, received_at=REF)
        return extract_notice(notice, self.registry, REF)

    def test_advisory_negation_is_not_order(self):
        extractions = self._extract(
            "请轮椅使用者不要走海西路涵洞，请经临港大桥前往北湾避护中心。"
        )
        avoid = next(e for e in extractions if e.action is ActionType.AVOID)
        self.assertEqual(avoid.force, ForceLevel.ADVISORY)
        self.assertTrue(avoid.negated)
        self.assertEqual(avoid.audience, Audience.WHEELCHAIR)
        # 建议不允许触发封路
        self.assertNotIn("MISSING_TIME_OR_CONDITION", avoid.issues)

    def test_confirmed_closure_is_order_without_time_requirement(self):
        extractions = self._extract("临港大桥即刻起封闭，封闭命令已经值班长确认。")
        self.assertEqual(extractions[0].force, ForceLevel.ORDER)
        self.assertEqual(extractions[0].action, ActionType.CLOSE)
        self.assertEqual(extractions[0].issues, [])

    def test_relay_never_escalates_to_order(self):
        extractions = self._extract(
            "邻居说海西路涵洞也一直开着，可以走。", kind=SourceKind.RELAY
        )
        self.assertEqual(extractions[0].force, ForceLevel.RELAY)

    def test_generic_place_is_flagged_unbounded(self):
        extractions = self._extract(
            "All shelters remain open until the tide recedes.",
            kind=SourceKind.MACHINE_TRANSLATION,
            language=Language.EN,
        )
        self.assertTrue(extractions[0].generic_place)
        self.assertIn("GENERIC_SCOPE_UNBOUNDED", extractions[0].issues)

    def test_scope_clause_does_not_become_command(self):
        extractions = self._extract("该时间条件只适用于东堤闸口这一处通道。")
        self.assertTrue(extractions[0].scope_clause)
        self.assertEqual(extractions[0].action, ActionType.UNKNOWN)
        self.assertEqual(extractions[0].issues, [])

    def test_service_action_for_last_boat(self):
        extractions = self._extract("轮渡码头末班船时间为23:00。")
        self.assertEqual(extractions[0].action, ActionType.SERVICE)
        self.assertEqual(extractions[0].audience, Audience.FERRY)

    def test_open_requires_time_or_condition(self):
        extractions = self._extract("北湾避护中心开放。")
        self.assertIn("MISSING_TIME_OR_CONDITION", extractions[0].issues)


if __name__ == "__main__":
    unittest.main()
