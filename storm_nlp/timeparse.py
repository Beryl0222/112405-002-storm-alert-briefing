"""时间窗与潮位条件解析。

支持演练通告中的表达：

* 「11月26日18:00」「22:30」等绝对/当日时刻；
* 「自……起」判定为起点，「至……止 / 末班船……」判定为终点；
* 「潮位低于一米二」「开放至潮位回落」解析为条件而非时刻。

解析器只依赖标准库，参考时刻由调用方传入，便于演练复现。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .models import Condition, Language, TimeWindow

_DATETIME_RE = re.compile(r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_EN_DATETIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(?:on|on\s+)?(?:Nov(?:ember)?\s+)?(\d{1,2})?", re.IGNORECASE)

_START_CUE_RE = re.compile(r"(自|从|starting\s+from|from)\W{0,6}(\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2})", re.IGNORECASE)
_END_CUE_RE = re.compile(r"(至|到|截止|末班|until|by|before|ends?\s+at|last\s+boat\s+(?:is\s+at)?)\W{0,6}(\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2})", re.IGNORECASE)

_TIDE_BELOW_ZH = re.compile(r"潮位低于(一)米(二)|潮位低于([\d.]+)\s*米?")
_TIDE_BELOW_EN = re.compile(r"tide\s+(?:falls|drops)?\s*below\s*([\d.]+)\s*m", re.IGNORECASE)
_TIDE_RECEDE_RE = re.compile(r"潮位回落|tide\s+recedes?", re.IGNORECASE)

_CN_FIXED = {"一米二": 1.2, "一米五": 1.5}


def _at(ref: datetime, hour: int, minute: int, month: Optional[int] = None, day: Optional[int] = None) -> datetime:
    return ref.replace(month=month or ref.month, day=day or ref.day, hour=hour, minute=minute, second=0, microsecond=0)


def _parse_moment(token: str, ref: datetime) -> datetime:
    m = _DATETIME_RE.search(token)
    if m:
        month, day, hour, minute = (int(g) for g in m.groups())
        return _at(ref, hour, minute, month, day)
    m = _TIME_RE.search(token)
    if m:
        return _at(ref, int(m.group(1)), int(m.group(2)))
    raise ValueError(f"无法解析时刻：{token}")


def parse_window(clause: str, ref_now: datetime, language: Language) -> Optional[TimeWindow]:
    """从条款中解析时间窗；没有任何时刻时返回 None。"""

    start: Optional[datetime] = None
    end: Optional[datetime] = None
    raw_tokens: list[str] = []

    for m in _START_CUE_RE.finditer(clause):
        start = _parse_moment(m.group(2), ref_now)
        raw_tokens.append(m.group(0))
    for m in _END_CUE_RE.finditer(clause):
        end = _parse_moment(m.group(2), ref_now)
        raw_tokens.append(m.group(0))

    # 没有起止提示词时，裸时刻按语义兜底：开放句视为起点，末班/截止句视为终点
    if start is None and end is None:
        for m in _TIME_RE.finditer(clause):
            moment = _parse_moment(m.group(0), ref_now)
            raw_tokens.append(m.group(0))
            head = clause[max(0, m.start() - 6): m.start()]
            if re.search(r"末班|截止|至|到|until|last|by", head, re.IGNORECASE):
                end = moment
            elif re.search(r"开放|open", clause, re.IGNORECASE):
                start = moment
            else:
                end = moment

    end_condition = parse_condition(clause, language)
    if start is None and end is None and end_condition is None:
        return None
    return TimeWindow(raw="；".join(raw_tokens) or clause[:24], start=start, end=end, end_condition=end_condition)


def parse_condition(clause: str, language: Language) -> Optional[Condition]:
    """解析潮位条件；普通时间窗结束条件与限定条件共用此入口。"""

    if language is Language.ZH:
        m = _TIDE_BELOW_ZH.search(clause)
        if m:
            if m.group(1) == "一" and m.group(2) == "二":
                return Condition("tide_below", m.group(0), 1.2)
            return Condition("tide_below", m.group(0), float(m.group(3)))
    else:
        m = _TIDE_BELOW_EN.search(clause)
        if m:
            return Condition("tide_below", m.group(0), float(m.group(1)))
    if _TIDE_RECEDE_RE.search(clause):
        return Condition("tide_recede", _TIDE_RECEDE_RE.search(clause).group(0))
    return None
