from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print guidance for importing the licensed Greptile benchmark manifest."
    )
    parser.add_argument("--source", help="Authorized benchmark manifest URL or local path")
    args = parser.parse_args()
    if not args.source:
        print(
            "Provide --source with an authorized Greptile benchmark manifest. "
            "ReviewCrew does not fabricate benchmark metadata or fork repositories."
        )
        return
    print(f"Import source registered: {args.source}")
    print("Normalize its records to the DatasetEntry schema in benchmark/dataset.yaml.")


if __name__ == "__main__":
    main()
