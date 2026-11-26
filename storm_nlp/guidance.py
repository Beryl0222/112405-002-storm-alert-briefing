"""指引生命周期管理。

职责：

1. 把要素抽取转成可发布指引，并执行发布闸门
   （结构不完整、译文阻断、效力为转述的内容一律不得作为命令下发）；
2. 处理封路命令：关闭网络闸口、失效受影响路线并尝试重算替代路线；
3. 处理改名/时间更正：标记旧指引 SUPERSEDED，产出新指引，并保留全部原文依据；
4. 提供逐条溯源：任何指引都能查回它依据的通告原文与条款。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from . import lexicon
from .graph import RoadNetwork, Route
from .models import (
    ActionType,
    Audience,
    BasisRef,
    Correction,
    Extraction,
    ForceLevel,
    Guidance,
    GuidanceStatus,
    IngestionReport,
    Notice,
    SourceKind,
    TranslationReport,
)
from .places import PlaceKind, PlaceRegistry

# 居民出发区（演练路网中的老城路口）
DEFAULT_ORIGIN = "J-OLDTOWN"

_AUDIENCE_MODE = {
    Audience.GENERAL: "walk",
    Audience.WHEELCHAIR: "wheelchair",
    Audience.FERRY: "ferry",
}
_ACTION_TITLE = {
    ActionType.OPEN: "开放指引",
    ActionType.CLOSE: "封闭通知",
    ActionType.SUSPEND: "停航通知",
    ActionType.SERVICE: "运营时刻指引",
    ActionType.AVOID: "禁行指引",
    ActionType.ROUTE: "路线指引",
    ActionType.GATHER: "集合指引",
    ActionType.UNKNOWN: "待人工判定",
}


@dataclass
class TraceResult:
    guidance: Guidance
    sources: list[Notice]
    spans: list[BasisRef]


class GuidanceManager:
    def __init__(
        self,
        registry: PlaceRegistry,
        network: RoadNetwork,
        ref_now: datetime,
        origin: str = DEFAULT_ORIGIN,
    ):
        self.registry = registry
        self.network = network
        self.ref_now = ref_now
        self.origin = origin
        self.notices: dict[str, Notice] = {}
        self.extractions: dict[str, list[Extraction]] = {}
        self.guidances: list[Guidance] = []
        self.reports: list[IngestionReport] = []
        self.audit: list[str] = []
        self._seq = 0

    def _next_gid(self) -> str:
        self._seq += 1
        return f"G-{self._seq:03d}"

    # ------------------------------------------------------------------
    # 入库
    # ------------------------------------------------------------------
    def record_notice(self, notice: Notice, extractions: list[Extraction]) -> IngestionReport:
        self.notices[notice.id] = notice
        self.extractions[notice.id] = extractions
        report = IngestionReport(notice_id=notice.id, extraction_count=len(extractions))

        if notice.kind is SourceKind.RELAY:
            for extraction in extractions:
                report.pending_relays.append(extraction.ref)
                self._make_relay_pending(extraction)
            report.notes.append("居民转述仅登记待核实，未产生可发布命令。")
            self.reports.append(report)
            return report

        for extraction in extractions:
            self._ingest_extraction(extraction, report)
        self.reports.append(report)
        return report

    def attach_translation_report(self, notice_id: str, report_t: TranslationReport) -> None:
        """译文核对结果绑定到该译文的入库报告，并对阻断指引做拦截标记。"""

        for report in self.reports:
            if report.notice_id == notice_id:
                report.translation_report = report_t
        if report_t.blocked:
            blocked_refs = {
                issue.target_ref
                for issue in report_t.issues
                if issue.severity == "blocker" and issue.target_ref
            }
            for guidance in self.guidances:
                if any(f"{b.notice_id}#{b.clause_index}" in blocked_refs for b in guidance.basis):
                    guidance.status = GuidanceStatus.BLOCKED
                    guidance.block_reasons = sorted(
                        set(guidance.block_reasons + [
                            f"{issue.code}: {issue.detail}"
                            for issue in report_t.issues
                            if issue.severity == "blocker"
                        ])
                    )
                    self.audit.append(
                        f"{notice_id} 译文核对阻断，指引 {guidance.gid} 不得下发："
                        f"{', '.join(i.code for i in report_t.issues if i.severity == 'blocker')}"
                    )

    def _ingest_extraction(self, extraction: Extraction, report: IngestionReport) -> None:
        if extraction.scope_clause:
            report.notes.append(f"{extraction.ref} 为范围说明条款，不单独生成命令。")
            return

        reasons = list(extraction.issues)
        if extraction.translation_blocked and "TRANSLATION_BLOCKED" not in reasons:
            reasons.append("TRANSLATION_BLOCKED")

        guidance = self._build_guidance(extraction)
        guidance.translation_derived = extraction.translation_derived

        if reasons:
            guidance.status = GuidanceStatus.BLOCKED
            guidance.block_reasons = reasons
            report.guidance_blocked.append((guidance.gid, reasons))
            self.audit.append(f"{extraction.ref} 未通过发布闸门：{','.join(reasons)}")
        else:
            report.guidance_issued.append(guidance.gid)
            self.audit.append(f"{extraction.ref} 生成可发布指引 {guidance.gid}")
        self.guidances.append(guidance)

        # 已确认的封路/禁行命令立即作用于网络
        if (
            extraction.force is ForceLevel.ORDER
            and extraction.action in (ActionType.CLOSE, ActionType.AVOID)
            and extraction.place_id
            and not reasons
        ):
            self._apply_closure(extraction)
            self._disprove_relays(extraction)

    def _build_guidance(self, extraction: Extraction) -> Guidance:
        basis = [BasisRef(extraction.notice_id, extraction.clause_index, extraction.span)]
        subject = extraction.place_id
        title = self._title(extraction)
        route_nodes, route_edges, detail = [], [], ""

        subject_place = self.registry.get(subject) if subject else None
        is_gate = bool(subject_place and subject_place.kind == PlaceKind.GATE)
        # 仅为避护点/码头的开放或前往安排计算实际路线；闸口本身是通道不是目的地
        if (
            extraction.action in (ActionType.ROUTE, ActionType.OPEN)
            and subject
            and not is_gate
        ):
            mode = _AUDIENCE_MODE[extraction.audience]
            route = self.network.shortest_route(self.origin, subject, mode)
            if route.feasible:
                route_nodes, route_edges, detail = route.nodes, route.edges, route.detail
            else:
                extraction.issues.append("NO_FEASIBLE_ROUTE")
                detail = route.detail

        return Guidance(
            gid=self._next_gid(),
            kind=extraction.action,
            subject_id=subject,
            audience=extraction.audience,
            title=title,
            window=extraction.window,
            basis=basis,
            route_nodes=route_nodes,
            route_edges=route_edges,
            route_detail=detail,
            is_relay=extraction.force is ForceLevel.RELAY,
            translation_derived=extraction.translation_derived,
            created_at=self.ref_now,
            updated_at=self.ref_now,
        )

    def _title(self, extraction: Extraction) -> str:
        place = self.registry.display(extraction.place_id) if extraction.place_id else "泛指地点"
        head = _ACTION_TITLE[extraction.action]
        audience_zh = {
            Audience.WHEELCHAIR: "（轮椅使用者）",
            Audience.FERRY: "（夜班渡船乘客）",
            Audience.GENERAL: "",
        }[extraction.audience]
        cond = f"，条件：{extraction.condition.describe()}" if extraction.condition else ""
        neg = "（否定/禁止）" if extraction.negated else ""
        return f"{head}{audience_zh}：{place}{cond}{neg}"

    def _make_relay_pending(self, extraction: Extraction) -> None:
        guidance = Guidance(
            gid=self._next_gid(),
            kind=extraction.action,
            subject_id=extraction.place_id,
            audience=extraction.audience,
            title=f"【待核实转述】{self._title(extraction)}",
            window=extraction.window,
            basis=[BasisRef(extraction.notice_id, extraction.clause_index, extraction.span)],
            status=GuidanceStatus.PENDING,
            is_relay=True,
            created_at=self.ref_now,
            updated_at=self.ref_now,
        )
        self.guidances.append(guidance)

    # ------------------------------------------------------------------
    # 封路
    # ------------------------------------------------------------------
    def _apply_closure(self, extraction: Extraction) -> None:
        gate_id = extraction.place_id
        basis = BasisRef(extraction.notice_id, extraction.clause_index, extraction.span)
        if self.network.is_gate_closed(gate_id):
            self.audit.append(
                f"{extraction.ref} 封路命令重复到达，通道 {self.registry.display(gate_id)} 已封闭，不重复生效"
            )
            return
        affected_edges = self.network.close_gate(gate_id, basis)
        self.audit.append(
            f"{extraction.ref} 封路生效，关闭通道 {self.registry.display(gate_id)}，受影响边：{', '.join(affected_edges)}"
        )
        for guidance in self.guidances:
            if guidance.status not in (GuidanceStatus.ACTIVE,):
                continue
            hit = [eid for eid in guidance.route_edges if eid in affected_edges]
            if not hit:
                continue
            guidance.status = GuidanceStatus.INVALIDATED
            guidance.invalidated_reason = (
                f"依据 {extraction.ref}，通道 {self.registry.display(gate_id)} 封闭，"
                f"原路线经过已关闭边 {', '.join(hit)}"
            )
            guidance.updated_at = self.ref_now
            self.audit.append(f"指引 {guidance.gid} 因封路失效")
            if guidance.subject_id:
                self._issue_detour(guidance)

    def _disprove_relays(self, extraction: Extraction) -> None:
        """官方封路命令直接否定同地点的待核实转述。"""

        for guidance in self.guidances:
            if (
                guidance.status is GuidanceStatus.PENDING
                and guidance.subject_id == extraction.place_id
            ):
                guidance.status = GuidanceStatus.SUPERSEDED
                guidance.superseded_by = extraction.notice_id
                guidance.invalidated_reason = (
                    f"官方命令 {extraction.ref} 已封闭该通道，转述内容不实，停止转发"
                )
                self.audit.append(f"待核实转述指引 {guidance.gid} 被官方命令 {extraction.ref} 否定")

    def _issue_detour(self, failed: Guidance) -> None:
        basis = list(failed.basis)
        closure_basis = next(
            (e.closed_by for e in self.network.edges.values() if e.closed_by), None
        )
        if closure_basis:
            basis.append(closure_basis)

        # 按该指引对象的通行方式重算；通用步行指引同时为轮椅补一条无障碍路线
        modes = [_AUDIENCE_MODE[failed.audience]]
        if failed.audience is Audience.GENERAL:
            modes.append("wheelchair")
        issued: set[tuple[str, str]] = set()
        for mode in dict.fromkeys(modes):
            route = self.network.shortest_route(self.origin, failed.subject_id, mode)
            if not route.feasible:
                self.audit.append(
                    f"指引 {failed.gid} 失效后 {mode} 暂无可行替代路线，需值班员人工处理"
                )
                continue
            audience = next(
                (aud for aud, m in _AUDIENCE_MODE.items() if m == mode), Audience.GENERAL
            )
            dedup_key = (audience.value, tuple(route.edges))
            if dedup_key in issued:
                continue
            issued.add(dedup_key)
            detour = Guidance(
                gid=self._next_gid(),
                kind=ActionType.ROUTE,
                subject_id=failed.subject_id,
                audience=audience,
                title=f"替代路线指引：{self.registry.display(failed.subject_id)}",
                window=failed.window,
                basis=basis,
                route_nodes=route.nodes,
                route_edges=route.edges,
                route_detail=route.detail,
                translation_derived=failed.translation_derived,
                created_at=self.ref_now,
                updated_at=self.ref_now,
            )
            self.guidances.append(detour)
            self.audit.append(f"已为失效指引 {failed.gid} 重算 {mode} 替代路线 {detour.gid}")

    # ------------------------------------------------------------------
    # 更正
    # ------------------------------------------------------------------
    def apply_correction(self, correction: Correction) -> list[str]:
        effects: list[str] = []
        for old_name, new_name in correction.place_renames:
            old_id = self.registry.resolve(old_name)
            new_id = self.registry.resolve(new_name)
            if old_id and new_id and old_id != new_id:
                # 两个既有译名指向同一地点：合并，不重复建点
                target = self.registry.require(new_id)
                self.registry.learn_alias(
                    new_id, old_name, f"{correction.notice_id} 更正：{old_name} 与 {new_name} 为同一地点"
                )
                effects.append(f"地点合并：{old_name} → {target.name}（{new_id}），未新建地点")
                self._supersede_for_place(old_id, correction.notice_id, "地点更名/合并")
            elif old_id and not new_id:
                self.registry.learn_alias(
                    old_id, new_name, f"{correction.notice_id} 更正：现名 {new_name}"
                )
                effects.append(f"地点更名：{old_name} → {new_name}（沿用 {old_id}）")
                self._supersede_for_place(old_id, correction.notice_id, "地点更名")
        for subject, old_time, new_time, span in correction.time_changes:
            changed = self._supersede_for_time(subject, old_time, new_time, correction.notice_id, span)
            effects.extend(changed)
        self.audit.extend(effects)
        return effects

    def _supersede_for_place(self, place_id: str, notice_id: str, reason: str) -> None:
        for guidance in self.guidances:
            if guidance.subject_id == place_id and guidance.status is GuidanceStatus.ACTIVE:
                guidance.status = GuidanceStatus.SUPERSEDED
                guidance.superseded_by = notice_id
                guidance.invalidated_reason = reason
                guidance.updated_at = self.ref_now
                fresh = self._clone_with_basis(guidance, notice_id)
                self.guidances.append(fresh)
                self.audit.append(f"指引 {guidance.gid} 因{reason}被取代，新指引 {fresh.gid} 可沿用核对")

    def _supersede_for_time(
        self, subject: str, old_time: Optional[datetime], new_time: Optional[datetime],
        notice_id: str, span: str,
    ) -> list[str]:
        effects: list[str] = []
        for guidance in self.guidances:
            if guidance.status is not GuidanceStatus.ACTIVE or not guidance.window:
                continue
            if guidance.window.end != old_time:
                continue
            guidance.status = GuidanceStatus.SUPERSEDED
            guidance.superseded_by = notice_id
            guidance.invalidated_reason = f"生效时间被更正（{old_time:%H:%M} → {new_time:%H:%M}）"
            guidance.updated_at = self.ref_now
            fresh = self._clone_with_basis(guidance, notice_id, new_end=new_time)
            self.guidances.append(fresh)
            effects.append(
                f"时间更正：指引 {guidance.gid} 失效（依据旧时间 {old_time:%H:%M}），"
                f"新指引 {fresh.gid} 按 {new_time:%H:%M} 生效"
            )
        return effects

    def _clone_with_basis(
        self, old: Guidance, notice_id: str, new_end: Optional[datetime] = None
    ) -> Guidance:
        from dataclasses import replace

        window = old.window
        if new_end and window:
            window = replace(window, end=new_end, raw=f"{window.raw}；更正后止 {new_end:%H:%M}")
        correction_notice = self.notices.get(notice_id)
        correction_span = correction_notice.text if correction_notice else "更正通告"
        basis = list(old.basis) + [BasisRef(notice_id, 1, correction_span)]
        clone = Guidance(
            gid=self._next_gid(),
            kind=old.kind,
            subject_id=old.subject_id,
            audience=old.audience,
            title=old.title,
            window=window,
            basis=basis,
            route_nodes=list(old.route_nodes),
            route_edges=list(old.route_edges),
            route_detail=old.route_detail,
            is_relay=old.is_relay,
            translation_derived=old.translation_derived,
            created_at=self.ref_now,
            updated_at=self.ref_now,
        )
        return clone

    # ------------------------------------------------------------------
    # 核实转述与溯源
    # ------------------------------------------------------------------
    def confirm_relay(self, relay_notice_id: str, official_notice: Notice, extractions: list[Extraction]) -> list[str]:
        """官方命令核实居民转述：PENDING 指引关闭，按官方抽取走正常入库。"""

        closed: list[str] = []
        for guidance in self.guidances:
            if guidance.status is GuidanceStatus.PENDING and any(
                b.notice_id == relay_notice_id for b in guidance.basis
            ):
                guidance.status = GuidanceStatus.SUPERSEDED
                guidance.superseded_by = official_notice.id
                guidance.invalidated_reason = f"转述经 {official_notice.id} 核实，按官方命令处置"
                closed.append(guidance.gid)
        self.record_notice(official_notice, extractions)
        self.audit.append(f"转述 {relay_notice_id} 已由 {official_notice.id} 核实，待核实指引 {', '.join(closed)} 关闭")
        return closed

    def trace(self, gid: str) -> Optional[TraceResult]:
        guidance = next((g for g in self.guidances if g.gid == gid), None)
        if guidance is None:
            return None
        notices, spans = [], []
        for basis in guidance.basis:
            notice = self.notices.get(basis.notice_id)
            if notice:
                notices.append(notice)
            spans.append(basis)
        return TraceResult(guidance, notices, spans)

    # ------------------------------------------------------------------
    # 查询视图
    # ------------------------------------------------------------------
    def active(self) -> list[Guidance]:
        """现行且可直接发布的指引；机器译文派生指引核实前不纳入。"""

        return [
            g for g in self.guidances
            if g.status is GuidanceStatus.ACTIVE and not g.translation_derived
        ]

    def active_all(self) -> list[Guidance]:
        """包含译文派生在内的全部 ACTIVE 指引，供审计与核对使用。"""

        return [g for g in self.guidances if g.status is GuidanceStatus.ACTIVE]

    def by_status(self, status: GuidanceStatus) -> list[Guidance]:
        return [g for g in self.guidances if g.status is status]

    def affected_by_notice(self, notice_id: str) -> list[Guidance]:
        """返回被某通告（封路/更正）影响的全部指引。"""

        return [
            g for g in self.guidances
            if g.status in (GuidanceStatus.INVALIDATED, GuidanceStatus.SUPERSEDED)
            and (g.superseded_by == notice_id or notice_id in (b.notice_id for b in g.basis))
        ]
