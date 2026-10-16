"""Blind expert rating (``python -m app.rate sheet|analyze``), measure M8.

``sheet`` draws the properties to rate from run records and writes two files: the sheet to hand to
the raters (no condition anywhere) and the key to keep away from them. ``analyze`` reads the filled
ratings (a JSON list) and prints the agreement of every pair of raters and the per-condition,
per-family values for ``app.analyze_runs``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.experiment import RunRecord
from app.domain.rating import Rating, RatingSheet, agreements, build_sheet, rating_values


def rate_main() -> None:
    """Build a sheet, or analyze filled ratings."""
    parser = argparse.ArgumentParser(description="Blind rating of properties.")
    commands = parser.add_subparsers(dest="command", required=True)
    sheet = commands.add_parser("sheet", help="draw the items to rate")
    sheet.add_argument("records", nargs="+", type=Path, help="JSON lines of run records")
    sheet.add_argument("--per-family", type=int, default=10)
    sheet.add_argument("--seed", default="pn-llm")
    sheet.add_argument("--items-out", type=Path, required=True, help="for the raters")
    sheet.add_argument("--key-out", type=Path, required=True, help="kept away from the raters")
    analyze = commands.add_parser("analyze", help="agreement and values from filled ratings")
    analyze.add_argument("--key", type=Path, required=True, help="the sheet file written by sheet")
    analyze.add_argument("ratings", type=Path, help="a JSON list of ratings")
    arguments = parser.parse_args()
    if arguments.command == "sheet":
        records = tuple(
            RunRecord.model_validate_json(line)
            for path in arguments.records
            for line in path.read_text().splitlines()
            if line.strip()
        )
        built = build_sheet(records=records, per_family=arguments.per_family, seed=arguments.seed)
        arguments.items_out.write_text(
            TypeAdapter(type(built.items)).dump_json(built.items, indent=1).decode() + "\n"
        )
        arguments.key_out.write_text(built.model_dump_json(indent=1) + "\n")
        return
    full = RatingSheet.model_validate_json(arguments.key.read_text())
    ratings = TypeAdapter(tuple[Rating, ...]).validate_json(arguments.ratings.read_text())
    sys.stdout.write(
        TypeAdapter(dict[str, object])
        .dump_json(
            {
                "agreement": agreements(ratings=ratings),
                "values": rating_values(sheet=full, ratings=ratings),
            },
            indent=2,
        )
        .decode()
        + "\n"
    )


if __name__ == "__main__":
    rate_main()
