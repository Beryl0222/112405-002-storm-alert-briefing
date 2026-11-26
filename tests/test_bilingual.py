"""原文—译文一致性核对：否定缺失、条件范围扩大必须阻断。"""

import unittest
from datetime import datetime

from storm_nlp.bilingual import TranslationChecker
from storm_nlp.dataio import load_network, load_registry
from storm_nlp.extract import extract_notice
from storm_nlp.models import Language, Notice, SourceKind

REF = datetime(2026, 11, 26, 14, 0)
DATA = "data/drill"


class BilingualTest(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(DATA)
        self.network = load_network(DATA, self.registry)
        self.checker = TranslationChecker(self.registry)

    def _pair(self, zh_text, en_text):
        src_notice = Notice("S-1", Language.ZH, SourceKind.OFFICIAL, zh_text, REF)
        tgt_notice = Notice(
            "S-1-MT", Language.EN, SourceKind.MACHINE_TRANSLATION, en_text, REF,
            translation_of="S-1",
        )
        src = extract_notice(src_notice, self.registry, REF)
        tgt = extract_notice(tgt_notice, self.registry, REF)
        return src, tgt, self.checker.check("S-1", "S-1-MT", src, tgt)

    def test_negation_drop_blocks(self):
        _, _, report = self._pair(
            "请轮椅使用者不要走海西路涵洞。",
            "Wheelchair users should use the Haixi Underpass.",
        )
        self.assertTrue(report.blocked)
        self.assertIn("NEG_DROP", [i.code for i in report.issues])

    def test_condition_scope_expansion_blocks(self):
        _, _, report = self._pair(
            "东堤闸口仅在潮位低于一米二后开放，开放至潮位回落。",
            "All shelters remain open until the tide recedes.",
        )
        codes = {i.code for i in report.issues}
        self.assertTrue(report.blocked)
        self.assertTrue({"COND_SCOPE_EXPANDED", "GENERIC_SCOPE_FABRICATION"} & codes)

    def test_condition_missing_blocks(self):
        _, _, report = self._pair(
            "东堤闸口仅在潮位低于一米二后开放。",
            "The East Embankment Gate is open.",
        )
        self.assertIn("COND_MISSING", [i.code for i in report.issues])

    def test_audience_drop_blocks(self):
        _, _, report = self._pair(
            "请轮椅使用者不要走海西路涵洞。",
            "People should not use the Haixi Underpass.",
        )
        self.assertIn("AUDIENCE_DROP", [i.code for i in report.issues])

    def test_faithful_translation_not_blocked(self):
        _, target, report = self._pair(
            "北湾避护中心自11月26日18:00起开放。",
            "North Bay Shelter will open at 18:00 on Nov 26.",
        )
        self.assertFalse(report.blocked)
        self.assertTrue(all(not t.translation_blocked for t in target))

    def test_only_flawed_clauses_are_blocked(self):
        _, target, report = self._pair(
            "北湾避护中心自11月26日18:00起开放。请轮椅使用者不要走海西路涵洞。",
            "North Bay Shelter will open at 18:00 on Nov 26. "
            "Wheelchair users should use the Haixi Underpass.",
        )
        self.assertTrue(report.blocked)
        blocked = [t.clause_index for t in target if t.translation_blocked]
        self.assertEqual(blocked, [2])  # 只有错误的第二条被阻断


if __name__ == "__main__":
    unittest.main()
