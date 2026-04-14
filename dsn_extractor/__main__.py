"""CLI entry point: python -m dsn_extractor path/to/file.dsn"""

from __future__ import annotations

import argparse
import json
import os
import sys

from dsn_extractor.extractors import extract
from dsn_extractor.parser import parse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dsn_extractor",
        description="Extract structured metrics from a French DSN file.",
    )
    parser.add_argument("file", help="Path to the .dsn file")
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--per-establishment",
        action="store_true",
        default=True,
        help="Include per-establishment detail (default)",
    )
    mode.add_argument(
        "--global-only",
        action="store_true",
        help="Output only global aggregates, omit per-establishment detail",
    )

    args = parser.parse_args(argv)

    try:
        try:
            text = open(args.file, encoding="utf-8").read()
        except UnicodeDecodeError:
            text = open(args.file, encoding="latin-1").read()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parsed = parse(text)

    if len(parsed.all_records) == 0:
        print("Error: file contains no valid DSN lines", file=sys.stderr)
        return 1

    try:
        result = extract(parsed, source_file=os.path.basename(args.file))
    except Exception as exc:
        print(f"Error during extraction: {exc}", file=sys.stderr)
        return 1

    exclude = {"establishments"} if args.global_only else None
    data = result.model_dump(mode="json", exclude=exclude)
    indent = 2 if args.pretty else None
    print(json.dumps(data, indent=indent, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
