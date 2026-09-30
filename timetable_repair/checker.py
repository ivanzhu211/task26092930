"""check 实现：独立复核安排合法性并重算移动集合。

check 不信任 repair 返回的任何标志，全部信息依据 problem 与
assignment 重新推导。除安排本身外，也会校验 problem 的结构合法性。
"""

from __future__ import annotations

from typing import Any, Mapping

from .model import (
    DAYS,
    PERIODS,
    CheckReport,
    Lesson,
    Placement,
    Problem,
    RepairResult,
    Start,
)


def validate_problem(problem: Any) -> list[str]:
    """校验 Problem 自身结构，返回错误信息列表（空列表表示合法）。"""
    errors: list[str] = []
    if not isinstance(problem, Problem):
        return ["problem 不是 Problem 实例"]

    seen_ids: set[str] = set()
    for index, lesson in enumerate(problem.lessons):
        prefix = f"lessons[{index}]"
        if not isinstance(lesson, Lesson):
            errors.append(f"{prefix} 不是 Lesson 实例")
            continue
        if not lesson.lesson_id:
            errors.append(f"{prefix} 缺少 lesson_id")
        elif lesson.lesson_id in seen_ids:
            errors.append(f"{prefix} lesson_id 重复: {lesson.lesson_id}")
        else:
            seen_ids.add(lesson.lesson_id)
        if not lesson.teacher:
            errors.append(f"{prefix}({lesson.lesson_id}) 缺少 teacher")
        if not lesson.klass:
            errors.append(f"{prefix}({lesson.lesson_id}) 缺少 klass")
        if lesson.duration not in (1, 2):
            errors.append(
                f"{prefix}({lesson.lesson_id}) duration 必须为 1 或 2，"
                f"实际为 {lesson.duration}"
            )
        if not lesson.allowed_starts:
            errors.append(f"{prefix}({lesson.lesson_id}) allowed_starts 为空")
        for start in lesson.allowed_starts:
            if not isinstance(start, Start):
                errors.append(f"{prefix}({lesson.lesson_id}) 起点不是 Start 实例")
                continue
            if not (0 <= start.day < DAYS):
                errors.append(
                    f"{prefix}({lesson.lesson_id}) 非法周几: {start.day}"
                )
            if not (0 <= start.period < PERIODS):
                errors.append(
                    f"{prefix}({lesson.lesson_id}) 非法节次: {start.period}"
                )
            if (
                0 <= start.period < PERIODS
                and start.period + lesson.duration > PERIODS
            ):
                errors.append(
                    f"{prefix}({lesson.lesson_id}) 起点 {start.day} 节 "
                    f"{start.period} 会跨出当天边界"
                )
        if not lesson.allowed_rooms:
            errors.append(f"{prefix}({lesson.lesson_id}) allowed_rooms 为空")
        for room in lesson.allowed_rooms:
            if not room:
                errors.append(f"{prefix}({lesson.lesson_id}) 存在空教室名")

    lesson_by_id = {
        lesson.lesson_id: lesson
        for lesson in problem.lessons
        if isinstance(lesson, Lesson) and lesson.lesson_id
    }

    for lesson_id, placement in problem.baseline.items():
        lesson = lesson_by_id.get(lesson_id)
        if lesson is None:
            errors.append(f"baseline 引用了不存在的课节: {lesson_id}")
            continue
        error = _placement_error(lesson, placement)
        if error is not None:
            errors.append(f"baseline[{lesson_id}]: {error}")

    for lesson_id in problem.locked_ids:
        if lesson_id not in problem.baseline:
            errors.append(f"locked_ids 包含无基线安排的课节: {lesson_id}")
        if lesson_id not in lesson_by_id:
            errors.append(f"locked_ids 引用了不存在的课节: {lesson_id}")

    return errors


