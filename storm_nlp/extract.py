"""单语通告要素抽取。

对每条通告先分句，再从条款中抽取值班员需要核对的五维信息：
地点、时间、对象、条件、行动要求，同时判定效力等级与否定。
抽取结果始终携带原文片段和条款编号，作为后续指引的溯源依据。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from . import lexicon
from .languages import split_clauses
from .models import (
    ActionType,
    Correction,
    Extraction,
    ForceLevel,
    Language,
    Notice,
    SourceKind,
)
from .places import PlaceRegistry
from .timeparse import parse_condition, parse_window

_SOURCE_DEFAULT_FORCE = {
    SourceKind.OFFICIAL: ForceLevel.ORDER,
    SourceKind.ADDENDUM: ForceLevel.ORDER,
    SourceKind.RELAY: ForceLevel.RELAY,
    SourceKind.MACHINE_TRANSLATION: ForceLevel.ORDER,
}

# 更正解析：「（原名 X）现名 Y」「X 更正为 Y」「X 应为 Y」
_RENAME_PATTERNS = [
    re.compile(r"原名[「\"']?([一-鿿A-Za-z0-9 ·]+?)[」\"']?[，,）)]\s*现名[「\"']?([一-鿿A-Za-z0-9 ·]+?)[」\"']?[。；,，]"),
    re.compile(r"[「\"']?([一-鿿A-Za-z0-9 ·]{2,20})[」\"']?\s*(?:更正|订正|改为|应为)\s*[「\"']?([一-鿿A-Za-z0-9 ·]{2,20})[」\"']?"),
    re.compile(r"[\"']([A-Za-z0-9 '\-]{3,30})[\"']\s+(?:is renamed|should read)\s+[\"']([A-Za-z0-9 '\-]{3,30})[\"']", re.IGNORECASE),
]
_TIME_CHANGE_ZH = re.compile(r"([^，。；,]{2,18}?时间|末班船)[^，。；,]*?应为\s*(\d{1,2}:\d{2})\s*[（(]原\s*(\d{1,2}:\d{2})[)）]")
_TIME_CHANGE_EN = re.compile(r"last boat.*?(\d{1,2}:\d{2}).*?instead of\s*(\d{1,2}:\d{2})", re.IGNORECASE)


def _detect_mentions(clause: str, language: Language, registry: PlaceRegistry) -> list[tuple[str, str]]:
    """返回条款中按出现顺序排列的 (mention 文字, place_id)，去重。"""

    found: list[tuple[int, str, str]] = []
    for place in registry.all():
        for name in place.all_names():
            if not name:
                continue
            if language is Language.ZH:
                pos = clause.find(name)
            else:
                m = re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", clause, re.IGNORECASE)
                pos = m.start() if m else -1
            if pos >= 0:
                found.append((pos, name, place.id))
    found.sort(key=lambda item: item[0])
    result: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for _, name, place_id in found:
        if place_id not in seen_ids:
            seen_ids.add(place_id)
            result.append((name, place_id))
    return result


def structural_issues(extraction: Extraction) -> list[str]:
    """结构完整性自检：缺少关键要素时给出问题代码，供发布闸门使用。"""

    issues: list[str] = []
    if extraction.scope_clause:
        return issues
    if extraction.action is ActionType.UNKNOWN:
        issues.append("MISSING_ACTION")
    if extraction.place_id is None and not extraction.generic_place:
        issues.append("MISSING_PLACE")
    if extraction.generic_place:
        # 泛指安排缺少明确适用对象/边界，不能按完整命令下发
        issues.append("GENERIC_SCOPE_UNBOUNDED")
    # 开放/停航/运营时刻必须有时间或条件；封闭/禁行可凭「即刻起」即时生效
    if extraction.action in (ActionType.OPEN, ActionType.SUSPEND, ActionType.SERVICE) and (
        extraction.window is None and extraction.condition is None
    ):
        issues.append("MISSING_TIME_OR_CONDITION")
    return issues


def extract_notice(notice: Notice, registry: PlaceRegistry, ref_now: datetime) -> list[Extraction]:
    clauses = split_clauses(notice.text, notice.language)
    default_force = _SOURCE_DEFAULT_FORCE[notice.kind]
    results: list[Extraction] = []

    for index, clause in enumerate(clauses, start=1):
        scope_clause = lexicon.is_scope_clause(clause, notice.language)
        mentions = [] if scope_clause else _detect_mentions(clause, notice.language, registry)
        generic = lexicon.is_generic(clause, notice.language)
        force = lexicon.find_force(clause, notice.language, default_force)
        # 居民转述来源整体降级为 RELAY，任何措辞都不能升级成命令
        if notice.kind is SourceKind.RELAY:
            force = ForceLevel.RELAY
        negated = lexicon.is_negated(clause, notice.language)
        action = ActionType.UNKNOWN if scope_clause else lexicon.find_action(clause, notice.language)
        audience = lexicon.find_audience(clause, notice.language)
        window = parse_window(clause, ref_now, notice.language)
        condition = parse_condition(clause, notice.language)
        if condition and window is not None and window.end_condition is None:
            window = _attach_condition(window, condition)

        primary = mentions[0] if mentions else (None, None)
        extraction = Extraction(
            notice_id=notice.id,
            clause_index=index,
            language=notice.language,
            force=force,
            action=action,
            span=clause,
            negated=negated,
            audience=audience,
            place_id=primary[1],
            mention=primary[0],
            generic_place=generic,
            related_place_ids=[pid for _, pid in mentions[1:]],
            window=window,
            condition=condition,
            scope_clause=scope_clause,
            translation_derived=notice.kind is SourceKind.MACHINE_TRANSLATION,
        )
        extraction.issues = structural_issues(extraction)
        results.append(extraction)
    return results


def _attach_condition(window, condition):
    from dataclasses import replace

    return replace(window, end_condition=condition)


def parse_correction(notice: Notice, registry: PlaceRegistry, ref_now: datetime) -> Correction:
    """从更正通告中抽取改名与时间变更。"""

    correction = Correction(notice_id=notice.id)
    text = notice.text
    for pattern in _RENAME_PATTERNS:
        for old, new in pattern.findall(text):
            old, new = old.strip(), new.strip()
            if old and new and old != new:
                correction.place_renames.append((old, new))
    for m in _TIME_CHANGE_ZH.finditer(text):
        subject, new_t, old_t = m.group(1), m.group(2), m.group(3)
        correction.time_changes.append(
            (subject.strip(), _hhmm(old_t, ref_now), _hhmm(new_t, ref_now), m.group(0))
        )
    for m in _TIME_CHANGE_EN.finditer(text):
        new_t, old_t = m.group(1), m.group(2)
        correction.time_changes.append(
            ("last boat", _hhmm(old_t, ref_now), _hhmm(new_t, ref_now), m.group(0))
        )
    return correction


def _hhmm(token: str, ref: datetime):
    hour, minute = token.split(":")
    return ref.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
