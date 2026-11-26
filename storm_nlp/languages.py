"""语种识别与分句/分条。

演练资料只涉及中文与英文；按字符集判定语种，按各自标点切分。
分条结果保留顺序编号，便于用 ``通告编号#条号`` 做溯源引用。
"""

from __future__ import annotations

import re

from .models import Language

_ZH_RE = re.compile(r"[一-鿿]")
_EN_RE = re.compile(r"[A-Za-z]")

# 中文按句末标点与分号切条（分号在通告里通常分隔另一条安排）
_ZH_SPLIT_RE = re.compile(r"[。！？；\n]+")
# 英文按句末标点与分号切条
_EN_SPLIT_RE = re.compile(r"[.;!?]\s+|\n+")


def detect_language(text: str) -> Language:
    zh = len(_ZH_RE.findall(text))
    en = len(_EN_RE.findall(text))
    return Language.ZH if zh >= en else Language.EN


def split_clauses(text: str, language: Language) -> list[str]:
    """把通告正文切成有序条款，去掉空白条。"""

    pattern = _ZH_SPLIT_RE if language is Language.ZH else _EN_SPLIT_RE
    parts = pattern.split(text)
    return [p.strip(" 　,，") for p in parts if p and p.strip(" 　,，")]
