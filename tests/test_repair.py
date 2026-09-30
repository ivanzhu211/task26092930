"""课表最小扰动修复库的自动化测试。

运行：python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import time
import unittest

from timetable_repair import (
    Lesson,
    Placement,
    Problem,
    Start,
    check,
    repair,
)

ROOM = "r1"


def lesson(
    lesson_id: str,
    periods: list[int],
    day: int = 0,
    duration: int = 1,
    room: str = ROOM,
) -> Lesson:
    return Lesson(
        lesson_id=lesson_id,
        teacher=f"t_{lesson_id}",
        klass=f"c_{lesson_id}",
        duration=duration,
        allowed_starts=tuple(Start(day, period) for period in periods),
        allowed_rooms=(room,),
    )


def place(period: int, day: int = 0, room: str = ROOM) -> Placement:
    return Placement(Start(day, period), room)


class SmallOptimumTest(unittest.TestCase):
    """场景一：手工可核对最优值，间接冲突迫使无冲突旧课搬迁。"""

    def test_optimum_two_with_indirect_move(self) -> None:
        # 时间轴（同教室 r1，教师/班级各不相同，仅教室资源冲突）。
        # 节次 0..4，基线 A=0, B=1, C=2, D=3，节次 4 空闲。
        # 新课 N 只能放 0，故 A 必动。候选范围：
        #   A: {0,1,3}, B: {1,2}, C: {2,3}, D: {3,4}
        #
        # 3 节移动的可行解：N=0, A=2, B=1（不动）, C=3, D=4。
        # 2 节移动的全局最优解：
        #   N=0, A=3, B=1, C=2（不动）, D=4 —— A 越过 B、C 跳进
        #   D 的位置，把 D 挤到 4；D 原本不与 N 直接冲突，却被迫搬迁。
        # 1 节移动不可能：A 离开 0 后只能落到 1 或 3，必再挤走 B 或 D。
        old = {
            "A": lesson("A", [0, 1, 2, 3]),
            "B": lesson("B", [1, 2]),
            "C": lesson("C", [2, 3]),
            "D": lesson("D", [3, 4]),
        }
        new_lesson = lesson("N", [0])
        baseline = {
            "A": place(0),
            "B": place(1),
            "C": place(2),
            "D": place(3),
        }
        problem = Problem(
            tuple(old.values()) + (new_lesson,), baseline, frozenset()
        )

        result = repair(problem)

        self.assertTrue(result.feasible, result.reason)
        self.assertEqual(len(result.moved), 2, sorted(result.moved))
        report = check(problem, result)
        self.assertTrue(report.feasible, report.errors)
        self.assertEqual(report.moved, result.moved)
        self.assertEqual(set(result.assignment), {"A", "B", "C", "D", "N"})
        # 最优解必须搬走原本不与新课直接冲突的 D
        self.assertIn("D", result.moved)

        three_move = {
            "A": place(2),
            "B": place(1),
            "C": place(3),
            "D": place(4),
            "N": place(0),
        }
        three_report = check(problem, three_move)
        self.assertTrue(three_report.feasible, three_report.errors)
        self.assertEqual(three_report.moved, frozenset({"A", "C", "D"}))

        two_move = {
            "A": place(3),
            "B": place(1),
            "C": place(2),
            "D": place(4),
            "N": place(0),
        }
        two_report = check(problem, two_move)
        self.assertTrue(two_report.feasible, two_report.errors)
        self.assertEqual(two_report.moved, frozenset({"A", "D"}))

    def test_check_detects_double_period_second_slot_conflict(self) -> None:
        # X 是连堂课，占 0、1 两节；Y 只占第 1 节。
        # 第 0 节无冲突，冲突恰好发生在连堂课的第二节。
        x = Lesson(
            "X",
            teacher="t_X",
            klass="c_X",
            duration=2,
            allowed_starts=(Start(0, 0),),
            allowed_rooms=("r2",),
        )
        y = Lesson(
            "Y",
            teacher="t_Y",
            klass="c_Y",
            duration=1,
            allowed_starts=(Start(0, 1),),
            allowed_rooms=("r2",),
        )
        problem = Problem(
            (x, y),
            {"X": Placement(Start(0, 0), "r2")},
            frozenset(),
        )
        bad = {
            "X": Placement(Start(0, 0), "r2"),
            "Y": Placement(Start(0, 1), "r2"),
        }
        report = check(problem, bad)
        self.assertFalse(report.feasible)
        self.assertTrue(
            any("第 2 节" in error for error in report.errors),
            report.errors,
        )


class RoomSwapTest(unittest.TestCase):
    """场景二：必须换教室；锁定后无解，解锁后可解；仅换教室计 1 次。"""

    def _problem(self, locked: bool) -> Problem:
        old = Lesson(
            "A",
            teacher="t_A",
            klass="c_A",
            duration=1,
            allowed_starts=(Start(0, 0),),
            allowed_rooms=("r1", "r2"),
        )
        new = Lesson(
            "N",
            teacher="t_N",
            klass="c_N",
            duration=1,
            allowed_starts=(Start(0, 0),),
            allowed_rooms=("r1",),
        )
        baseline = {"A": Placement(Start(0, 0), "r1")}
        locked_ids = frozenset({"A"}) if locked else frozenset()
        return Problem((old, new), baseline, locked_ids)

    def test_room_swap_unlocked_is_feasible(self) -> None:
        result = repair(self._problem(locked=False))
        self.assertTrue(result.feasible, result.reason)
        self.assertEqual(result.moved, frozenset({"A"}))
        # A 时间不变，仅换教室
        self.assertEqual(result.assignment["A"], Placement(Start(0, 0), "r2"))
        self.assertEqual(result.assignment["N"], Placement(Start(0, 0), "r1"))
        report = check(self._problem(False), result)
        self.assertTrue(report.feasible, report.errors)
        self.assertEqual(report.moved, frozenset({"A"}))

    def test_room_swap_locked_is_infeasible(self) -> None:
        result = repair(self._problem(locked=True))
        self.assertFalse(result.feasible)
        self.assertEqual(result.assignment, {})
        self.assertEqual(result.moved, frozenset())

    def test_unlocking_restores_feasibility(self) -> None:
        locked_result = repair(self._problem(locked=True))
        unlocked_result = repair(self._problem(locked=False))
        self.assertFalse(locked_result.feasible)
        self.assertTrue(unlocked_result.feasible)


class ForcedChainScaleTest(unittest.TestCase):
    """场景三：200 节旧课，20 节强制搬迁链 + 180 节完全独立课。"""

    @staticmethod
    def _build_problem() -> Problem:
        lessons = []
        baseline = {}

        # 20 节链上旧课：共享教室 rchain。槽位按"天*8+节次"线性编号，
        # CH_i 的两个相邻候选是槽 i 与槽 i+1，基线占槽 i
        # （i=0..19，占用槽 0..19；槽 20 留空）。新课 N 只能占槽 0，
        # 唯一出路是整条链顺移一格，20 节旧课全部移动 1 次。
        for i in range(20):
            day_i, period_i = divmod(i, 8)
            day_j, period_j = divmod(i + 1, 8)
            lessons.append(
                Lesson(
                    f"CH{i}",
                    teacher=f"t_ch{i}",
                    klass=f"c_ch{i}",
                    duration=1,
                    allowed_starts=(
                        Start(day_i, period_i),
                        Start(day_j, period_j),
                    ),
                    allowed_rooms=("rchain",),
                )
            )
            baseline[f"CH{i}"] = Placement(
                Start(day_i, period_i), "rchain"
            )

        # 180 节独立旧课：每天 60 节、各自独占教室（每节都有
        # allowed_rooms 两间但只允许自己用的命名空间），教师与班级
        # 也全部唯一，故与链及彼此均无资源交互。每节两个候选起点。
        for i in range(180):
            room = f"room_{i}"
            day = 2 + (i // 60)
            period = i % 8
            lessons.append(
                Lesson(
                    f"IS{i}",
                    teacher=f"t_is{i}",
                    klass=f"c_is{i}",
                    duration=1,
                    allowed_starts=(
                        Start(day, period),
                        Start(day, (period + 1) % 8),
                    ),
                    allowed_rooms=(room,),
                )
            )
            baseline[f"IS{i}"] = Placement(Start(day, period), room)

        new_lesson = Lesson(
            "NEW",
            teacher="t_new",
            klass="c_new",
            duration=1,
            allowed_starts=(Start(0, 0),),
            allowed_rooms=("rchain",),
        )
        # 独立课虽与链课在时间轴上有重叠，但教室、教师、班级命名空间
        # 全部互不相交，因此零资源交互。
        lessons.append(new_lesson)
        return Problem(tuple(lessons), baseline, frozenset())

    def test_optimum_twenty_moves_within_budget(self) -> None:
        problem = self._build_problem()
        started = time.perf_counter()
        result = repair(problem)
        elapsed = time.perf_counter() - started
        print(f"\n200 节旧课规模求解耗时: {elapsed:.4f}s")

        self.assertTrue(result.feasible, result.reason)
        self.assertEqual(len(result.moved), 20, sorted(result.moved))
        self.assertEqual(
            result.moved, frozenset(f"CH{i}" for i in range(20))
        )
        # 全部 200 节旧课仍在结果中，且新课也恰好安排一次
        self.assertEqual(len(result.assignment), 201)
        for i in range(20):
            day_j, period_j = divmod(i + 1, 8)
            self.assertEqual(
                result.assignment[f"CH{i}"],
                Placement(Start(day_j, period_j), "rchain"),
            )
        for i in range(180):
            day = 2 + (i // 60)
            period = i % 8
            self.assertEqual(
                result.assignment[f"IS{i}"],
                Placement(Start(day, period), f"room_{i}"),
            )
        report = check(problem, result)
        self.assertTrue(report.feasible, report.errors)
        self.assertEqual(len(report.moved), 20)
        self.assertLess(elapsed, 10.0, "规模测试超过 10 秒预算")


class LockedAndCompletenessTest(unittest.TestCase):
    """锁定约束、无解不返回部分课表等补充检查。"""

    def test_locked_must_keep_baseline(self) -> None:
        old = Lesson(
            "A",
            "t_A",
            "c_A",
            1,
            (Start(0, 0), Start(0, 1)),
            ("r1",),
        )
        new = lesson("N", [0])
        baseline = {"A": place(0)}
        problem = Problem((old, new), baseline, frozenset({"A"}))
        result = repair(problem)
        self.assertFalse(result.feasible)
        self.assertEqual(result.assignment, {})

    def test_check_recomputes_moved_without_trust(self) -> None:
        old = lesson("A", [0, 1])
        problem = Problem((old,), {"A": place(0)}, frozenset())
        from timetable_repair import RepairResult

        forged = RepairResult(
            feasible=True,
            assignment={"A": place(1)},
            moved=frozenset(),
        )
        report = check(problem, forged)
        self.assertTrue(report.feasible)
        self.assertEqual(report.moved, frozenset({"A"}))

    def test_check_detects_missing_lesson(self) -> None:
        old = lesson("A", [0])
        problem = Problem((old,), {"A": place(0)}, frozenset())
        report = check(problem, {})
        self.assertFalse(report.feasible)
        self.assertTrue(any("缺失" in e for e in report.errors))


if __name__ == "__main__":
    unittest.main()
