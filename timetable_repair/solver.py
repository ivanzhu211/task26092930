"""repair 实现：穷举回溯 + 前向检查 + 分支定界的最小扰动求解器。

求解目标：满足全部硬约束的前提下，被移动的旧课数量最少。

设计要点：
- 每个课节的候选放置（起点 x 教室）只在预处理时按需生成一次，
  搜索过程中不做完整笛卡尔积展开，内存只与各课节候选数之和相关。
- 锁定课节固定在基线；其余课节按 MRV 选择变量、按
  "基线优先 / 冲突最少优先" 排列取值，配合前向检查传播。
- 分支定界保证：找到第一个可行解后继续以其移动数为上界剪枝，
  穷举完整搜索空间后才能宣布无解，不存在超时误判（无超时截断）。
- 间接冲突通过传播自然处理：一个旧课搬走后若落入其他旧课的基线
  位置，后者会被级联迫使移动。
"""

from __future__ import annotations

from dataclasses import dataclass

from .checker import validate_problem
from .model import Placement, Problem, RepairResult


@dataclass(frozen=True)
class _Candidate:
    """一个课节的一种完整放置（起点 + 教室）及其资源占用。"""

    placement: Placement
    occupied: frozenset[tuple[str, str, int, int]]


@dataclass
class _Compiled:
    """预处理后的问题。"""

    lesson_ids: list[str]
    duration: dict[str, int]
    candidates: dict[str, list[_Candidate]]
    baseline_index: dict[str, int]
    locked: set[str]
    is_old: dict[str, bool]
    pairs: list[tuple[str, str]]


_RESOURCE_KINDS = ("teacher", "class", "room")


def _build_candidates(lesson) -> list[_Candidate]:
    result: list[_Candidate] = []
    for start in lesson.allowed_starts:
        if start.period + lesson.duration > 8:
            continue
        for room in lesson.allowed_rooms:
            occupied = set()
            for offset in range(lesson.duration):
                period = start.period + offset
                occupied.add(("teacher", lesson.teacher, start.day, period))
                occupied.add(("class", lesson.klass, start.day, period))
                occupied.add(("room", room, start.day, period))
            result.append(
                _Candidate(Placement(start, room), frozenset(occupied))
            )
    return result


def compile_problem(problem: Problem) -> tuple[_Compiled | None, list[str]]:
    """预处理：展开每个课节自身的候选放置并建立冲突对索引。

    候选展开是按课节逐个进行的单课节内组合（最多 8x4=32），不是
    全课表的笛卡尔积。
    """
    errors = validate_problem(problem)
    if errors:
        return None, errors

    compiled = _Compiled(
        lesson_ids=[],
        duration={},
        candidates={},
        baseline_index={},
        locked=set(problem.locked_ids),
        is_old={},
        pairs=[],
    )
    for lesson in problem.lessons:
        candidates = _build_candidates(lesson)
        if not candidates:
            return None, [f"课节无可行放置: {lesson.lesson_id}"]
        compiled.lesson_ids.append(lesson.lesson_id)
        compiled.duration[lesson.lesson_id] = lesson.duration
        compiled.candidates[lesson.lesson_id] = candidates
        compiled.is_old[lesson.lesson_id] = lesson.lesson_id in problem.baseline
        base = problem.baseline.get(lesson.lesson_id)
        if base is not None:
            index = next(
                (
                    i
                    for i, candidate in enumerate(
                        compiled.candidates[lesson.lesson_id]
                    )
                    if candidate.placement == base
                ),
                None,
            )
            if index is None:
                return None, [
                    f"基线安排不在课节候选范围内: {lesson.lesson_id}"
                ]
            compiled.baseline_index[lesson.lesson_id] = index

    for i, lesson_a in enumerate(problem.lessons):
        candidates_a = compiled.candidates[lesson_a.lesson_id]
        for lesson_b in problem.lessons[i + 1 :]:
            candidates_b = compiled.candidates[lesson_b.lesson_id]
            if not _can_conflict(lesson_a, lesson_b):
                continue
            if not _pair_conflicts(candidates_a, candidates_b):
                continue
            compiled.pairs.append((lesson_a.lesson_id, lesson_b.lesson_id))

    return compiled, []


