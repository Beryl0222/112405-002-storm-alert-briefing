"""多语种关键词与句式表（中文 / 英文）。

词表按「效力、否定、行动、对象、泛指」五个维度组织，抽取器据此把条款
归入统一的 ForceLevel / ActionType / Audience，避免各模块各写一套正则。
"""

from __future__ import annotations

import re

from .models import ActionType, Audience, ForceLevel, Language

# 效力线索：顺序即优先级（建议措辞先于命令措辞命中，避免把「请勿」误判为建议）
FORCE_CUES: dict[Language, dict[ForceLevel, list[str]]] = {
    Language.ZH: {
        ForceLevel.RELAY: ["邻居说", "听说", "据传", "有人说", "居民反映", "据说", "转述"],
        ForceLevel.ADVISORY: ["建议", "推荐", "宜", "可前往", "请前往", "尽量", "请勿", "请不要", "不要走", "不要"],
        ForceLevel.ORDER: [
            "命令", "下令", "封闭", "关闭", "停止开放", "禁止", "不得", "即刻起",
            "现决定", "暂停", "停航", "末班", "定于", "确认",
        ],
    },
    Language.EN: {
        ForceLevel.RELAY: [
            "neighbor says", "heard that", "reportedly", "residents say",
            "someone said", "rumour", "rumor", "people say",
        ],
        ForceLevel.ADVISORY: [
            "recommend", "advised", "should", "please", "consider",
        ],
        ForceLevel.ORDER: [
            "ordered", "order", "mandatory", "is closed", "will close", "closed",
            "suspended", "do not", "don't", "must not", "prohibited", "hereby",
            "last boat", "will open", "is open",
        ],
    },
}

NEGATION_CUES: dict[Language, list[str]] = {
    Language.ZH: ["请勿", "请不要", "不要", "不能", "不得", "禁止", "勿", "无法", "不宜", "暂停使用"],
    Language.EN: ["do not", "don't", "must not", "no longer", "not ", "unavailable", "prohibited", "closed to"],
}

ACTION_CUES: dict[Language, dict[ActionType, list[str]]] = {
    Language.ZH: {
        ActionType.SUSPEND: ["停航", "暂停运营"],
        ActionType.SERVICE: ["末班船时间", "末班", "保持运营", "运营时间", "时刻"],
        ActionType.AVOID: ["请勿通行", "不要走", "勿从", "请勿从", "绕行避开", "不要通行", "停止使用"],
        ActionType.CLOSE: ["封闭", "关闭", "停开", "阻断"],
        ActionType.OPEN: ["开放", "开着", "接收", "继续开放", "可用"],
        ActionType.ROUTE: ["前往", "路线", "绕行", "改走", "经", "抵达"],
        ActionType.GATHER: ["集合", "集结"],
        ActionType.UNKNOWN: [],
    },
    Language.EN: {
        ActionType.SUSPEND: ["suspend", "ends service"],
        ActionType.SERVICE: ["last boat", "keeps running", "remains in service", "schedule"],
        ActionType.AVOID: ["do not use", "do not cross", "avoid", "do not take"],
        ActionType.CLOSE: ["close", "closed", "shut"],
        ActionType.OPEN: ["open", "available", "remains available", "accept"],
        ActionType.ROUTE: ["route to", "head to", "detour via", "via", "reach"],
        ActionType.GATHER: ["assemble", "gather at"],
        ActionType.UNKNOWN: [],
    },
}

AUDIENCE_CUES: dict[Language, dict[Audience, list[str]]] = {
    Language.ZH: {
        Audience.WHEELCHAIR: ["轮椅", "行动不便", "无障碍"],
        Audience.FERRY: ["轮渡", "渡船", "乘客", "夜班渡船", "搭船", "乘船"],
        Audience.GENERAL: [],
    },
    Language.EN: {
        Audience.WHEELCHAIR: ["wheelchair", "reduced mobility", "accessible"],
        Audience.FERRY: ["ferry", "passengers", "night boat", "by boat"],
        Audience.GENERAL: [],
    },
}

# 泛指措辞：出现时不能把时间条件挂到某一个具体点，更不能外推到所有点
GENERIC_CUES: dict[Language, list[str]] = {
    Language.ZH: ["所有避护点", "各避护点", "所有通道", "全部避护点", "各点"],
    Language.EN: ["all shelters", "all sites", "every shelter", "all routes", "all crossings"],
}

# 范围说明条款：只解释条件的适用范围，本身不构成可执行命令
SCOPE_CUES: dict[Language, list[str]] = {
    Language.ZH: ["时间条件只适用", "条件只适用", "仅适用于", "只适用于", "本条只针对"],
    Language.EN: ["this condition applies only", "applies only to", "limited to"],
}

# 更正通告的触发措辞
CORRECTION_CUES: dict[Language, list[str]] = {
    Language.ZH: ["更正", "应为", "替代", "原名", "现名", "订正"],
    Language.EN: ["correction", "should read", "renamed", "previously listed", "replace"],
}


def find_force(clause: str, language: Language, source_default: ForceLevel) -> ForceLevel:
    lower = clause if language is Language.ZH else clause.lower()
    table = FORCE_CUES[language]
    for level in (ForceLevel.RELAY, ForceLevel.ADVISORY, ForceLevel.ORDER):
        if any(cue in lower for cue in table[level]):
            return level
    return source_default


def is_negated(clause: str, language: Language) -> bool:
    lower = clause if language is Language.ZH else clause.lower()
    return any(cue in lower for cue in NEGATION_CUES[language])


def find_action(clause: str, language: Language) -> ActionType:
    lower = clause if language is Language.ZH else clause.lower()
    # 优先级：停航 > 运营时刻 > 禁行 > 封闭 > 开放 > 路线 > 集合
    priority = [
        ActionType.SUSPEND, ActionType.SERVICE, ActionType.AVOID, ActionType.CLOSE,
        ActionType.OPEN, ActionType.ROUTE, ActionType.GATHER,
    ]
    for action in priority:
        cues = ACTION_CUES[language][action]
        if any(cue in lower for cue in cues):
            return action
    return ActionType.UNKNOWN


def is_scope_clause(clause: str, language: Language) -> bool:
    lower = clause if language is Language.ZH else clause.lower()
    return any(cue in lower for cue in SCOPE_CUES[language])


def find_audience(clause: str, language: Language) -> Audience:
    lower = clause if language is Language.ZH else clause.lower()
    for audience in (Audience.WHEELCHAIR, Audience.FERRY):
        if any(cue in lower for cue in AUDIENCE_CUES[language][audience]):
            return audience
    return Audience.GENERAL


def is_generic(clause: str, language: Language) -> bool:
    lower = clause if language is Language.ZH else clause.lower()
    return any(cue in lower for cue in GENERIC_CUES[language])


def is_correction(clause: str, language: Language) -> bool:
    lower = clause if language is Language.ZH else clause.lower()
    return any(cue in lower for cue in CORRECTION_CUES[language])


def regex_find(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None
