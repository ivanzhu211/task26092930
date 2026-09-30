"""课表最小扰动修复库的自动化测试（仅标准库 unittest）。"""

from __future__ import annotations

import itertools
import time
import unittest

from schedule_repair import check, repair
from schedule_repair.model import (
    Lesson,
    Placement,
    Problem,
    Start,
)

R1 = "R1"
R2 = "R2"


def S(day: int, *periods: int) -> frozenset[Start]:
    return frozenset(Start(day, p) for p in periods)


def brute_force_min_moves(problem: Problem) -> int | None:
    """小规模暴力枚举，独立验证最优移动数；无解返回 None。"""
    lessons = problem.lessons
    options: list[list[Placement]] = []
    for lesson in lessons:
        opts = [
            Placement(start, room)
            for start in lesson.starts
            for room in lesson.rooms
        ]
        if lesson.lesson_id in problem.locked:
            opts = [problem.baseline[lesson.lesson_id]]
        options.append(opts)
        if not opts:
            return None

    best: int | None = None
    combo_by_id: dict[str, Placement]
    for combo in itertools.product(*options):
        combo_by_id = {
            lesson.lesson_id: placement
            for lesson, placement in zip(lessons, combo)
        }
        used: dict[tuple, str] = {}
        ok = True
        for lesson, placement in zip(lessons, combo):
            for i in range(lesson.length):
                for kind, resource in (
                    ("T", lesson.teacher),
                    ("C", lesson.klass),
                    ("R", placement.room),
                ):
                    key = (kind, resource, placement.start.day,
                           placement.start.period + i)
                    if key in used:
                        ok = False
                    used[key] = lesson.lesson_id
            if not ok:
                break
        if not ok:
            continue
        moves = sum(
            1 for lid, base in problem.baseline.items()
            if combo_by_id[lid] != base
        )
        best = moves if best is None else min(best, moves)
    return best


class Scenario1Tests(unittest.TestCase):
    """手工可核对：存在 3 移动修复，最优 2 移动，且最优解搬动不直接冲突的旧课。"""

    def setUp(self) -> None:
        # 单教室、单班、单教师；每天 8 节，只用第 0 天。
        # 基线：A=p0, B=p1, C=p2。
        #   A 只能待在 p0；B 候选 p1,p2；C 候选 p2,p3。
        # 新课 N 候选 p0 或 p1。
        # - 不动旧课：p0/p1 均被占 => 不可行；
        # - 移动 1：N->p0 迫使 A 走但 A 无处可去；N->p1 迫使 B 走，
        #   B 只能去 p2，而 C 在 p2 且 C 不能不动 => 不可行；
        # - 移动 2：N->p1, B->p2, C->p3 => 恰好 2 移动。
        #   C 原本并不与 N 直接冲突（N 在 p1，C 在 p2）。
        # - 另一条直观修法 N->p0 无法成立（A 锁死在 p0）。
        rooms = frozenset([R1])
        self.A = Lesson("A", "t", "c", 1, S(0, 0), rooms)
        self.B = Lesson("B", "t", "c", 1, S(0, 1, 2), rooms)
        self.C = Lesson("C", "t", "c", 1, S(0, 2, 3), rooms)
        self.N = Lesson("N", "t", "c", 1, S(0, 0, 1), rooms)
        self.baseline = {
            "A": Placement(Start(0, 0), R1),
            "B": Placement(Start(0, 1), R1),
            "C": Placement(Start(0, 2), R1),
        }

    def test_optimal_is_two_and_moves_indirect_lesson(self) -> None:
        problem = Problem([self.A, self.B, self.C, self.N], self.baseline)

        # 暴力独立核对最优值为 2。
        self.assertEqual(brute_force_min_moves(problem), 2)

        result = repair(problem)
        self.assertTrue(result.feasible)
        self.assertTrue(result.optimal)
        self.assertEqual(len(result.moved), 2, result.moved)
        self.assertIn("C", result.moved,
                      "最优解必须搬动与新课不直接冲突的 C")
        self.assertNotIn("A", result.moved)

        checked = check(problem, result.assignments)
        self.assertTrue(checked.valid, checked.errors)
        self.assertEqual(checked.moved, result.moved)

        # 期望的 2 移动修复形态。
        self.assertEqual(result.assignments["N"], Placement(Start(0, 1), R1))
        self.assertEqual(result.assignments["B"], Placement(Start(0, 2), R1))
        self.assertEqual(result.assignments["C"], Placement(Start(0, 3), R1))

    def test_check_detects_double_period_second_slot_conflict(self) -> None:
        # 连堂 D 占 p2,p3；另排一节 E 在 p3，冲突发生在连堂的第二节。
        rooms = frozenset([R1])
        D = Lesson("D", "t", "c", 2, S(0, 2), rooms)
        E = Lesson("E", "t", "c", 1, S(0, 3), rooms)
        problem = Problem(
            [D, E],
            {"D": Placement(Start(0, 2), R1)},
        )
        assignment = {
            "D": Placement(Start(0, 2), R1),
            "E": Placement(Start(0, 3), R1),
        }
        result = check(problem, assignment)
        self.assertFalse(result.valid)
        self.assertTrue(
            any("第4节" in e and e.startswith("RESOURCE_CONFLICT")
                for e in result.errors),
            result.errors,
        )
        # 合法对照：E 改到 p4。
        E_ok = Lesson("E", "t", "c", 1, S(0, 3, 4), rooms)
        ok = check(
            Problem([D, E_ok], {"D": Placement(Start(0, 2), R1)}),
            {"D": Placement(Start(0, 2), R1),
             "E_ok" if False else "E": Placement(Start(0, 4), R1)},
        )
        self.assertTrue(ok.valid, ok.errors)