def _placement_error(lesson: Lesson, placement: Any) -> str | None:
    """返回单个安排相对课节候选范围的错误信息；合法时返回 None。"""
    if not isinstance(placement, Placement):
        return "安排不是 Placement 实例"
    start = placement.start
    if not isinstance(start, Start):
        return "起点不是 Start 实例"
    if not (0 <= start.day < DAYS and 0 <= start.period < PERIODS):
        return f"起点越界: day={start.day} period={start.period}"
    if start.period + lesson.duration > PERIODS:
        return (
            f"起点 {start.day} 节 {start.period} 加上 duration="
            f"{lesson.duration} 跨出当天"
        )
    if start not in lesson.allowed_starts:
        return f"起点 ({start.day}, {start.period}) 不在 allowed_starts 中"
    if placement.room not in lesson.allowed_rooms:
        return f"教室 {placement.room} 不在 allowed_rooms 中"
    return None


def _as_assignment(target: Any) -> Any:
    """允许直接传 RepairResult 或映射。"""
    if isinstance(target, RepairResult):
        return target.assignment
    return target


def check(problem: Problem, assignment: Any) -> CheckReport:
    """复核安排：完整性、候选范围、锁定约束、资源冲突，并重算移动集合。"""
    errors = validate_problem(problem)
    mapping = _as_assignment(assignment)
    if not isinstance(mapping, Mapping):
        errors.append("assignment 不是 ID -> Placement 的映射")
        return CheckReport(False, frozenset(), tuple(errors))

    lesson_by_id = {
        lesson.lesson_id: lesson
        for lesson in problem.lessons
        if isinstance(lesson, Lesson) and lesson.lesson_id
    }

    placed: dict[str, Placement] = {}
    for lesson_id, placement in mapping.items():
        if lesson_id not in lesson_by_id:
            errors.append(f"安排包含未知课节 ID: {lesson_id}")
            continue
        if not isinstance(placement, Placement):
            errors.append(f"安排[{lesson_id}] 不是 Placement 实例")
            continue
        placed[lesson_id] = placement

    for lesson_id, lesson in lesson_by_id.items():
        if lesson_id not in placed:
            errors.append(f"课节缺失: {lesson_id}")

    for lesson_id, placement in placed.items():
        lesson = lesson_by_id[lesson_id]
        error = _placement_error(lesson, placement)
        if error is not None:
            errors.append(f"安排[{lesson_id}]: {error}")

    for lesson_id in problem.locked_ids:
        baseline = problem.baseline.get(lesson_id)
        current = placed.get(lesson_id)
        if baseline is not None and current is not None and current != baseline:
            errors.append(
                f"锁定课节 {lesson_id} 偏离基线: "
                f"{_describe(current)} != {_describe(baseline)}"
            )

    errors.extend(_resource_conflicts(lesson_by_id, placed))

    moved = {
        lesson_id
        for lesson_id, placement in placed.items()
        if lesson_id in problem.baseline
        and problem.baseline[lesson_id] != placement
    }
    return CheckReport(len(errors) == 0, frozenset(moved), tuple(errors))


def _describe(placement: Placement) -> str:
    return (
        f"(day={placement.start.day}, period={placement.start.period}, "
        f"room={placement.room})"
    )


def _resource_conflicts(
    lesson_by_id: dict[str, Lesson], placed: dict[str, Placement]
) -> list[str]:
    """检测教师、班级、教室三类资源的同时段占用冲突。"""
    errors: list[str] = []
    owners: dict[tuple[str, str, int, int], str] = {}
    for lesson_id, lesson in lesson_by_id.items():
        placement = placed.get(lesson_id)
        if placement is None:
            continue
        start = placement.start
        if not (0 <= start.day < DAYS and 0 <= start.period < PERIODS):
            continue
        for offset in range(lesson.duration):
            period = start.period + offset
            if period >= PERIODS:
                break
            for kind, value in (
                ("teacher", lesson.teacher),
                ("class", lesson.klass),
                ("room", placement.room),
            ):
                key = (kind, value, start.day, period)
                other = owners.get(key)
                if other is not None:
                    errors.append(
                        f"{kind} 资源冲突: {value} 在第 {start.day + 1} 天 "
                        f"第 {period + 1} 节被 {other} 与 {lesson_id} 同时占用"
                    )
                else:
                    owners[key] = lesson_id
    return errors