def _can_conflict(lesson_a, lesson_b) -> bool:
    """两课节是否共享任一资源类型（无共享则任何放置都不会冲突）。"""
    return (
        lesson_a.teacher == lesson_b.teacher
        or lesson_a.klass == lesson_b.klass
        or bool(
            set(lesson_a.allowed_rooms) & set(lesson_b.allowed_rooms)
        )
    )


def _pair_conflicts(
    candidates_a: list[_Candidate], candidates_b: list[_Candidate]
) -> bool:
    """两课节的候选之间是否存在至少一对冲突放置。"""
    for candidate_a in candidates_a:
        for candidate_b in candidates_b:
            if not candidate_a.occupied.isdisjoint(candidate_b.occupied):
                return True
    return False


class _Solver:
    """穷举回溯求解器（分支定界保证最优 / 完整证明无解）。"""

    def __init__(self, problem: Problem, compiled: _Compiled) -> None:
        self.problem = problem
        self.compiled = compiled
        self.ids = compiled.lesson_ids
        self.n = len(self.ids)
        self.index = {lesson_id: i for i, lesson_id in enumerate(self.ids)}
        self.cand = [compiled.candidates[lesson_id] for lesson_id in self.ids]
        self.is_old = [compiled.is_old[lesson_id] for lesson_id in self.ids]
        self.baseline = [
            compiled.baseline_index.get(lesson_id, -1) for lesson_id in self.ids
        ]
        self.locked = [lesson_id in compiled.locked for lesson_id in self.ids]

        self.neighbors: list[list[int]] = [[] for _ in range(self.n)]
        for id_a, id_b in compiled.pairs:
            i, j = self.index[id_a], self.index[id_b]
            self.neighbors[i].append(j)
            self.neighbors[j].append(i)

        self.domains: list[set[int]] = [
            set(range(len(cands))) for cands in self.cand
        ]
        self.assigned: list[int] = [-1] * self.n
        self.trail: list[tuple] = []
        self.best_cost = self.n + 1
        self.best_choice: list[int] | None = None

    # ---- 成本 ----
    def _cost(self, var: int, candidate_index: int) -> int:
        return 1 if self.is_old[var] and candidate_index != self.baseline[var] else 0

    def _lower_bound(self) -> int:
        total = 0
        for var in range(self.n):
            if self.assigned[var] >= 0:
                continue
            live = self.domains[var]
            if not live:
                return self.best_cost
            if self.is_old[var] and self.baseline[var] in live:
                continue
            if self.is_old[var]:
                total += 1
        return total

    # ---- trail 机制 ----
    def _remove(self, var: int, candidate_index: int) -> None:
        self.domains[var].discard(candidate_index)
        self.trail.append(("r", var, candidate_index))

    def _mark(self) -> int:
        return len(self.trail)

    def _rollback(self, marker: int) -> None:
        while len(self.trail) > marker:
            kind, var, value = self.trail.pop()
            if kind == "r":
                self.domains[var].add(value)
            else:
                self.assigned[var] = -1

    # ---- 赋值与传播 ----
    def _try_assign(self, var: int, candidate_index: int) -> bool:
        self.assigned[var] = candidate_index
        self.trail.append(("a", var, candidate_index))
        occupied = self.cand[var][candidate_index].occupied
        for neighbor in self.neighbors[var]:
            if self.assigned[neighbor] >= 0:
                chosen = self.cand[neighbor][self.assigned[neighbor]]
                if not chosen.occupied.isdisjoint(occupied):
                    return False
                continue
            live = self.domains[neighbor]
            for other_index in list(live):
                other = self.cand[neighbor][other_index]
                if not other.occupied.isdisjoint(occupied):
                    self._remove(neighbor, other_index)
            if not self.domains[neighbor]:
                return False
        return True

    def _propagate_singletons(self) -> tuple[bool, int]:
        """反复强制赋值当前只剩一个候选的未分配课节，返回是否成功与增量成本。"""
        extra_cost = 0
        while True:
            singleton = -1
            for var in range(self.n):
                if self.assigned[var] < 0 and len(self.domains[var]) == 1:
                    singleton = var
                    break
            if singleton < 0:
                return True, extra_cost
            only = next(iter(self.domains[singleton]))
            extra_cost += self._cost(singleton, only)
            if not self._try_assign(singleton, only):
                return False, extra_cost

    # ---- 变量 / 取值排序 ----
    def _select_var(self) -> int:
        best_var = -1
        best_key = None
        for var in range(self.n):
            if self.assigned[var] >= 0:
                continue
            size = len(self.domains[var])
            if size == 0:
                return var
            key = (
                size,
                0 if self.is_old[var] else -1,
                -len(self.neighbors[var]),
                self.ids[var],
            )
            if best_key is None or key < best_key:
                best_key = key
                best_var = var
        return best_var

    def _ordered_values(self, var: int) -> list[int]:
        live = list(self.domains[var])

        def conflict_count(candidate_index: int) -> int:
            occupied = self.cand[var][candidate_index].occupied
            count = 0
            for neighbor in self.neighbors[var]:
                if self.assigned[neighbor] >= 0:
                    continue
                for other_index in self.domains[neighbor]:
                    other = self.cand[neighbor][other_index]
                    if not other.occupied.isdisjoint(occupied):
                        count += 1
            return count

        live.sort(
            key=lambda ci: (
                self._cost(var, ci),
                conflict_count(ci),
                ci,
            )
        )
        return live

    # ---- 搜索主循环 ----
    def solve(self) -> bool:
        for var in range(self.n):
            if not self.locked[var]:
                continue
            if not self._try_assign(var, self.baseline[var]):
                return False
        ok, _ = self._propagate_singletons()
        if not ok:
            return False
        if any(not domain for domain in self.domains):
            return False
        self._dfs(0)
        return self.best_choice is not None

    def _dfs(self, cost: int) -> None:
        if cost + self._lower_bound() >= self.best_cost:
            return
        var = self._select_var()
        if var < 0:
            self.best_cost = cost
            self.best_choice = self.assigned[:]
            return
        if not self.domains[var]:
            return
        for candidate_index in self._ordered_values(var):
            marker = self._mark()
            if not self._try_assign(var, candidate_index):
                self._rollback(marker)
                continue
            ok, extra = self._propagate_singletons()
            branch_cost = cost + self._cost(var, candidate_index) + extra
            if ok:
                self._dfs(branch_cost)
            self._rollback(marker)
            if self.best_cost == 0:
                return

    def build_result(self) -> RepairResult:
        if self.best_choice is None:
            return RepairResult(False, reason="不存在满足全部约束的安排（已穷举证明）")
        assignment: dict[str, Placement] = {}
        moved: set[str] = set()
        for var, lesson_id in enumerate(self.ids):
            candidate_index = self.best_choice[var]
            placement = self.cand[var][candidate_index].placement
            assignment[lesson_id] = placement
            if self.is_old[var] and candidate_index != self.baseline[var]:
                moved.add(lesson_id)
        return RepairResult(True, assignment, frozenset(moved))


def repair(problem: Problem) -> RepairResult:
    """返回移动旧课数最少的完整安排；无解时明确报告，绝不返回部分课表。"""
    compiled, errors = compile_problem(problem)
    if compiled is None:
        return RepairResult(False, reason="问题结构非法: " + "; ".join(errors))
    solver = _Solver(problem, compiled)
    if not solver.solve():
        return RepairResult(False, reason="不存在满足全部约束的安排（已穷举证明）")
    return solver.build_result()