class Scenario2Tests(unittest.TestCase):
    """必须借助换教室才能完成的修复；锁定关键旧课则无解。"""

    def build_problem(self, locked: bool) -> Problem:
        # 第 0 天 p0：A 基线在 R1，新课 N 也必须用 R1 的 p0；
        # 二者教师、班级互不相同，唯一资源争用是教室，
        # 因此唯一可行修复是 A 保持时间不变、平移到同时间的 R2。
        rooms = frozenset([R1, R2])
        A = Lesson("A", "tA", "cA", 1, S(0, 0), rooms)
        N = Lesson("N", "tN", "cN", 1, S(0, 0), frozenset([R1]))
        baseline = {"A": Placement(Start(0, 0), R1)}
        lock = frozenset(["A"]) if locked else frozenset()
        return Problem([A, N], baseline, lock)

    def test_room_swap_solves_and_counts_as_one_move(self) -> None:
        problem = self.build_problem(locked=False)
        self.assertEqual(brute_force_min_moves(problem), 1)
        result = repair(problem)
        self.assertTrue(result.feasible, result.reason)
        self.assertEqual(result.moved, frozenset(["A"]))
        # 时间未变，仅换教室，仍然计为 1 次移动。
        self.assertEqual(result.assignments["A"], Placement(Start(0, 0), R2))
        self.assertEqual(result.assignments["N"], Placement(Start(0, 0), R1))
        checked = check(problem, result.assignments)
        self.assertTrue(checked.valid, checked.errors)
        self.assertEqual(checked.moved, frozenset(["A"]))

    def test_locked_makes_infeasible(self) -> None:
        locked_problem = self.build_problem(locked=True)
        self.assertIsNone(brute_force_min_moves(locked_problem))
        result = repair(locked_problem)
        self.assertFalse(result.feasible)
        self.assertEqual(result.assignments, {})

        # 解除锁定后恢复可解。
        unlocked = self.build_problem(locked=False)
        self.assertTrue(repair(unlocked).feasible)

        # check 必须拒绝"硬塞"的安排（A 仍在 R1，N 也在 R1）。
        forced = {
            "A": Placement(Start(0, 0), R1),
            "N": Placement(Start(0, 0), R1),
        }
        checked = check(unlocked, forced)
        self.assertFalse(checked.valid)
        self.assertTrue(
            any(e.startswith("RESOURCE_CONFLICT") for e in checked.errors),
            checked.errors,
        )

        # check 必须拒绝锁定课被移动。
        moved_locked = {
            "A": Placement(Start(0, 0), R2),
            "N": Placement(Start(0, 0), R1),
        }
        checked_lock = check(locked_problem, moved_locked)
        self.assertFalse(checked_lock.valid)
        self.assertTrue(
            any(e.startswith("LOCKED_MOVED:A") for e in checked_lock.errors),
            checked_lock.errors,
        )


