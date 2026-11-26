"""道路网络、封路事件与无障碍寻路。

网络由节点（登记地点/路口）和边（道路、桥、轮渡）组成。桥与涵洞作为
「通道闸口」绑定在边的 gate_place 上；封路命令关闭闸口后，所有经过它的边
立即不可用，旧路线据此判定失效。

寻路支持：

* mode='walk' / 'wheelchair' / 'ferry'，约束不可通行的边；
* 已关闭闸口一律绕行；
* 返回节点序列与所依据的边编号，供指引溯源。
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Optional

from .models import BasisRef, GuidanceStatus
from .places import PlaceKind, PlaceRegistry


@dataclass
class RoadEdge:
    id: str
    a: str
    b: str
    label: str
    modes: list[str]                       # 支持的通行方式
    gate_place_id: Optional[str] = None    # 桥/涵洞等受控通道
    minutes: int = 10
    closed: bool = False
    closed_by: Optional[BasisRef] = None

    def usable(self, mode: str) -> bool:
        if self.closed:
            return False
        return mode in self.modes

    def endpoints(self) -> tuple[str, str]:
        return self.a, self.b


@dataclass
class Route:
    nodes: list[str]
    edges: list[str]
    minutes: int
    detail: str
    feasible: bool

    @classmethod
    def unavailable(cls, reason: str) -> "Route":
        return cls([], [], 0, reason, False)


@dataclass
class ClosureEvent:
    gate_place_id: str
    basis: BasisRef


class RoadNetwork:
    def __init__(self, registry: PlaceRegistry, edges: Optional[list[RoadEdge]] = None):
        self.registry = registry
        self.edges: dict[str, RoadEdge] = {}
        self.adj: dict[str, list[tuple[str, RoadEdge]]] = {}
        self.closure_log: list[ClosureEvent] = []
        for edge in edges or []:
            self.add_edge(edge)

    def add_edge(self, edge: RoadEdge) -> None:
        self.edges[edge.id] = edge
        self.adj.setdefault(edge.a, []).append((edge.b, edge))
        self.adj.setdefault(edge.b, []).append((edge.a, edge))

    def close_gate(self, gate_place_id: str, basis: BasisRef) -> list[str]:
        """关闭闸口，返回受影响而关闭的边编号。"""

        affected: list[str] = []
        for edge in self.edges.values():
            if edge.gate_place_id == gate_place_id and not edge.closed:
                edge.closed = True
                edge.closed_by = basis
                affected.append(edge.id)
        self.closure_log.append(ClosureEvent(gate_place_id, basis))
        return affected

    def edges_through_gate(self, gate_place_id: str) -> list[RoadEdge]:
        return [e for e in self.edges.values() if e.gate_place_id == gate_place_id]

    def is_gate_closed(self, gate_place_id: str) -> bool:
        return any(e.closed for e in self.edges_through_gate(gate_place_id))

    def shortest_route(self, origin: str, destination: str, mode: str) -> Route:
        if origin not in self.adj or destination not in self.adj:
            return Route.unavailable(f"网络中缺少节点 {origin} 或 {destination}")

        dist = {origin: 0}
        prev: dict[str, tuple[str, RoadEdge]] = {}
        heap: list[tuple[int, str]] = [(0, origin)]

        while heap:
            cost, node = heapq.heappop(heap)
            if cost > dist.get(node, float("inf")):
                continue
            if node == destination:
                break
            for nxt, edge in self.adj.get(node, []):
                if not edge.usable(mode):
                    continue
                new_cost = cost + edge.minutes
                if new_cost < dist.get(nxt, float("inf")):
                    dist[nxt] = new_cost
                    prev[nxt] = (node, edge)
                    heapq.heappush(heap, (new_cost, nxt))

        if destination not in dist:
            closed = [e.id for e in self.edges.values() if e.closed]
            return Route.unavailable(
                f"在当前封路（{', '.join(closed) or '无'}）与 {mode} 通行约束下无可行路线"
            )

        nodes, edge_ids = [destination], []
        cursor = destination
        while cursor != origin:
            parent, edge = prev[cursor]
            edge_ids.append(edge.id)
            nodes.append(parent)
            cursor = parent
        nodes.reverse()
        edge_ids.reverse()
        detail = self._describe(nodes, edge_ids, mode, dist[destination])
        return Route(nodes, edge_ids, dist[destination], detail, True)

    def _describe(self, nodes: list[str], edge_ids: list[str], mode: str, minutes: int) -> str:
        names = [self.registry.display(n) for n in nodes]
        used = [self.edges[eid] for eid in edge_ids]
        gates = [self.registry.display(e.gate_place_id) for e in used if e.gate_place_id]
        mode_zh = {"walk": "步行", "wheelchair": "轮椅", "ferry": "轮渡"}.get(mode, mode)
        text = f"{mode_zh}路线：" + " → ".join(names) + f"，预计 {minutes} 分钟"
        if gates:
            text += f"；途经通道：{'、'.join(dict.fromkeys(gates))}"
        return text

    def route_uses_closed_gate(self, route_edge_ids: list[str]) -> Optional[str]:
        for edge_id in route_edge_ids:
            edge = self.edges.get(edge_id)
            if edge and edge.closed:
                return edge.gate_place_id
        return None

    @classmethod
    def from_dicts(cls, registry: PlaceRegistry, rows: list[dict]) -> "RoadNetwork":
        edges = [
            RoadEdge(
                id=row["id"],
                a=row["a"],
                b=row["b"],
                label=row.get("label", ""),
                modes=list(row["modes"]),
                gate_place_id=row.get("gate"),
                minutes=row.get("minutes", 10),
            )
            for row in rows
        ]
        return cls(registry, edges)
