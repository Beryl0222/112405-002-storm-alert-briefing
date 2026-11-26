"""演练数据加载器。

数据文件全部是虚构演练资料。加载器只做 JSON → 领域对象的转换，
不执行任何外部代码；调用方以路径参数传入数据目录。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .graph import RoadNetwork
from .models import Language, Notice, SourceKind
from .places import Place, PlaceKind, PlaceRegistry

# 演练路网中的路口节点（非登记地点），登记后可在路线描述中显示中文名称
_JUNCTIONS = {
    "J-OLDTOWN": "老城路口",
    "J-NORTHBAY": "北湾路口",
    "J-HAIXI": "海西路口",
}


def _at(ref: datetime, token: str) -> datetime:
    hour, minute = token.split(":")
    return ref.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def load_registry(data_dir: str | Path) -> PlaceRegistry:
    path = Path(data_dir) / "places.json"
    rows = json.loads(path.read_text(encoding="utf-8"))["places"]
    registry = PlaceRegistry.from_dicts(rows)
    for node_id, label in _JUNCTIONS.items():
        registry.register(Place(node_id, label, PlaceKind.JUNCTION))
    return registry


def load_network(data_dir: str | Path, registry: PlaceRegistry) -> RoadNetwork:
    path = Path(data_dir) / "network.json"
    rows = json.loads(path.read_text(encoding="utf-8"))["edges"]
    return RoadNetwork.from_dicts(registry, rows)


def load_notices(data_dir: str | Path, ref_now: datetime) -> list[Notice]:
    path = Path(data_dir) / "notices.json"
    raw = json.loads(path.read_text(encoding="utf-8"))["notices"]
    notices: list[Notice] = []
    for row in raw:
        received = row.get("received_at")
        received_at = _at(ref_now, received) if received else ref_now
        notices.append(
            Notice(
                id=row["id"],
                language=Language(row["language"]),
                kind=SourceKind(row["kind"]),
                text=row["text"],
                received_at=received_at,
                translation_of=row.get("translation_of"),
            )
        )
    return notices


def load_inquiries(data_dir: str | Path) -> list[dict]:
    path = Path(data_dir) / "inquiries.json"
    return json.loads(path.read_text(encoding="utf-8"))["inquiries"]
