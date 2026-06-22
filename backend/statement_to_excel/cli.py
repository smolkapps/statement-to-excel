"""Tiny CLI wrapper around the engine: ``stx statement.pdf -o out.xlsx``.

The web-app is the product; this CLI exists so the same engine is scriptable and
so power users / CI can batch-convert without the server. Format is inferred
from the output extension (``.xlsx`` / ``.csv`` / ``.json``); with no ``-o`` it
writes CSV to stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .engine import ConversionError, convert_pdf
from .writers import to_csv_bytes, to_csv_str, to_json_bytes, to_xlsx_bytes


def _infer_format(output: Optional[str], explicit: Optional[str]) -> str:
    if explicit:
        return explicit.lower()
    if output:
        suffix = Path(output).suffix.lower().lstrip(".")
        if suffix in {"xlsx", "csv", "json"}:
            return suffix
    return "csv"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stx", description="Convert a bank-statement PDF to a spreadsheet."
    )
    parser.add_argument("pdf", help="path to the input statement PDF")
    parser.add_argument("-o", "--output", help="output file (format from extension)")
    parser.add_argument("--format", choices=["xlsx", "csv", "json"], default=None)
    parser.add_argument("--currency", default="USD")
    args = parser.parse_args(argv)

    if not Path(args.pdf).exists():
        print(f"error: file not found: {args.pdf}", file=sys.stderr)
        return 2

    try:
        txns = convert_pdf(args.pdf, currency=args.currency)
    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    fmt = _infer_format(args.output, args.format)

    if not args.output:
        if fmt == "xlsx":
            print("error: xlsx output requires -o (binary file)", file=sys.stderr)
            return 2
        if fmt == "json":
            from .writers import to_json_str

            sys.stdout.write(to_json_str(txns) + "\n")
        else:
            sys.stdout.write(to_csv_str(txns))
        return 0

    if fmt == "xlsx":
        Path(args.output).write_bytes(to_xlsx_bytes(txns))
    elif fmt == "json":
        Path(args.output).write_bytes(to_json_bytes(txns))
    else:
        Path(args.output).write_bytes(to_csv_bytes(txns))
    print(f"wrote {len(txns)} transactions to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
