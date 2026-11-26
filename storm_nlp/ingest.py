"""入库流水线编排。

把分句抽取、译文核对、发布闸门、指引管理串成一条可重复运行的流水线，
并对持久化（Storage）做可选装配。调用方只需要按时间顺序喂通告。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .bilingual import TranslationChecker
from .extract import extract_notice, parse_correction
from .graph import RoadNetwork
from .guidance import GuidanceManager
from .models import (
    Correction,
    IngestionReport,
    Notice,
    SourceKind,
    TranslationReport,
)
from .places import PlaceRegistry
from .storage import Storage


@dataclass
class PipelineResult:
    ingestion: list[IngestionReport]
    translations: list[TranslationReport]
    corrections: list[Correction]
    correction_effects: list[str]


class IngestPipeline:
    def __init__(
        self,
        registry: PlaceRegistry,
        network: RoadNetwork,
        ref_now: datetime,
        storage: Optional[Storage] = None,
    ):
        self.registry = registry
        self.network = network
        self.ref_now = ref_now
        self.storage = storage
        self.manager = GuidanceManager(registry, network, ref_now)
        self.checker = TranslationChecker(registry)
        self.translation_reports: list[TranslationReport] = []
        self.corrections: list[Correction] = []
        self.correction_effects: list[str] = []

    # ------------------------------------------------------------------
    def ingest(self, notice: Notice) -> IngestionReport:
        extractions = extract_notice(notice, self.registry, self.ref_now)
        if self.storage:
            self.storage.save_notice(notice)
            self.storage.save_extractions(notice.id, extractions)

        report = self.manager.record_notice(notice, extractions)

        # 机器译文：找到原文抽取结果并做一致性核对
        if notice.kind is SourceKind.MACHINE_TRANSLATION and notice.translation_of:
            source_ex = self.manager.extractions.get(notice.translation_of, [])
            if source_ex:
                t_report = self.checker.check(
                    notice.translation_of, notice.id, source_ex, extractions
                )
                self.translation_reports.append(t_report)
                self.manager.attach_translation_report(notice.id, t_report)
                if self.storage:
                    for issue in t_report.issues:
                        self.storage.log_event(
                            f"译文核对 {issue.severity}/{issue.code}：{issue.detail}", self.ref_now
                        )

        if self.storage:
            self.storage.log_event(f"通告 {notice.id} 入库，抽取 {len(extractions)} 条", self.ref_now)
            for g in self.manager.guidances:
                self.storage.save_guidance(g)
        return report

    def ingest_correction(self, notice: Notice) -> list[str]:
        extractions = extract_notice(notice, self.registry, self.ref_now)
        if self.storage:
            self.storage.save_notice(notice)
            self.storage.save_extractions(notice.id, extractions)
        # 更正通告本身仍登记原文与抽取（保证更正后指引可回溯），但不产生命令类指引
        self.manager.notices[notice.id] = notice
        self.manager.extractions[notice.id] = extractions
        correction = parse_correction(notice, self.registry, self.ref_now)
        self.corrections.append(correction)
        effects = self.manager.apply_correction(correction)
        self.correction_effects.extend(effects)
        if self.storage:
            self.storage.log_event(f"更正通告 {notice.id} 入库", self.ref_now)
            for effect in effects:
                self.storage.log_event(f"更正生效：{effect}", self.ref_now)
            for g in self.manager.guidances:
                self.storage.save_guidance(g)
        return effects

    def result(self) -> PipelineResult:
        return PipelineResult(
            ingestion=list(self.manager.reports),
            translations=list(self.translation_reports),
            corrections=list(self.corrections),
            correction_effects=list(self.correction_effects),
        )