class Scenario3Tests(unittest.TestCase):
    """200 节旧课：20 节被新课触发的强制搬迁链 + 180 节完全无资源交互的旧课。"""

    CHAIN_LEN = 20
    ISOLATED = 180

    def build_problem(self) -> Problem:
        lessons: list[Lesson] = []
        baseline: dict[str, Placement] = {}

        # 搬迁链：单教师/单班/单教室，占 21 个线性单元（跨第 0..2 天）。
        # 单元 k 映射到 (k // 8, k % 8)；L_i 候选仅为单元 i、i+1，
        # 基线在单元 i；新课 N 只能在单元 0。所有课长度均为 1，
        # 跨天边界处只是换一天，不涉及连堂。
        def cell(k: int) -> Start:
            return Start(k // 8, k % 8)

        chain_room = frozenset(["CR"])
        for i in range(self.CHAIN_LEN):
            lesson = Lesson(
                f"L{i:02d}", "ct", "cc", 1,
                frozenset([cell(i), cell(i + 1)]), chain_room,
            )
            lessons.append(lesson)
            baseline[lesson.lesson_id] = Placement(cell(i), "CR")
        new_lesson = Lesson("N0", "ct", "cc", 1, frozenset([cell(0)]),
                            chain_room)
        lessons.append(new_lesson)

        # 180 节独立旧课：教师、班级、教室全部独占；
        # 只允许出现在第 4 天，与链（第 0 天）时间域不相交，
        # 因而与链及彼此都没有资源交互，每个都有 >=2 个候选位置。
        for j in range(self.ISOLATED):
            room = f"R{j:03d}"
            lesson = Lesson(
                f"I{j:03d}", f"t{j:03d}", f"c{j:03d}", 1,
                S(4, 0, 1), frozenset([room]),
            )
            lessons.append(lesson)
            baseline[lesson.lesson_id] = Placement(Start(4, 0), room)

        return Problem(lessons, baseline, frozenset())

    def test_force_chain_optimal_twenty_within_ten_seconds(self) -> None:
        problem = self.build_problem()
        self.assertEqual(len(problem.lessons), 201)

        started = time.perf_counter()
        result = repair(problem)
        elapsed = time.perf_counter() - started
        print(f"\n[scenario3] solved in {elapsed:.3f}s")

        self.assertTrue(result.feasible, result.reason)
        self.assertTrue(result.optimal)
        self.assertEqual(len(result.moved), 20, result.moved)
        self.assertEqual(result.moved, {f"L{i:02d}" for i in range(20)})

        # 全部 200 节旧课与新课都仍在结果中。
        old_ids = {lesson.lesson_id for lesson in problem.lessons
                   if lesson.lesson_id in problem.baseline}
        self.assertEqual(len(old_ids), 200)
        self.assertEqual(set(result.assignments), old_ids | {"N0"})

        checked = check(problem, result.assignments)
        self.assertTrue(checked.valid, checked.errors)
        self.assertEqual(checked.moved, result.moved)

        # 链被整体推动：N0 在 p0，L_i 移到 p_{i+1}。
        assignments = result.assignments
        def cell(k: int) -> Start:
            return Start(k // 8, k % 8)

        self.assertEqual(assignments["N0"], Placement(cell(0), "CR"))
        for i in range(self.CHAIN_LEN):
            self.assertEqual(
                assignments[f"L{i:02d}"], Placement(cell(i + 1), "CR")
            )
        # 独立旧课全部保持基线。
        for j in range(self.ISOLATED):
            self.assertEqual(
                assignments[f"I{j:03d}"], Placement(Start(4, 0), f"R{j:03d}")
            )

        self.assertLessEqual(elapsed, 10.0, f"求解耗时 {elapsed:.2f}s 超过 10s")


class RandomizedCrossCheckTests(unittest.TestCase):
    """固定种子的随机小例：repair 与独立暴力枚举逐项对齐。"""

    def test_random_small_instances(self) -> None:
        import random
        rng = random.Random(20260930)
        rooms_pool = ["RA", "RB", "RC"]
        teachers = [f"tt{i}" for i in range(4)]
        klasses = [f"kk{i}" for i in range(4)]

        for trial in range(25):
            old_n = rng.randint(3, 4)
            new_n = rng.randint(1, 2)
            lessons: list[Lesson] = []
            baseline: dict[str, Placement] = {}
            used_cells: set[tuple] = set()

            def random_lesson(lid: str, base_ok: bool) -> tuple[Lesson, Placement | None]:
                # 多次尝试，保证旧课能取到一个与已有基线不冲突的位置。
                for _ in range(200):
                    length = rng.choice([1, 1, 2])
                    max_start = 8 - length
                    start_pool = [Start(d, p) for d in range(2)
                                  for p in range(max_start)]
                    k = rng.randint(1, min(3, len(start_pool)))
                    starts = frozenset(rng.sample(start_pool, k))
                    room_n = rng.randint(1, 2)
                    rooms = frozenset(rng.sample(rooms_pool, room_n))
                    teacher = rng.choice(teachers)
                    klass = rng.choice(klasses)
                    lesson = Lesson(lid, teacher, klass, length, starts, rooms)
                    if not base_ok:
                        return lesson, None
                    for start in sorted(starts, key=lambda x: (x.day, x.period)):
                        for room in sorted(rooms):
                            keys = {
                                (kind, resource, start.day, start.period + off)
                                for off in range(length)
                                for kind, resource in (
                                    ("T", teacher), ("C", klass), ("R", room)
                                )
                            }
                            if keys.isdisjoint(used_cells):
                                used_cells.update(keys)
                                return lesson, Placement(start, room)
                raise RuntimeError("随机生成器无法放置旧课")

            for i in range(old_n):
                lesson, placement = random_lesson(f"O{i}", base_ok=True)
                lessons.append(lesson)
                baseline[lesson.lesson_id] = placement
            for i in range(new_n):
                lesson, _ = random_lesson(f"N{i}", base_ok=False)
                lessons.append(lesson)

            locked = frozenset(
                lesson.lesson_id for lesson in lessons
                if lesson.lesson_id in baseline and rng.random() < 0.25
            )
            problem = Problem(lessons, baseline, locked)
            expected = brute_force_min_moves(problem)
            result = repair(problem)

            if expected is None:
                self.assertFalse(result.feasible, f"trial {trial}: 应为无解")
                continue
            self.assertTrue(result.feasible,
                            f"trial {trial}: 应有解，{result.reason}")
            self.assertEqual(
                len(result.moved), expected,
                f"trial {trial}: 最优 {expected}，实际 {len(result.moved)}",
            )
            checked = check(problem, result.assignments)
            self.assertTrue(checked.valid,
                            f"trial {trial}: {checked.errors}")
            self.assertEqual(checked.moved, result.moved)
            for lid in locked:
                self.assertEqual(result.assignments[lid], baseline[lid])


class EdgeCaseTests(unittest.TestCase):
    """边界与错误输入。"""

    def test_new_lesson_without_candidate_is_infeasible(self) -> None:
        rooms = frozenset([R1])
        A = Lesson("A", "t", "c", 2, S(0, 7), rooms)  # 连堂起点越界
        problem = Problem([A], {})
        result = repair(problem)
        self.assertFalse(result.feasible)
        self.assertIn("BAD_START", result.reason)
        self.assertEqual(result.assignments, {})

    def test_empty_problem_is_feasible(self) -> None:
        result = repair(Problem([], {}))
        self.assertTrue(result.feasible)
        self.assertEqual(result.assignments, {})
        self.assertEqual(result.moved, frozenset())

    def test_check_rejects_missing_duplicate_and_unknown(self) -> None:
        rooms = frozenset([R1, R2])
        A = Lesson("A", "t", "c", 1, S(0, 0), rooms)
        B = Lesson("B", "t", "c", 1, S(0, 0), rooms)
        problem = Problem([A, B], {"A": Placement(Start(0, 0), R1)})

        missing = check(problem, {"A": Placement(Start(0, 0), R1)})
        self.assertFalse(missing.valid)
        self.assertTrue(any(e.startswith("MISSING_LESSON:B") for e in missing.errors))

        unknown = check(problem, {
            "A": Placement(Start(0, 0), R1),
            "B": Placement(Start(0, 0), R2),
            "X": Placement(Start(0, 0), R2),
        })
        self.assertFalse(unknown.valid)
        self.assertTrue(any(e.startswith("UNKNOWN_LESSON:X") for e in unknown.errors))

        candidate = check(problem, {
            "A": Placement(Start(0, 1), R1),  # 起点不在允许集合
            "B": Placement(Start(0, 0), R2),
        })
        self.assertFalse(candidate.valid)
        self.assertTrue(any(e.startswith("CANDIDATE_START:A")
                            for e in candidate.errors))

    def test_locked_baseline_mismatch_detected(self) -> None:
        rooms = frozenset([R1])
        A = Lesson("A", "t", "c", 1, S(0, 0), rooms)
        problem = Problem([A], {"A": Placement(Start(0, 0), R1)},
                          frozenset(["A"]))
        # 结构层：锁定集合引用不存在的课节也应报错。
        bad = Problem([A], {"A": Placement(Start(0, 0), R1)},
                      frozenset(["GHOST"]))
        self.assertFalse(repair(bad).feasible)
        # 合法锁定安排。
        ok = repair(problem)
        self.assertTrue(ok.feasible)
        self.assertEqual(ok.assignments["A"], Placement(Start(0, 0), R1))

    def test_double_period_must_stay_in_day(self) -> None:
        rooms = frozenset([R1])
        # 允许集合中混入越界起点时，整体问题不合法。
        A = Lesson("A", "t", "c", 2, S(0, 6), rooms)  # 6+2=8 合法
        self.assertTrue(repair(Problem([A], {})).feasible)
        B = Lesson("B", "t", "c", 2, S(0, 7), rooms)  # 7+2>8 非法
        self.assertFalse(repair(Problem([B], {})).feasible)


if __name__ == "__main__":
    unittest.main()
