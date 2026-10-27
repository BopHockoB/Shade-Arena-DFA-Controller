import argparse
import re
import shutil
from pathlib import Path

# Matches "role": "DFAController" with any whitespace/formatting
DFA_RE = re.compile(r'"role"\s*:\s*"DFAController"')
SUFFIX = "_dfa"
TYPE_LEVEL = 1  # index of transcript-type dir, relative to <root>/<task>/...


def has_dfa(path: Path) -> bool:
    try:
        return bool(DFA_RE.search(path.read_text(encoding="utf-8", errors="ignore")))
    except OSError as e:
        print(f"  ! could not read {path}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="root dir, e.g. task_pairs")
    ap.add_argument("--dry-run", action="store_true", help="only print what would move")
    ap.add_argument("--ext", default=".json", help="file extension to scan (default .json, '' = all)")
    args = ap.parse_args()

    root = args.root.resolve()
    moved = skipped = scanned = 0

    for f in sorted(root.rglob(f"*{args.ext}")):
        if not f.is_file():
            continue
        rel = f.relative_to(root).parts  # (task, type, model_a, model_b, ..., file)
        if len(rel) <= TYPE_LEVEL + 1:
            continue  # not deep enough to have a transcript-type dir
        if rel[TYPE_LEVEL].endswith(SUFFIX):
            continue  # already in a _dfa dir

        scanned += 1
        if not has_dfa(f):
            continue

        new_parts = list(rel)
        new_parts[TYPE_LEVEL] += SUFFIX
        dest = root.joinpath(*new_parts)

        if dest.exists():
            print(f"  ! exists, skipping: {dest}")
            skipped += 1
            continue

        print(f"{'[dry] ' if args.dry_run else ''}{f.relative_to(root)} -> {dest.relative_to(root)}")
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
        moved += 1

    print(f"\nScanned {scanned} files, {'would move' if args.dry_run else 'moved'} {moved}, skipped {skipped}.")


if __name__ == "__main__":
    main()