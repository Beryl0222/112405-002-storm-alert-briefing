"""值班中心命令行入口。

用法示例（在仓库根目录执行）::

    python3 -m storm_nlp.cli review --data data/drill
    python3 -m storm_nlp.cli ask --data data/drill --question "北湾避护中心怎么去？"
    python3 -m storm_nlp.cli trace --data data/drill --gid G-003
    python3 -m storm_nlp.cli export --data data/drill --db run/drill.sqlite

所有数据均为虚构演练资料。
"""

from __future__ import annotations

import argparse
from datetime import datetime

from .dataio import load_inquiries, load_network, load_notices, load_registry
from .guidance import GuidanceManager
from .ingest import IngestPipeline
from .inquiry import InquiryService
from .lexicon import is_correction
from .models import SourceKind
from .review import ReviewService
from .storage import Storage

REF_NOW = datetime(2026, 11, 26, 14, 0)


def build_pipeline(data_dir: str, db_path: str | None = None) -> IngestPipeline:
    registry = load_registry(data_dir)
    network = load_network(data_dir, registry)
    storage = Storage(db_path) if db_path else None
    pipeline = IngestPipeline(registry, network, REF_NOW, storage)
    for notice in load_notices(data_dir, REF_NOW):
        if notice.kind in (SourceKind.OFFICIAL, SourceKind.ADDENDUM) and is_correction(
            notice.text, notice.language
        ):
            pipeline.ingest_correction(notice)
        else:
            pipeline.ingest(notice)
    return pipeline


def cmd_review(args: argparse.Namespace) -> int:
    pipeline = build_pipeline(args.data, args.db)
    service = ReviewService(pipeline.manager, pipeline.registry)
    print(service.render_text())
    if args.db:
        pipeline.storage.close()
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    pipeline = build_pipeline(args.data, args.db)
    inquiry = InquiryService(pipeline.manager, pipeline.registry)
    answer = inquiry.answer(args.question)
    print(f"问：{answer.question}")
    print(f"答（置信：{'是' if answer.confident else '否'}）：{answer.text}")
    if answer.cited:
        print(f"溯源：{'、'.join(answer.cited)}")
    if args.db:
        pipeline.storage.close()
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    pipeline = build_pipeline(args.data, args.db)
    result = pipeline.manager.trace(args.gid)
    if result is None:
        print(f"未找到指引 {args.gid}")
        return 1
    g = result.guidance
    print(f"指引 {g.gid}：{g.title}（状态 {g.status.value}）")
    print("依据原文：")
    for notice in result.sources:
        print(f"  [{notice.id} | {notice.language.value} | {notice.kind.value}] {notice.text}")
    for basis in result.spans:
        print(f"  条款 {basis.notice_id}#{basis.clause_index}：{basis.span}")
    if args.db:
        pipeline.storage.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    pipeline = build_pipeline(args.data, args.db)
    print(f"已写入持久化数据库：{args.db}")
    rows = pipeline.storage.list_guidances()
    print(f"共保存指引 {len(rows)} 条；审计事件 {len(pipeline.storage.audit_trail())} 条")
    pipeline.storage.close()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    pipeline = build_pipeline(args.data, args.db)
    manager: GuidanceManager = pipeline.manager
    review = ReviewService(manager, pipeline.registry)
    print(review.render_text())

    print("\n" + "=" * 78)
    print("居民问询应答（仅依据现行有效指引，转述与失效内容不作事实答复）")
    print("=" * 78)
    inquiry = InquiryService(manager, pipeline.registry)
    for item in load_inquiries(args.data):
        answer = inquiry.answer(item["text"])
        print(f"\n[{item['id']}] 问：{answer.question}")
        print(f"答：{answer.text}")
        if answer.cited:
            print(f"溯源：{'、'.join(answer.cited)}")

    print("\n" + "=" * 78)
    print("更正影响清单：哪些指引已失效/被取代，哪些仍可沿用")
    print("=" * 78)
    from .models import GuidanceStatus

    for g in manager.guidances:
        if g.status in (GuidanceStatus.INVALIDATED, GuidanceStatus.SUPERSEDED):
            print(f"· {g.gid} {g.status.value}：{g.title} → {g.invalidated_reason}")
    print("仍可沿用：")
    for g in manager.active():
        print(f"· {g.gid}：{g.title}（依据 {g.cite()}）")

    if args.db:
        print(f"\n持久化数据库：{args.db}（{len(pipeline.storage.audit_trail())} 条审计事件）")
        pipeline.storage.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="沿海值班中心多语种风暴通告 NLP 工具（演练）")
    parser.add_argument("--data", default="data/drill", help="演练数据目录")
    parser.add_argument("--db", help="可选 SQLite 数据库路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("review", help="输出值班员五维核对报告").set_defaults(func=cmd_review)
    ask = sub.add_parser("ask", help="回答居民问询")
    ask.add_argument("--question", required=True)
    ask.set_defaults(func=cmd_ask)
    trace = sub.add_parser("trace", help="回溯指引所依据的原文")
    trace.add_argument("--gid", required=True)
    trace.set_defaults(func=cmd_trace)
    sub.add_parser("export", help="写入 SQLite 持久化").set_defaults(func=cmd_export)
    sub.add_parser("demo", help="一键运行完整演练").set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
