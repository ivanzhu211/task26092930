"""问题结构与安排的合法性校验（供 check 复用）。"""

from __future__ import annotations

from .model import (
    DAYS,
    PERIODS,
    Assignment,
    CheckResult,
    Lesson,
    Placement,
    Problem,
    occupancy,
    valid_start,
)


def _validate_lesson(lesson: Lesson) -> list[str]:
    errors: list[str] = []
    if not isinstance(lesson.lesson_id, str) or not lesson.lesson_id:
        errors.append("BAD_LESSON_ID: 课节 ID 必须是非空字符串")
    if not isinstance(lesson.teacher, str) or not lesson.teacher:
        errors.append(f"BAD_TEACHER:{lesson.lesson_id}: 教师必须是非空字符串")
    if not isinstance(lesson.klass, str) or not lesson.klass:
        errors.append(f"BAD_CLASS:{lesson.lesson_id}: 班级必须是非空字符串")
    if lesson.length not in (1, 2):
        errors.append(f"BAD_LENGTH:{lesson.lesson_id}: 长度必须为 1 或 2")
        return errors
    if not lesson.starts:
        errors.append(f"EMPTY_STARTS:{lesson.lesson_id}: 允许起点集合为空")
    for start in lesson.starts:
        if not valid_start(start, lesson.length):
            errors.append(
                f"BAD_START:{lesson.lesson_id}: 起点 ({start.day},{start.period}) "
                f"对长度 {lesson.length} 不合法"
            )
    if not lesson.rooms:
        errors.append(f"EMPTY_ROOMS:{lesson.lesson_id}: 允许教室集合为空")
    for room in lesson.rooms:
        if not isinstance(room, str) or not room:
            errors.append(f"BAD_ROOM:{lesson.lesson_id}: 教室名必须是非空字符串")
    return errors


def validate_problem(problem: Problem) -> list[str]:
    """检查 Problem 的结构合法性，返回错误信息列表（空列表表示通过）。"""
    errors: list[str] = []
    by_id: dict[str, Lesson] = {}
    for lesson in problem.lessons:
        errors.extend(_validate_lesson(lesson))
        if lesson.lesson_id in by_id:
            errors.append(f"DUPLICATE_LESSON_ID:{lesson.lesson_id}: 课节 ID 重复")
        by_id[lesson.lesson_id] = lesson

    for lesson_id, placement in problem.baseline.items():
        lesson = by_id.get(lesson_id)
        if lesson is None:
            errors.append(
                f"BASELINE_UNKNOWN_LESSON:{lesson_id}: 基线包含不存在的课节"
            )
            continue
        if placement.start not in lesson.starts:
            errors.append(
                f"BASELINE_BAD_START:{lesson_id}: 基线起点不在允许起点集合内"
            )
        if placement.room not in lesson.rooms:
            errors.append(
                f"BASELINE_BAD_ROOM:{lesson_id}: 基线教室不在允许教室集合内"
            )

    for lesson_id in problem.locked:
        if lesson_id not in by_id:
            errors.append(f"LOCKED_UNKNOWN_LESSON:{lesson_id}: 锁定课节不存在")
        elif lesson_id not in problem.baseline:
            errors.append(f"LOCKED_NOT_BASELINE:{lesson_id}: 锁定课节不在基线中")

    return errors


def _check_resources(
    problem: Problem, assignments: Assignment
) -> list[str]:
    errors: list[str] = []
    by_id = {lesson.lesson_id: lesson for lesson in problem.lessons}
    holders: dict[tuple, tuple[str, str]] = {}

    def claim(kind: str, resource: str, day: int, period: int, lesson_id: str) -> None:
        key = (kind, resource, day, period)
        if key in holders:
            prev_resource_kind, prev_id = holders[key]
            label = {"T": "教师", "C": "班级", "R": "教室"}[kind]
            errors.append(
                f"RESOURCE_CONFLICT:{label} {resource} 在 第{day + 1}天第{period + 1}节 "
                f"被 {prev_id} 与 {lesson_id} 同时占用"
            )
        else:
            holders[key] = (kind, lesson_id)

    for lesson_id, placement in assignments.items():
        lesson = by_id[lesson_id]
        for day, period in occupancy(placement.start, lesson.length):
            claim("T", lesson.teacher, day, period, lesson_id)
            claim("C", lesson.klass, day, period, lesson_id)
            claim("R", placement.room, day, period, lesson_id)
    return errors


def check_assignment(problem: Problem, assignments: Assignment) -> CheckResult:
    """完整检查安排：完整性、候选范围、锁定约束、资源冲突，并重算移动集合。"""
    errors = validate_problem(problem)

    by_id = {lesson.lesson_id: lesson for lesson in problem.lessons}
    seen: set[str] = set()
    for lesson_id, placement in assignments.items():
        if lesson_id not in by_id:
            errors.append(
                f"UNKNOWN_LESSON:{lesson_id}: 安排中出现问题里不存在的课节"
            )
            continue
        if lesson_id in seen:
            errors.append(f"DUPLICATE_ASSIGNMENT:{lesson_id}: 课节被安排多次")
        seen.add(lesson_id)
        lesson = by_id[lesson_id]
        if not isinstance(placement, Placement):
            errors.append(f"BAD_PLACEMENT:{lesson_id}: 安排值不是 Placement")
            continue
        if placement.start not in lesson.starts:
            errors.append(
                f"CANDIDATE_START:{lesson_id}: 起点 "
                f"({placement.start.day},{placement.start.period}) 不在允许起点集合内"
            )
        if placement.room not in lesson.rooms:
            errors.append(
                f"CANDIDATE_ROOM:{lesson_id}: 教室 {placement.room} 不在允许教室集合内"
            )
        if lesson_id in problem.locked and problem.baseline.get(lesson_id) != placement:
            errors.append(f"LOCKED_MOVED:{lesson_id}: 锁定课节偏离基线安排")

    for lesson in problem.lessons:
        if lesson.lesson_id not in seen:
            errors.append(f"MISSING_LESSON:{lesson.lesson_id}: 课节未被安排")

    if not any(e.startswith(("MISSING_LESSON", "UNKNOWN_LESSON", "BAD_PLACEMENT"))
               for e in errors):
        errors.extend(_check_resources(problem, assignments))

    moved = frozenset(
        lesson_id
        for lesson_id, placement in problem.baseline.items()
        if lesson_id in seen and assignments.get(lesson_id) != placement
    )

    return CheckResult(valid=not errors, moved=moved, errors=errors)
