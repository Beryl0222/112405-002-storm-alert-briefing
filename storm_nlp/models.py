"""领域数据模型。

设计要点：

* 每条要素抽取（Extraction）保留原文片段与所属通告编号，保证任何指引都可回溯；
* 效力等级（ForceLevel）区分「已确认命令 / 预警建议 / 居民转述」，转述永远不能直接成为命令；
* 指引（Guidance）携带状态与失效/被取代原因，更正发生时可逐条说明影响。
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class Language(str, enum.Enum):
    ZH = "zh"
    EN = "en"


class SourceKind(str, enum.Enum):
    """通告来源类型，决定默认效力与处理方式。"""

    OFFICIAL = "official-bulletin"
    ADDENDUM = "local-addendum"
    RELAY = "resident-report"
    MACHINE_TRANSLATION = "machine-translation"


class ForceLevel(str, enum.Enum):
    """语句效力等级。"""

    ORDER = "order"        # 已确认的命令/安排（封路令、定时开放）
    ADVISORY = "advisory"  # 预警中的建议
    RELAY = "relay"        # 居民转述，未核实


class Audience(str, enum.Enum):
    GENERAL = "general"
    WHEELCHAIR = "wheelchair"
    FERRY = "ferry"


class ActionType(str, enum.Enum):
    OPEN = "open"          # 开放（避护点/通道）
    CLOSE = "close"        # 封闭（桥/路/通道）
    ROUTE = "route"        # 前往/路线
    AVOID = "avoid"        # 禁止/请勿通行
    SUSPEND = "suspend"    # 停航/停止使用（运营中断）
    SERVICE = "service"    # 运营时刻安排（如末班船时间、保持运营）
    GATHER = "gather"      # 集合
    UNKNOWN = "unknown"


class GuidanceStatus(str, enum.Enum):
    ACTIVE = "active"            # 现行有效，可发布
    SUPERSEDED = "superseded"    # 被更正后的新指引取代
    INVALIDATED = "invalidated"  # 因封路等事件失效
    BLOCKED = "blocked"          # 未通过发布闸门，不得下发
    PENDING = "pending"          # 居民转述，待核实


@dataclass(frozen=True)
class Condition:
    """适用条件，例如「潮位低于一米二」。"""

    kind: str                       # tide_below / tide_recede
    raw: str
    value: Optional[float] = None   # 潮位阈值（米）

    def describe(self) -> str:
        if self.kind == "tide_below":
            return f"潮位低于 {self.value} 米"
        if self.kind == "tide_recede":
            return "潮位回落"
        return self.raw


@dataclass(frozen=True)
class TimeWindow:
    """生效时间窗；起止均可缺省，结束也可能由条件而非时刻决定。"""

    raw: str
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    end_condition: Optional[Condition] = None

    def effective_at(self, moment: datetime) -> bool:
        if self.start and moment < self.start:
            return False
        if self.end and moment > self.end:
            return False
        return True

    def describe(self) -> str:
        parts = [self.raw]
        if self.start:
            parts.append(f"起 {self.start:%Y-%m-%d %H:%M}")
        if self.end:
            parts.append(f"止 {self.end:%Y-%m-%d %H:%M}")
        if self.end_condition:
            parts.append(f"结束条件：{self.end_condition.describe()}")
        return "（".join([parts[0]] + [p + "）" for p in parts[1:]]) if len(parts) > 1 else parts[0]


@dataclass
class Notice:
    """一条原始通告（含机器译文），原文永不丢弃。"""

    id: str
    language: Language
    kind: SourceKind
    text: str
    received_at: datetime
    translation_of: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "language": self.language.value,
            "kind": self.kind.value,
            "text": self.text,
            "received_at": self.received_at.isoformat(timespec="minutes"),
            "translation_of": self.translation_of,
        }


@dataclass
class Extraction:
    """从一个分句中抽取出的可执行要素。"""

    notice_id: str
    clause_index: int
    language: Language
    force: ForceLevel
    action: ActionType
    span: str
    negated: bool = False
    audience: Audience = Audience.GENERAL
    place_id: Optional[str] = None          # 解析到的登记地点；None 表示未登记或泛指
    mention: Optional[str] = None           # 原文中实际出现的地名文字
    generic_place: bool = False             # 「所有避护点 / all shelters」这类泛指
    related_place_ids: list[str] = field(default_factory=list)
    window: Optional[TimeWindow] = None
    condition: Optional[Condition] = None
    issues: list[str] = field(default_factory=list)
    translation_blocked: bool = False
    translation_derived: bool = False       # 来自机器译文，核实前不得作为发布依据
    scope_clause: bool = False              # 仅说明适用范围，不构成独立命令
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    @property
    def ref(self) -> str:
        """溯源引用编号，例如 N-01#2。"""
        return f"{self.notice_id}#{self.clause_index}"


@dataclass(frozen=True)
class BasisRef:
    """指引所依据的原文位置。"""

    notice_id: str
    clause_index: int
    span: str


@dataclass
class Guidance:
    """一条可发布的避护指引及其生命周期状态。"""

    gid: str
    kind: ActionType
    subject_id: Optional[str]
    audience: Audience
    title: str
    window: Optional[TimeWindow]
    basis: list[BasisRef] = field(default_factory=list)
    route_nodes: list[str] = field(default_factory=list)
    route_edges: list[str] = field(default_factory=list)
    route_detail: str = ""
    status: GuidanceStatus = GuidanceStatus.ACTIVE
    block_reasons: list[str] = field(default_factory=list)
    invalidated_reason: str = ""
    superseded_by: Optional[str] = None
    is_relay: bool = False
    translation_derived: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def cite(self) -> str:
        return "、".join(f"{b.notice_id}#{b.clause_index}" for b in self.basis)


@dataclass
class Correction:
    """更正通告解析结果。"""

    notice_id: str
    place_renames: list[tuple[str, str]] = field(default_factory=list)   # (旧名, 新名)
    time_changes: list[tuple[str, Optional[datetime], Optional[datetime], str]] = field(default_factory=list)
    # 每项：(对象描述, 旧时间, 新时间, 原文片段)


@dataclass
class TranslationIssue:
    severity: str   # blocker / warning
    code: str
    detail: str
    source_ref: Optional[str] = None
    target_ref: Optional[str] = None


@dataclass
class TranslationReport:
    source_notice_id: str
    target_notice_id: str
    issues: list[TranslationIssue] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(i.severity == "blocker" for i in self.issues)


@dataclass
class IngestionReport:
    notice_id: str
    extraction_count: int = 0
    guidance_issued: list[str] = field(default_factory=list)
    guidance_blocked: list[tuple[str, list[str]]] = field(default_factory=list)
    pending_relays: list[str] = field(default_factory=list)
    translation_report: Optional[TranslationReport] = None
    notes: list[str] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return not (self.translation_report and self.translation_report.blocked)
