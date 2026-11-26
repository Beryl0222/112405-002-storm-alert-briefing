# 沿海值班中心多语种风暴通告 NLP 工作台

本项目把「多语种风暴通告 → 可核对、可发布、可撤回的避护指引」落成一条可重复运行的
Python 流水线，帮助值班人员核对**地点、时间、对象、条件、行动要求**五个维度，并据此
确认要发布的避护指引。所有样例均为**虚构演练通告**，不对应真实人员、机构、地点或业务决定。

运行环境：Python 3.11+，**无第三方运行依赖**（仅标准库）。

## 业务规则如何落地

| 演练中的问题 | 系统中的处理 |
| --- | --- |
| 「开放至潮位回落」只限定东堤闸口一处，机译却读成所有避护点同时开放 | 条件与地点绑定到同一条抽取；译文泛指句触发 `COND_SCOPE_EXPANDED` / `GENERIC_SCOPE_FABRICATION` 阻断 |
| 译文丢失否定（「请勿走涵洞」译成「应走涵洞」） | `NEG_DROP` 阻断，该译文条款标记 `TRANSLATION_BLOCKED`，不得作为命令下发 |
| 译文丢失适用对象（轮椅使用者）或适用条件 | `AUDIENCE_DROP`、`COND_MISSING` 阻断；结构不完整（缺地点/时间/行动）由发布闸门拦截 |
| 预警建议、已确认封路命令、居民转述混在一起 | 三档效力 `ADVISORY / ORDER / RELAY`；转述永远不能升级为命令，只能登记为 PENDING |
| 同一地点两个译名重复建点 | `PlaceRegistry` 按中英文名/别名归一到同一 `place_id`，新译名走合并并留痕 |
| 封桥后旧路线继续被转发 | 封路令作用于路网闸口，经过闸口的指引立即 `INVALIDATED` 并自动重算替代路线 |
| 地名/末班船时间被更正 | 更正通告把旧指引标记为 `SUPERSEDED` 并产出新指引，逐条给出失效/可沿用清单 |
| 需要查回指引依据的原文 | 每条指引携带 `BasisRef`（通告编号#条款号 + 原文片段），`trace` 可完整回溯 |

## 目录结构

```
storm_nlp/
  models.py      领域模型（通告、抽取、指引、效力等级、生命周期状态）
  languages.py   语种识别与分句/分条
  timeparse.py   时间窗与潮位条件解析
  lexicon.py     中英双语关键词与句式表
  places.py      地名登记、译名合并与误写容错
  extract.py     单语要素抽取与结构完整性自检、更正解析
  bilingual.py   原文—译文一致性核对（阻断项/提示项）
  graph.py       道路网络、闸口封路、步行/轮椅/轮渡寻路
  guidance.py    指引生命周期：发布闸门、失效、取代、替代路线、溯源
  ingest.py      入库流水线编排
  inquiry.py     居民问询应答（只依据现行有效指引）
  review.py      值班员五维核对报告
  storage.py     SQLite 持久化与审计事件
  dataio.py      演练数据加载
  cli.py         命令行入口
data/drill/      虚构演练数据（地点、路网、通告、问询）
tests/           41 个单元/集成测试
scripts/run_drill.py  一键演练
```

## 使用方式

```sh
# 跑全部测试
python3 -m unittest discover -s tests -v

# 一键完整演练（预警→译文核对→封路→转述→更正→问询）
python3 scripts/run_drill.py

# 值班员五维核对报告
python3 -m storm_nlp.cli --data data/drill review

# 居民问询
python3 -m storm_nlp.cli --data data/drill ask --question "我是轮椅使用者，临港大桥封了以后还能怎么去北湾避护中心？"

# 回溯任意指引所依据的原文
python3 -m storm_nlp.cli --data data/drill trace --gid G-010

# 写入 SQLite（指引、抽取、通告、审计事件）
python3 -m storm_nlp.cli --data data/drill --db run/drill.sqlite export
```

## 演练数据说明（全部虚构）

`data/drill/notices.json` 按时间顺序包含：

1. **N-01** 市级预警：避护点定时开放、东堤闸口潮位条件（仅限定该通道）、轮椅禁行涵洞、渡船建议；
2. **N-01-MT** 有缺陷的机器译文：丢失否定、把单通道条件外推为所有避护点——应被整体阻断；
3. **N-02** 地方补充（已确认命令）：临港大桥封闭、轮渡保持运营；
4. **N-03** 居民转述：称涵洞仍可通行——仅登记待核实；
5. **N-04** 时间更正：末班船 23:00 改为 22:00；
6. **N-05** 官方命令：涵洞封闭，并否定 N-03 的转述。

原始合成资料 `data/case.json` 保持不变，其稳定性测试继续通过。

## 设计边界

* 词表与规则面向演练句式，刻意保持透明可审计；接入真实 NLP 模型时可替换
  `lexicon.py`/`extract.py` 内部实现，而 `models.py` 的效力等级、发布闸门与生命周期契约不变。
* 机器译文在通过一致性核对前只作为**译文派生**材料保留，不进入可发布指引集合。
* 任何 BLOCKED / PENDING / INVALIDATED / SUPERSEDED 内容都不会用于居民问询的事实答复。
