"""沿海值班中心多语种风暴通告 NLP 工具包。

所有演练资料均为虚构内容，不对应真实人员、机构、地点或业务决定。
包内模块按处理流水线划分：

* models      领域数据模型
* languages   语种识别与分句
* timeparse   生效时间窗与潮位条件解析
* places      地名登记与跨语种译名去重
* lexicon     多语种关键词与句式表
* extract     单语通告要素抽取（地点/时间/对象/条件/行动/效力等级）
* bilingual   原文—译文一致性核对（否定缺失、条件范围扩大等）
* ingest      入库流水线与发布闸门
* graph       道路网络、封路与无障碍路径
* guidance    指引生命周期（生效、失效、更正、溯源）
* inquiry     居民问询应答
* storage     SQLite 持久化与审计事件
* review      值班员五维核对报告
"""

from __future__ import annotations

__version__ = "0.2.0"
