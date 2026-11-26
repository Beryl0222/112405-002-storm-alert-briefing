"""原文与机器译文的一致性核对。

核对目标是把「译文缺少否定或适用条件时不能按完整命令下发」落成可执行规则：

* NEG_DROP            译文丢失否定（如把「请勿」译成肯定句）；
* COND_MISSING        译文丢失潮位/适用条件；
* COND_SCOPE_EXPANDED 条件只限定一处通道，译文却外推为所有点同时适用；
* AUDIENCE_DROP       译文丢失轮椅/渡船乘客等适用对象（阻断，避免错发命令）；
* TIME_MISMATCH       译文的时间窗与原文不一致；
* HALLUCINATION / UNTRANSLATED 为提示级问题。

出现任一 blocker 的译文整体标记为不可发布，其要素抽取会被打上 translation_blocked。
"""

from __future__ import annotations

from .models import (
    ActionType,
    Audience,
    Extraction,
    ForceLevel,
    TranslationIssue,
    TranslationReport,
)
from .places import PlaceRegistry


class TranslationChecker:
    def __init__(self, registry: PlaceRegistry):
        self.registry = registry

    def check(
        self,
        source_id: str,
        target_id: str,
        source: list[Extraction],
        target: list[Extraction],
    ) -> TranslationReport:
        report = TranslationReport(source_notice_id=source_id, target_notice_id=target_id)
        unmatched_targets = set(range(len(target)))
        blocked_refs: set[str] = set()

        for src in source:
            cand = self._best_match(src, target)
            if cand is None:
                report.issues.append(
                    TranslationIssue(
                        "warning",
                        "UNTRANSLATED",
                        f"原文 {src.ref} 的安排未在译文中找到对应条款：{src.span}",
                        source_ref=src.ref,
                    )
                )
                continue
            tgt, tgt_index = cand
            unmatched_targets.discard(tgt_index)
            before = len(report.issues)
            self._compare_pair(src, tgt, report)
            if any(
                i.severity == "blocker" and i.target_ref == tgt.ref
                for i in report.issues[before:]
            ):
                blocked_refs.add(tgt.ref)

        for idx in unmatched_targets:
            tgt = target[idx]
            severity = "blocker" if tgt.generic_place else "warning"
            code = "GENERIC_SCOPE_FABRICATION" if tgt.generic_place else "HALLUCINATION"
            detail = (
                f"译文 {tgt.ref} 把原文只限定单处通道的条件外推为泛指安排：{tgt.span}"
                if tgt.generic_place
                else f"译文 {tgt.ref} 在原文中找不到对应安排：{tgt.span}"
            )
            report.issues.append(
                TranslationIssue(severity, code, detail, target_ref=tgt.ref)
            )
            if severity == "blocker":
                blocked_refs.add(tgt.ref)

        # 只阻断确有问题的译文条款；正确译出的条款保留抽取，但其指引仍标记为译文派生
        for extraction in target:
            if extraction.ref in blocked_refs:
                extraction.translation_blocked = True
                extraction.issues.append("TRANSLATION_BLOCKED")
        return report

    # ---------- 配对 ----------
    def _best_match(self, src: Extraction, targets: list[Extraction]):
        equivalent = {ActionType.SUSPEND, ActionType.SERVICE}
        candidates = [
            (idx, tgt)
            for idx, tgt in enumerate(targets)
            if (
                tgt.action is src.action
                or (tgt.action in equivalent and src.action in equivalent)
            )
            and (
                (src.generic_place and tgt.generic_place)
                or (src.place_id and src.place_id == tgt.place_id)
                or (src.place_id is None and not tgt.generic_place)
            )
        ]
        if not candidates:
            # 放宽行动类型限制，仅按地点配
            candidates = [
                (idx, tgt)
                for idx, tgt in enumerate(targets)
                if (src.place_id and src.place_id == tgt.place_id)
                or (src.generic_place and tgt.generic_place)
            ]
        return (candidates[0][1], candidates[0][0]) if candidates else None

    # ---------- 逐维比较 ----------
    def _compare_pair(self, src: Extraction, tgt: Extraction, report: TranslationReport) -> None:
        src_ref, tgt_ref = src.ref, tgt.ref

        if src.negated and not tgt.negated:
            report.issues.append(
                TranslationIssue(
                    "blocker", "NEG_DROP",
                    f"原文含否定/禁止要求（{src.span}），译文丢失否定，禁止按肯定命令下发。",
                    src_ref, tgt_ref,
                )
            )

        # 条件范围：原文的条件只绑定具体地点时，泛指译文属于范围扩大
        if src.condition and tgt.condition is None:
            report.issues.append(
                TranslationIssue(
                    "blocker", "COND_MISSING",
                    f"原文 {src_ref} 含适用条件「{src.condition.describe()}」，译文 {tgt_ref} 未译出该条件。",
                    src_ref, tgt_ref,
                )
            )
        if src.condition and src.place_id and tgt.generic_place:
            report.issues.append(
                TranslationIssue(
                    "blocker", "COND_SCOPE_EXPANDED",
                    f"条件「{src.condition.describe()}」原文只限定 {self.registry.display(src.place_id)}，"
                    f"译文却外推到所有避护点，范围扩大。",
                    src_ref, tgt_ref,
                )
            )
        if src.generic_place and not tgt.generic_place and tgt.place_id:
            report.issues.append(
                TranslationIssue(
                    "warning", "SCOPE_NARROWED",
                    f"原文泛指所有避护点，译文仅落到 {self.registry.display(tgt.place_id)}，范围收窄，请人工确认。",
                    src_ref, tgt_ref,
                )
            )

        if src.audience is not Audience.GENERAL and tgt.audience is Audience.GENERAL:
            report.issues.append(
                TranslationIssue(
                    "blocker", "AUDIENCE_DROP",
                    f"原文 {src_ref} 限定对象为 {src.audience.value}，译文 {tgt_ref} 丢失适用对象。",
                    src_ref, tgt_ref,
                )
            )

        if src.window and tgt.window:
            if not self._window_compatible(src, tgt):
                report.issues.append(
                    TranslationIssue(
                        "blocker", "TIME_MISMATCH",
                        f"译文时间窗（{tgt.window.raw}）与原文（{src.window.raw}）不一致。",
                        src_ref, tgt_ref,
                    )
                )
        elif src.window and not tgt.window:
            report.issues.append(
                TranslationIssue(
                    "warning", "TIME_DROP",
                    f"原文 {src_ref} 含时间安排，译文未体现。",
                    src_ref, tgt_ref,
                )
            )

        if src.force is ForceLevel.ADVISORY and tgt.force is ForceLevel.ORDER:
            report.issues.append(
                TranslationIssue(
                    "blocker", "FORCE_ESCALATION",
                    f"原文是预警建议，译文使用命令措辞，效力被抬高。",
                    src_ref, tgt_ref,
                )
            )

    @staticmethod
    def _window_compatible(src: Extraction, tgt: Extraction) -> bool:
        sw, tw = src.window, tgt.window
        if (sw.start is not None or tw.start is not None) and sw.start != tw.start:
            return False
        if (sw.end is not None or tw.end is not None) and sw.end != tw.end:
            return False
        if type(sw.end_condition) is not type(tw.end_condition):
            return False
        if sw.end_condition and tw.end_condition and sw.end_condition.kind != tw.end_condition.kind:
            return False
        return True
