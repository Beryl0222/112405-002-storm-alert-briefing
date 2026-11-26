"""居民问询应答。

只依据当前仍有效（ACTIVE）的指引回答；转述（PENDING）明确标注未核实，
阻断（BLOCKED）与失效（INVALIDATED/SUPERSEDED）内容不用于答复。
每个回答附带原文溯源编号，值班员可据此核对后再发布。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Audience, Guidance, GuidanceStatus
from .places import PlaceRegistry

_INTENTS = [
    ("closed", re.compile(r"封|关闭|不能走|closed|shut", re.IGNORECASE)),
    ("bridge", re.compile(r"桥|bridge", re.IGNORECASE)),
    ("wheelchair", re.compile(r"轮椅|无障碍|wheelchair|accessib", re.IGNORECASE)),
    ("ferry", re.compile(r"船|轮渡|渡船|ferry|boat", re.IGNORECASE)),
    ("open", re.compile(r"开着|开放|还能去|open|available", re.IGNORECASE)),
    ("route", re.compile(r"怎么去|路线|怎么走|怎么走才能到|how do i (get|go)|route|way to", re.IGNORECASE)),
]


@dataclass
class Answer:
    question: str
    text: str
    cited: list[str] = field(default_factory=list)
    confident: bool = True


class InquiryService:
    def __init__(self, manager, registry: PlaceRegistry):
        self.manager = manager
        self.registry = registry

    def answer(self, question: str) -> Answer:
        place_id = self._find_place(question)
        intent = self._intent(question)
        audience = (
            Audience.WHEELCHAIR if re.search(r"轮椅|wheelchair", question, re.IGNORECASE)
            else Audience.FERRY if re.search(r"船|ferry|boat", question, re.IGNORECASE)
            else Audience.GENERAL
        )
        actives = [
            g for g in self.manager.guidances
            if g.status is GuidanceStatus.ACTIVE and not g.translation_derived
        ]
        pending = [g for g in self.manager.guidances if g.status is GuidanceStatus.PENDING]

        # 对象类意图最优先：轮椅/渡船乘客即便提到「封桥」也要给路线答复
        if audience is Audience.WHEELCHAIR:
            return self._wheelchair_answer(question, place_id)
        if audience is Audience.FERRY and intent == "ferry":
            return self._ferry_answer(question)
        # 桥/封闭类问询看网络中的实际闸口状态（封路命令已作用于网络）
        if intent in ("bridge", "closed"):
            return self._gate_answer(question, place_id)

        # 先处理转述类问询：任何时候转述都不能当事实答复
        relay_hits = [g for g in pending if place_id and g.subject_id == place_id]
        if relay_hits and intent == "open":
            g = relay_hits[0]
            return Answer(
                question,
                f"关于「{self.registry.display(place_id)}」一直开放的说法来自居民转述（依据 {g.cite()}），"
                "尚未经官方核实，不能据此安排，请等待值班中心确认。",
                [g.cite()], confident=False,
            )

        # open / route 统一走地点指引
        if place_id is None:
            return Answer(question, "未在问询中识别出登记地点，请值班员补充地点后再答复。", [], False)
        hits = [
            g for g in actives
            if g.subject_id == place_id
            and not g.translation_derived
            and (
                audience is Audience.GENERAL
                or g.audience in (audience, Audience.GENERAL)
            )
        ]
        # 轮椅问询补充同地点或同目的地的轮椅专用指引（如禁行涵洞的提示）
        if audience is Audience.WHEELCHAIR:
            dedicated = [
                g for g in self.manager.guidances
                if g.status is GuidanceStatus.ACTIVE
                and not g.translation_derived
                and g.audience is Audience.WHEELCHAIR
                and g not in hits
            ]
            hits = dedicated + hits
        if not hits:
            superseded = [g for g in self.manager.guidances if g.subject_id == place_id
                          and g.status in (GuidanceStatus.SUPERSEDED, GuidanceStatus.INVALIDATED)]
            if superseded:
                g = superseded[0]
                return Answer(
                    question,
                    f"「{self.registry.display(place_id)}」的旧指引（{g.cite()}）已{self._status_zh(g.status)}："
                    f"{g.invalidated_reason}。请使用当前有效指引，勿继续转发旧路线。",
                    [g.cite()], confident=False,
                )
            return Answer(question, f"目前没有关于「{self.registry.display(place_id)}」的有效指引。", [], False)

        lines, cited = [], []
        for g in hits:
            line = f"[{g.gid}] {g.title}"
            if g.window:
                line += f"；时间：{g.window.describe()}"
            if g.route_detail:
                line += f"；{g.route_detail}"
            line += f"（依据 {g.cite()}）"
            lines.append(line)
            cited.append(g.cite())
        return Answer(question, "\n".join(lines), cited, True)

    # ------------------------------------------------------------------
    def _gate_answer(self, question: str, place_id: str | None) -> Answer:
        closed_edges = [e for e in self.manager.network.edges.values() if e.closed]
        if place_id:
            closed_edges = [e for e in closed_edges if e.gate_place_id == place_id]
        if not closed_edges:
            target = self.registry.display(place_id) if place_id else "各通道"
            return Answer(question, f"目前没有关于{target}的已确认封路命令。", [])
        seen, lines, cited, invalidated_gids = set(), [], [], []
        for edge in closed_edges:
            if edge.gate_place_id in seen:
                continue
            seen.add(edge.gate_place_id)
            basis = edge.closed_by
            cited.append(f"{basis.notice_id}#{basis.clause_index}")
            lines.append(
                f"{self.registry.display(edge.gate_place_id)} 已封闭（依据 {basis.notice_id}#{basis.clause_index}），"
                "经过该通道的旧路线全部失效，请使用系统重算的替代路线，勿继续转发旧路线。"
            )
            for g in self.manager.guidances:
                if (
                    g.status is GuidanceStatus.INVALIDATED
                    and edge.id in g.route_edges
                    and g.gid not in invalidated_gids
                ):
                    invalidated_gids.append(g.gid)
        if invalidated_gids:
            lines.append(f"已失效路线指引：{'、'.join(invalidated_gids)}；替代路线见现行有效指引。")
        return Answer(question, "\n".join(lines), cited, True)

    def _ferry_answer(self, question: str) -> Answer:
        ferries = [
            g for g in self.manager.guidances
            if g.audience is Audience.FERRY
            and g.status is GuidanceStatus.ACTIVE
            and not g.translation_derived
        ]
        if not ferries:
            return Answer(question, "目前没有面向夜班渡船乘客的有效安排。", [], False)
        lines, cited = [], []
        for g in ferries:
            when = g.window.describe() if g.window else "以现场通知为准"
            lines.append(f"[{g.gid}] {g.title}；时间：{when}（依据 {g.cite()}）")
            cited.append(g.cite())
        return Answer(question, "\n".join(lines), cited, True)

    def _wheelchair_answer(self, question: str, place_id: str | None) -> Answer:
        wc_guidance = [
            g for g in self.manager.guidances
            if g.status is GuidanceStatus.ACTIVE
            and not g.translation_derived
            and g.audience is Audience.WHEELCHAIR
            and (place_id is None or g.subject_id == place_id)
        ]
        if not wc_guidance:
            return Answer(question, "暂无专门的轮椅可行路线，请值班员人工确认后再答复。", [], False)
        lines, cited = [], []
        for g in wc_guidance:
            if g.route_detail:
                lines.append(f"[{g.gid}] {g.title}；{g.route_detail}（依据 {g.cite()}）")
            else:
                lines.append(f"[{g.gid}] {g.title}（依据 {g.cite()}）")
            cited.append(g.cite())
        return Answer(question, "\n".join(lines), cited, True)

    def _find_place(self, text: str) -> str | None:
        for place in self.registry.all():
            for name in place.all_names():
                if name and name.lower() in text.lower():
                    return place.id
        return None

    @staticmethod
    def _intent(question: str) -> str:
        for name, pattern in _INTENTS:
            if pattern.search(question):
                return name
        return "open"

    @staticmethod
    def _status_zh(status: GuidanceStatus) -> str:
        return {
            GuidanceStatus.SUPERSEDED: "被更正取代",
            GuidanceStatus.INVALIDATED: "因封路失效",
            GuidanceStatus.BLOCKED: "拦截未发布",
        }.get(status, status.value)
