"""端到端流水线：封路失效、时间更正、转述降级、译文闸门、溯源。"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from storm_nlp.cli import build_pipeline
from storm_nlp.dataio import load_network, load_notices, load_registry
from storm_nlp.guidance import GuidanceManager
from storm_nlp.ingest import IngestPipeline
from storm_nlp.inquiry import InquiryService
from storm_nlp.models import GuidanceStatus, SourceKind
from storm_nlp.storage import Storage

REF = datetime(2026, 11, 26, 14, 0)
DATA = "data/drill"


class PipelineDrillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = build_pipeline(DATA)
        cls.manager: GuidanceManager = cls.pipeline.manager

    def test_machine_translation_report_is_blocked(self):
        report = next(r for r in self.pipeline.translation_reports
                      if r.target_notice_id == "N-01-MT")
        self.assertTrue(report.blocked)
        codes = {i.code for i in report.issues}
        self.assertIn("NEG_DROP", codes)
        self.assertIn("GENERIC_SCOPE_FABRICATION", codes)

    def test_blocked_translation_guidances_are_not_publishable(self):
        blocked = self.manager.by_status(GuidanceStatus.BLOCKED)
        self.assertTrue(blocked)
        for g in blocked:
            self.assertTrue(g.block_reasons)
        # 所有可发布指引都不来自被阻断的译文条款
        for g in self.manager.active():
            self.assertFalse(
                g.translation_derived,
                f"译文派生指引 {g.gid} 不应进入可发布集合",
            )

    def test_bridge_closure_invalidates_old_routes_and_issues_detour(self):
        invalidated = [
            g for g in self.manager.guidances
            if g.status is GuidanceStatus.INVALIDATED and "E-LINGANG" in g.route_edges
        ]
        self.assertTrue(invalidated)
        detours = [
            g for g in self.manager.active()
            if g.kind.value == "route"
            and any("N-02" in f"{b.notice_id}" for b in g.basis)
        ]
        self.assertTrue(detours)
        # 替代路线不再经过已封闭的桥
        for g in detours:
            self.assertNotIn("E-LINGANG", g.route_edges)

    def test_wheelchair_detour_exists_after_bridge_closure(self):
        wc_detours = [
            g for g in self.manager.active()
            if g.audience.value == "wheelchair" and g.route_edges
        ]
        self.assertTrue(wc_detours)
        for g in wc_detours:
            self.assertIn("E-SURFACE", g.route_edges)

    def test_relay_stays_pending_until_official_order_disproves_it(self):
        relay = next(g for g in self.manager.guidances if g.is_relay)
        self.assertEqual(relay.status, GuidanceStatus.SUPERSEDED)
        self.assertIn("不实", relay.invalidated_reason)
        self.assertEqual(relay.superseded_by, "N-05")

    def test_time_correction_supersedes_old_ferry_guidance(self):
        superseded = [
            g for g in self.manager.guidances
            if g.status is GuidanceStatus.SUPERSEDED and g.window and g.window.end
        ]
        self.assertTrue(superseded)
        fresh = [
            g for g in self.manager.active()
            if g.window and g.window.end == datetime(2026, 11, 26, 22, 0)
        ]
        self.assertTrue(fresh)

    def test_trace_returns_original_notice_text(self):
        active = self.manager.active()[0]
        trace = self.manager.trace(active.gid)
        self.assertIsNotNone(trace)
        self.assertTrue(trace.sources)
        for notice in trace.sources:
            self.assertTrue(notice.text.strip())

    def test_inquiry_does_not_publish_relay_or_stale_routes(self):
        service = InquiryService(self.manager, self.pipeline.registry)
        answer = service.answer("听说海西路涵洞一直开着，是真的吗？")
        self.assertNotIn("可以走", answer.text)
        bridge = service.answer("临港大桥现在是什么状态？之前发的路线还能用吗？")
        self.assertIn("已封闭", bridge.text)
        self.assertIn("已失效路线指引", bridge.text)

    def test_every_active_guidance_has_basis(self):
        for g in self.manager.active():
            self.assertTrue(g.basis, f"{g.gid} 缺少原文依据")
            for basis in g.basis:
                self.assertIn(basis.notice_id, self.manager.notices)


class StorageTest(unittest.TestCase):
    def test_persistence_roundtrip_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "drill.sqlite"
            pipeline = build_pipeline(DATA, db_path=str(db))
            storage = Storage(str(db))
            rows = storage.list_guidances()
            self.assertTrue(rows)
            notice = storage.load_notice("N-02")
            self.assertIsNotNone(notice)
            self.assertIn("临港大桥", notice["text"])
            self.assertTrue(storage.audit_trail())
            storage.close()


if __name__ == "__main__":
    unittest.main()
