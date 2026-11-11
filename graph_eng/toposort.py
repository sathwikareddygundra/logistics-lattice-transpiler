"""Deterministic topological sort (T-42): Kahn's algorithm with a stable
tie-break (natural sort of node ids), raising the same typed error as the
cycle check when the graph is cyclic."""

from __future__ import annotations

import heapq
import re

from graph_eng.cycles import find_cycle


class CycleError(ValueError):
    def __init__(self, cycle: list[str]) -> None:
        super().__init__("graph contains a cycle: " + " -> ".join(cycle))
        self.cycle = cycle


def _natural(node_id: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", node_id))


def toposort(node_ids: list[str], edges: list[tuple[str, str]]) -> list[str]:
    indegree = dict.fromkeys(node_ids, 0)
    outgoing: dict[str, list[str]] = {n: [] for n in node_ids}
    for a, b in edges:
        outgoing[a].append(b)
        indegree[b] += 1
    ready = [(_natural(n), n) for n in node_ids if indegree[n] == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        _, node = heapq.heappop(ready)
        order.append(node)
        for nxt in outgoing[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(ready, (_natural(nxt), nxt))
    if len(order) != len(node_ids):
        raise CycleError(find_cycle(outgoing) or ["?"])
    return order
