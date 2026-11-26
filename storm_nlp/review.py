"""值班员五维核对报告。

按「地点、时间、对象、条件、行动要求」五个维度汇总每条抽取与每条指引，
并单列效力等级、译文问题与发布闸门结论，支撑值班员确认后再发布。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Audience,
    ForceLevel,
    Guidance,
    GuidanceStatus,
    IngestionReport,
)
from .places import PlaceRegistry


_FORCE_ZH = {
    ForceLevel.ORDER: "已确认命令",
    ForceLevel.ADVISORY: "预警建议",
    ForceLevel.RELAY: "居民转述",
}
_STATUS_ZH = {
    GuidanceStatus.ACTIVE: "现行有效",
    GuidanceStatus.SUPERSEDED: "已被取代",
    GuidanceStatus.INVALIDATED: "已失效",
    GuidanceStatus.BLOCKED: "已拦截",
    GuidanceStatus.PENDING: "待核实",
}
_AUDIENCE_ZH = {
    Audience.GENERAL: "全体居民",
    Audience.WHEELCHAIR: "轮椅使用者",
    Audience.FERRY: "夜班渡船乘客",
}


@dataclass
class ReviewRow:
    ref: str
    force: str
    place: str
    time: str
    audience: str
    condition: str
    action: str
    negated: bool
    issues: list[str]


class ReviewService:
    def __init__(self, manager, registry: PlaceRegistry):
        self.manager = manager
        self.registry = registry

    def extraction_rows(self) -> list[ReviewRow]:
        rows: list[ReviewRow] = []
        for notice_id, extractions in self.manager.extractions.items():
            for ex in extractions:
                rows.append(
                    ReviewRow(
                        ref=ex.ref,
                        force=_FORCE_ZH[ex.force],
                        place="泛指" if ex.generic_place else self.registry.display(ex.place_id),
                        time=ex.window.describe() if ex.window else "—",
                        audience=_AUDIENCE_ZH[ex.audience],
                        condition=ex.condition.describe() if ex.condition else "—",
                        action=ex.action.value + ("（否定）" if ex.negated else ""),
                        negated=ex.negated,
                        issues=list(ex.issues),
                    )
                )
        return rows

    def guidance_table(self) -> list[Guidance]:
        return list(self.manager.guidances)

    def render_text(self) -> str:
        lines: list[str] = []
        lines.append("=" * 78)
        lines.append("值班员核对报告（演练资料，内容均为虚构）")
        lines.append("=" * 78)
        lines.append("\n一、要素抽取五维核对（地点 / 时间 / 对象 / 条件 / 行动）")
        header = f"{'条款':<9}{'效力':<8}{'地点':<12}{'对象':<12}{'条件':<12}{'行动':<12}{'问题'}"
        lines.append(header)
        lines.append("-" * 78)
        for row in self.extraction_rows():
            lines.append(
                f"{row.ref:<9}{row.force:<8}{row.place:<12}{row.audience:<12}"
                f"{row.condition:<12}{row.action:<12}{','.join(row.issues) or '无'}"
            )
            lines.append(f"         时间：{row.time}")

        lines.append("\n二、指引生命周期")
        lines.append("-" * 78)
        for g in self.manager.guidances:
            tag = "（译文派生，核实前不发布）" if g.translation_derived else ""
            lines.append(
                f"[{g.gid}] {_STATUS_ZH[g.status]:<6} {g.title}{tag} ｜ 依据 {g.cite()}"
            )
            if g.status is GuidanceStatus.BLOCKED:
                lines.append(f"    拦截原因：{'; '.join(g.block_reasons)}")
            if g.invalidated_reason:
                lines.append(f"    失效/取代说明：{g.invalidated_reason}")
            if g.route_detail:
                lines.append(f"    路线：{g.route_detail}")

        lines.append("\n三、入库闸门与译文核对")
        lines.append("-" * 78)
        report: IngestionReport
        for report in self.manager.reports:
            verdict = "可发布" if report.publishable else "译文阻断，禁止按完整命令下发"
            lines.append(f"通告 {report.notice_id}：抽取 {report.extraction_count} 条 → {verdict}")
            if report.translation_report:
                for issue in report.translation_report.issues:
                    lines.append(f"    [{issue.severity}] {issue.code}: {issue.detail}")
            for gid, reasons in report.guidance_blocked:
                lines.append(f"    指引 {gid} 拦截：{', '.join(reasons)}")
            if report.pending_relays:
                lines.append(f"    待核实转述：{', '.join(report.pending_relays)}")

        lines.append("\n四、审计轨迹")
        lines.append("-" * 78)
        lines.extend(f"· {entry}" for entry in self.manager.audit)
        return "\n".join(lines)
