"""地名登记与跨语种译名管理。

同一地点的两个译名只能指向同一个登记点（place_id），不能重复建点。
登记表支持：

* 按中英文名、别名、拼写接近的误写解析地点；
* 为已登记地点学习新译名（合并而非新建），并留下合并记录供值班员核对；
* 区分避护点、通道闸口（桥/涵洞）、轮渡码头等类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional


class PlaceKind:
    SHELTER = "shelter"
    GATE = "gate"          # 桥、涵洞等可被封闭的通道
    TERMINAL = "terminal"  # 轮渡码头
    JUNCTION = "junction"


@dataclass
class Place:
    id: str
    name: str
    kind: str
    aliases: list[str] = field(default_factory=list)
    access: list[str] = field(default_factory=list)
    description: str = ""

    def all_names(self) -> list[str]:
        return [self.name, *self.aliases]


@dataclass(frozen=True)
class MergeRecord:
    """一次译名合并：没有新建地点，而是把新名字并入既有地点。"""

    learned_alias: str
    target_place_id: str
    reason: str


def _norm(text: str) -> str:
    return "".join(text.lower().split()).replace("，", "").replace(",", "").strip()


class PlaceRegistry:
    def __init__(self, places: Optional[list[Place]] = None):
        self._places: dict[str, Place] = {}
        self._index: dict[str, str] = {}
        self.merges: list[MergeRecord] = []
        for place in places or []:
            self.register(place)

    # ---------- 登记与去重 ----------
    def register(self, place: Place) -> MergeRecord | None:
        """登记地点；若其任一名称已指向既有地点，则合并别名而不是重复建点。"""

        existing = self._find_by_any_name(place)
        if existing is not None and existing != place.id:
            target = self._places[existing]
            for name in place.all_names():
                if name and name not in target.all_names():
                    target.aliases.append(name)
                    self._index[_norm(name)] = target.id
            record = MergeRecord(
                learned_alias=place.name,
                target_place_id=target.id,
                reason="名称与既有地点重合，按同一地点合并，未重复建点",
            )
            self.merges.append(record)
            return record
        self._places[place.id] = place
        for name in place.all_names():
            self._index[_norm(name)] = place.id
        return None

    def learn_alias(self, place_id: str, alias: str, reason: str = "通告中出现的新译名") -> MergeRecord:
        place = self.require(place_id)
        if alias not in place.all_names():
            place.aliases.append(alias)
            self._index[_norm(alias)] = place_id
        record = MergeRecord(alias, place_id, reason)
        self.merges.append(record)
        return record

    def _find_by_any_name(self, place: Place) -> Optional[str]:
        for name in place.all_names():
            hit = self._index.get(_norm(name))
            if hit:
                return hit
        return None

    # ---------- 解析 ----------
    def resolve(self, mention: str) -> Optional[str]:
        """把原文地名文字解析为登记地点 ID；查不到返回 None。"""

        if not mention:
            return None
        hit = self._index.get(_norm(mention))
        if hit:
            return hit
        # 容错：通告里的轻微误写（漏字、错字、英文拼写偏差）走相似度匹配
        best_id, best_score = None, 0.0
        key = _norm(mention)
        for name, place_id in self._index.items():
            score = SequenceMatcher(None, key, name).ratio()
            if score > best_score:
                best_id, best_score = place_id, score
        return best_id if best_score >= 0.72 else None

    def require(self, place_id: str) -> Place:
        if place_id not in self._places:
            raise KeyError(f"未登记的地点：{place_id}")
        return self._places[place_id]

    def get(self, place_id: str) -> Optional[Place]:
        return self._places.get(place_id)

    def display(self, place_id: Optional[str]) -> str:
        if place_id is None:
            return "（未登记地点）"
        place = self._places.get(place_id)
        return place.name if place else f"未知地点 {place_id}"

    def all(self) -> list[Place]:
        return list(self._places.values())

    @classmethod
    def from_dicts(cls, rows: list[dict]) -> "PlaceRegistry":
        places = [
            Place(
                id=row["id"],
                name=row["name"],
                kind=row.get("kind", PlaceKind.SHELTER),
                aliases=list(row.get("aliases", [])),
                access=list(row.get("access", [])),
                description=row.get("description", ""),
            )
            for row in rows
        ]
        return cls(places)
