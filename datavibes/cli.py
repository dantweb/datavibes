"""The ``datavibes`` console script — a thin argparse shell over ``DatasetSDK``.

Every command maps to one facade method. There is no logic here beyond parsing
arguments and printing results.
"""

from __future__ import annotations

import argparse
import os
import sys

from datavibes.config.app_config import describe_config
from datavibes.errors import DatavibesError
from datavibes.sdk import DatasetSDK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datavibes",
        description="Collect data and generate versioned dataset snapshots.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="directory holding dataset folders (default: config.yaml paths.datasets_root)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list known datasets + metadata")
    subparsers.add_parser(
        "config", help="print the resolved effective config (secrets masked)"
    )

    new_parser = subparsers.add_parser("new", help="scaffold a new dataset")
    new_parser.add_argument("slug")
    new_parser.add_argument("--category", required=True)

    for name, help_text in (
        ("validate", "load config, check schema + sources resolve"),
        ("generate", "fetch sources -> raw snapshot"),
        ("process", "latest raw -> processed rows"),
        ("run", "generate + process + export (the cron target)"),
        ("info", "show latest snapshot path + row count"),
    ):
        single = subparsers.add_parser(name, help=help_text)
        single.add_argument("slug")

    export_parser = subparsers.add_parser("export", help="re-export processed rows")
    export_parser.add_argument("slug")
    export_parser.add_argument(
        "--format", default=None, choices=["csv", "json", "parquet"]
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sdk = DatasetSDK(root=args.root)
    try:
        return _dispatch(sdk, args)
    except DatavibesError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _dispatch(sdk: DatasetSDK, args: argparse.Namespace) -> int:
    handler = {
        "list": _cmd_list,
        "config": _cmd_config,
        "new": _cmd_new,
        "validate": _cmd_validate,
        "generate": _cmd_generate,
        "process": _cmd_process,
        "export": _cmd_export,
        "run": _cmd_run,
        "info": _cmd_info,
    }[args.command]
    return handler(sdk, args)


def _cmd_config(sdk: DatasetSDK, _args: argparse.Namespace) -> int:
    print(describe_config(sdk.app_config, os.environ))
    return 0


def _cmd_list(sdk: DatasetSDK, _args: argparse.Namespace) -> int:
    infos = sdk.list()
    if not infos:
        print("no datasets found")
        return 0
    for info in infos:
        print(f"{info.slug}\t{info.category}\t{info.title}")
    return 0


def _cmd_new(sdk: DatasetSDK, args: argparse.Namespace) -> int:
    path = sdk.scaffold(args.slug, args.category)
    print(f"created {path}")
    return 0


def _cmd_validate(sdk: DatasetSDK, args: argparse.Namespace) -> int:
    config = sdk.validate(args.slug)
    print(
        f"ok: {config.slug} "
        f"({len(config.schema.fields)} fields, "
        f"{len(config.sources)} source(s), "
        f"{len(config.processing)} step(s))"
    )
    return 0


def _cmd_generate(sdk: DatasetSDK, args: argparse.Namespace) -> int:
    snapshot = sdk.generate(args.slug)
    print(f"raw snapshot: {snapshot.path} ({snapshot.row_count} rows)")
    for failure in snapshot.failed_sources:
        print(f"  warning: source failed -> {failure}", file=sys.stderr)
    return 0


def _cmd_process(sdk: DatasetSDK, args: argparse.Namespace) -> int:
    rows = sdk.process(args.slug)
    print(f"processed {len(rows)} rows")
    return 0


def _cmd_export(sdk: DatasetSDK, args: argparse.Namespace) -> int:
    path = sdk.export(args.slug, fmt=args.format)
    print(f"exported: {path}")
    return 0


def _cmd_run(sdk: DatasetSDK, args: argparse.Namespace) -> int:
    path = sdk.run(args.slug)
    print(f"snapshot: {path}")
    return 0


def _cmd_info(sdk: DatasetSDK, args: argparse.Namespace) -> int:
    info = sdk.info(args.slug)
    latest = info.latest_output or "(none)"
    print(f"{info.slug}: latest={latest} rows={info.row_count}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
