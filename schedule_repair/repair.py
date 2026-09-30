"""最小移动修复求解器（精确搜索）。

思路（避免完整笛卡尔积展开）：
1. 每个课节候选位置按需编码为 (起点, 教室)，资源占用用 40 位整数位掩码表示；
2. 按"候选之间可能发生资源冲突"构建交互图，分解连通分量：
   不含新课的分量直接保留基线（不可能被间接波及）；
3. 含新课的分量用「移动数预算迭代加深 + MRV 前向检查」精确求解，
   预算从 0 递增，首个可行预算即全局最优；任何预算下都完整搜索，
   超时/预算耗尽不会被报告为无解。
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import (
    DAYS,
    PERIODS,
    Lesson,
    Placement,
    Problem,
    RepairResult,
    Start,
    occupancy,
    valid_start,
)
from .validate import validate_problem


def _cell_bits(start: Start, length: int) -> int:
    bits = 0
    for day, period in occupancy(start, length):
        bits |= 1 << (day * PERIODS + period)
    return bits


@dataclass
class Candidate:
    index: int
    start: Start
    room: str
    cost: int  # 旧课偏离基线为 1，否则 0；新课恒为 0
    masks: dict[str, int]


def _build_candidates(
    lessons: list[Lesson], baseline: dict[str, Placement]
) -> dict[str, list[Candidate]]:
    candidates: dict[str, list[Candidate]] = {}
    for lesson in lessons:
        cands: list[Candidate] = []
        base = baseline.get(lesson.lesson_id)
        for start in sorted(lesson.starts, key=lambda s: (s.day, s.period)):
            if not valid_start(start, lesson.length):
                continue
            bits = _cell_bits(start, lesson.length)
            for room in sorted(lesson.rooms):
                cost = 0
                if base is not None and (start != base.start or room != base.room):
                    cost = 1
                masks = {
                    f"T:{lesson.teacher}": bits,
                    f"C:{lesson.klass}": bits,
                    f"R:{room}": bits,
                }
                cands.append(
                    Candidate(len(cands), start, room, cost, masks)
                )
        candidates[lesson.lesson_id] = cands
    return candidates


def _candidates_conflict(c1: Candidate, c2: Candidate, lesson1: Lesson,
                         lesson2: Lesson) -> bool:
    if lesson1.teacher == lesson2.teacher and (
        c1.masks[f"T:{lesson1.teacher}"] & c2.masks[f"T:{lesson2.teacher}"]
    ):
        return True
    if lesson1.klass == lesson2.klass and (
        c1.masks[f"C:{lesson1.klass}"] & c2.masks[f"C:{lesson2.klass}"]
    ):
        return True
    if c1.room == c2.room and (c1.masks[f"R:{c1.room}"] & c2.masks[f"R:{c2.room}"]):
        return True
    return False


class DSU:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _time_domain(lesson: Lesson, baseline_placement: Placement | None) -> int:
    """课节在任意可行/停留安排下可能占用的时间单元并集（40 位）。

    除允许起点外还必须并入基线位置：分量分解必须覆盖
    「新课分量里的搬动课」与「停留在基线的其它分量旧课」之间的交互。
    """
    bits = 0
    for start in lesson.starts:
        if valid_start(start, lesson.length):
            bits |= _cell_bits(start, lesson.length)
    if baseline_placement is not None:
        bits |= _cell_bits(baseline_placement.start, lesson.length)
    return bits


def _components(
    lessons: list[Lesson], baseline: dict[str, Placement]
) -> list[list[int]]:
    """按"共享教师/班级/教室且时间域可能相交"分解交互图连通分量。"""
    n = len(lessons)
    domains = [_time_domain(lesson, baseline.get(lesson.lesson_id))
               for lesson in lessons]
    dsu = DSU(n)

    def link_groups(groups: dict[str, list[int]]) -> None:
        for group in groups.values():
            for a_pos in range(len(group)):
                ia = group[a_pos]
                for b_pos in range(a_pos + 1, len(group)):
                    ib = group[b_pos]
                    if domains[ia] & domains[ib]:
                        dsu.union(ia, ib)

    by_teacher: dict[str, list[int]] = {}
    by_klass: dict[str, list[int]] = {}
    by_room: dict[str, list[int]] = {}
    for i, lesson in enumerate(lessons):
        by_teacher.setdefault(lesson.teacher, []).append(i)
        by_klass.setdefault(lesson.klass, []).append(i)
        for room in lesson.rooms:
            by_room.setdefault(room, []).append(i)
    link_groups(by_teacher)
    link_groups(by_klass)
    link_groups(by_room)

    comp_map: dict[int, list[int]] = {}
    for i in range(n):
        comp_map.setdefault(dsu.find(i), []).append(i)
    return list(comp_map.values())


class _ComponentSolver:
    """单个交互分量的精确求解器（结构预计算一次，预算可复用）。"""

    def __init__(
        self,
        lessons: list[Lesson],
        indices: list[int],
        candidates: dict[str, list[Candidate]],
        baseline: dict[str, Placement],
        locked: frozenset[str],
        new_ids: frozenset[str],
    ) -> None:
        self.comp_lessons = [lessons[i] for i in indices]
        self.n = len(indices)
        self.cands = [candidates[lesson.lesson_id] for lesson in self.comp_lessons]
        self.locked = locked
        self.new_ids = new_ids
        self.baseline = baseline

        self.peers: list[list[int]] = [[] for _ in range(self.n)]
        self.masks: dict[tuple[int, int], list[int]] = {}
        self.base_index: dict[int, int] = {}
        self._build_static()

        full = [(1 << len(cands)) - 1 for cands in self.cands]
        # 锁定课节只能使用基线安排。
        for pos, lesson in enumerate(self.comp_lessons):
            if lesson.lesson_id in locked:
                bi = self.base_index.get(pos)
                full[pos] = 0 if bi is None else (1 << bi)
        self.full_masks = full

    def _build_static(self) -> None:
        n = self.n
        for a in range(n):
            la = self.comp_lessons[a]
            for b in range(a + 1, n):
                lb = self.comp_lessons[b]
                forward: list[int] = []
                for ca in self.cands[a]:
                    mask = 0
                    for cb in self.cands[b]:
                        if _candidates_conflict(ca, cb, la, lb):
                            mask |= 1 << cb.index
                    forward.append(mask)
                self.masks[(a, b)] = forward
                if any(forward):
                    self.peers[a].append(b)
                    self.peers[b].append(a)
                # 转置掩码：(b, a)[k] 表示 b 取第 k 候选时与 a 的冲突位。
                trans = [0] * len(self.cands[b])
                for ca_idx, mask in enumerate(forward):
                    bit = mask
                    while bit:
                        low = bit & -bit
                        cb_idx = low.bit_length() - 1
                        trans[cb_idx] |= 1 << ca_idx
                        bit ^= low
                self.masks[(b, a)] = trans

        for pos, lesson in enumerate(self.comp_lessons):
            base = self.baseline.get(lesson.lesson_id)
            if base is not None:
                for cand in self.cands[pos]:
                    if cand.start == base.start and cand.room == base.room:
                        self.base_index[pos] = cand.index
                        break

    def solve(self, budget: int) -> dict[int, int] | None:
        domains = list(self.full_masks)
        assignment: dict[int, int] = {}
        cands = self.cands
        masks = self.masks
        peers = self.peers
        comp_lessons = self.comp_lessons
        base_index = self.base_index
        locked = self.locked
        new_ids = self.new_ids
        n = self.n

        def dfs(spent: int) -> dict[int, int] | None:
            # 下界：剩余旧课中候选域已不含基线的课节必然要移动。
            lower = spent
            for other in range(n):
                if other in assignment:
                    continue
                bi = base_index.get(other)
                if bi is not None and not (domains[other] & (1 << bi)):
                    lower += 1
            if lower > budget:
                return None

            # MRV：候选数最少者优先；同数时锁定课、新课、旧课依次优先。
            best = -1
            best_key: tuple[int, int, int] | None = None
            for pos in range(n):
                if pos in assignment:
                    continue
                count = domains[pos].bit_count()
                if count == 0:
                    return None
                lid = comp_lessons[pos].lesson_id
                rank = 0 if lid in locked else (1 if lid in new_ids else 2)
                key = (count, rank, pos)
                if best_key is None or key < best_key:
                    best, best_key = pos, key
            if best < 0:
                return dict(assignment)

            pos = best
            lesson = comp_lessons[pos]
            base_idx = base_index.get(pos)
            values: list[int] = []
            bit = domains[pos]
            while bit:
                low = bit & -bit
                values.append(low.bit_length() - 1)
                bit ^= low

            def value_key(cidx: int) -> tuple[int, int]:
                if cidx == base_idx:
                    return (0, 0)
                return (cands[pos][cidx].cost, cidx)

            values.sort(key=value_key)

            removed: list[tuple[int, int]] = []
            for cidx in values:
                cand = cands[pos][cidx]
                cost = 0 if lesson.lesson_id in new_ids else cand.cost
                if spent + cost > budget:
                    continue

                ok = True
                for other in peers[pos]:
                    if other in assignment:
                        continue
                    # (x, y)[k] = x 取第 k 候选时与 y 的候选冲突位掩码。
                    kill = masks[(pos, other)][cidx]
                    new_domain = domains[other] & ~kill
                    if new_domain == 0:
                        ok = False
                        break
                    if new_domain != domains[other]:
                        removed.append((other, domains[other]))
                        domains[other] = new_domain

                try:
                    if ok:
                        assignment[pos] = cidx
                        result = dfs(spent + cost)
                        if result is not None:
                            return result
                        del assignment[pos]
                finally:
                    while removed:
                        other, old_domain = removed.pop()
                        domains[other] = old_domain

            return None

        return dfs(0)


def repair(problem: Problem) -> RepairResult:
    """返回搬动旧课数量最少的完整课表；无解时返回 feasible=False。

    搜索是完备的：每个移动数预算都做完整回溯，预算耗尽不会被当作无解；
    只有证明所有预算均不可行时才返回无解。
    """
    errors = validate_problem(problem)
    if errors:
        return RepairResult(feasible=False, reason="; ".join(errors))

    lessons = problem.lessons
    baseline = problem.baseline
    locked = problem.locked
    new_ids = frozenset(
        lesson.lesson_id for lesson in lessons if lesson.lesson_id not in baseline
    )

    candidates = _build_candidates(lessons, baseline)
    for lesson in lessons:
        if not candidates[lesson.lesson_id]:
            return RepairResult(
                feasible=False,
                reason=f"NO_CANDIDATE:{lesson.lesson_id}: 课节不存在任何合法候选位置",
            )

    chosen: dict[str, Placement] = {}
    total_moved: set[str] = set()

    for comp in _components(lessons, baseline):
        comp_ids = {lessons[i].lesson_id for i in comp}
        if comp_ids.isdisjoint(new_ids):
            # 不含新课的分量不可能被间接波及，整体保留基线。
            for lesson_id in comp_ids:
                chosen[lesson_id] = baseline[lesson_id]
            continue

        comp_lessons = [lessons[i] for i in comp]
        old_count = sum(1 for lesson in comp_lessons if lesson.lesson_id in baseline)
        solver = _ComponentSolver(
            lessons, comp, candidates, baseline, locked, new_ids
        )
        comp_solution: dict[str, int] | None = None
        for comp_budget in range(old_count + 1):
            comp_solution = solver.solve(comp_budget)
            if comp_solution is not None:
                break
        if comp_solution is None:
            return RepairResult(
                feasible=False,
                reason="INFEASIBLE: 不存在满足全部硬约束的完整安排",
            )

        for pos, cidx in comp_solution.items():
            lesson = comp_lessons[pos]
            cand = candidates[lesson.lesson_id][cidx]
            placement = Placement(cand.start, cand.room)
            chosen[lesson.lesson_id] = placement
            base = baseline.get(lesson.lesson_id)
            if base is not None and placement != base:
                total_moved.add(lesson.lesson_id)

    return RepairResult(
        feasible=True,
        assignments=chosen,
        moved=frozenset(total_moved),
        optimal=True,
    )
