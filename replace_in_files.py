#!/usr/bin/env python3
"""
Find and replace strings (e.g. model names) in every file under a directory.

Usage:
  python3 replace_in_files.py <root_dir>                     # dry run, uses REPLACEMENTS below
  python3 replace_in_files.py <root_dir> --apply             # actually writes changes
  python3 replace_in_files.py <root_dir> -r OLD=NEW -r A=B   # replacements from the command line
  python3 replace_in_files.py <root_dir> --ext .py .sh       # only these file types
  python3 replace_in_files.py <root_dir> --apply --backup    # keep a .bak copy of each changed file
"""
import argparse
import re
import sys
from pathlib import Path

# Edit this mapping, or pass -r OLD=NEW on the command line instead.
REPLACEMENTS = {
    "Qwen/Qwen3.6-27B-FP8": "Qwen3.6-27B-FP8",
    "RedHatAI/gemma-4-31B-it-FP8-block": "gemma-4-31B-it-FP8-block"
}

DEFAULT_EXTS = [".py", ".sh", ".ipynb", ".json", ".yaml", ".yml", ".txt", ".md", ".cfg", ".toml"]
SKIP_DIRS = {".git", "__pycache__", ".ipynb_checkpoints", "node_modules", ".venv", "venv"}


def build_pattern(mapping):
    # Longest keys first, so "Qwen/Qwen3.6-27B-FP8" wins over "Qwen3.6-27B-FP8".
    # One regex pass means a replaced value is never replaced again.
    keys = sorted(mapping, key=len, reverse=True)
    return re.compile("|".join(re.escape(k) for k in keys))


def iter_files(root, exts):
    for p in root.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if exts and p.suffix.lower() not in exts:
            continue
        yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path)
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    ap.add_argument("--backup", action="store_true", help="save original as <file>.bak before writing")
    ap.add_argument("-r", "--replace", action="append", default=[], metavar="OLD=NEW",
                    help="replacement pair; can be repeated; overrides REPLACEMENTS")
    ap.add_argument("--ext", nargs="*", default=DEFAULT_EXTS,
                    help="file extensions to process; pass --ext with nothing after it for all files")
    args = ap.parse_args()

    if args.replace:
        mapping = {}
        for pair in args.replace:
            if "=" not in pair:
                sys.exit(f"Bad --replace value (expected OLD=NEW): {pair}")
            old, new = pair.split("=", 1)
            mapping[old] = new
    else:
        mapping = REPLACEMENTS

    mapping = {k: v for k, v in mapping.items() if k and k != v}
    if not mapping:
        sys.exit("No replacements given.")

    root = args.root.resolve()
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in args.ext}
    pattern = build_pattern(mapping)

    print("Replacements:")
    for k, v in mapping.items():
        print(f"  {k!r} -> {v!r}")
    print()

    files_changed = total_hits = skipped = 0
    for path in iter_files(root, exts):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped += 1  # binary or unreadable
            continue

        hits = len(pattern.findall(text))
        if not hits:
            continue

        new_text = pattern.sub(lambda m: mapping[m.group(0)], text)
        files_changed += 1
        total_hits += hits
        print(f"{hits:5d}  {path.relative_to(root)}")

        if args.apply:
            if args.backup:
                path.with_name(path.name + ".bak").write_text(text, encoding="utf-8")
            tmp = path.with_name(path.name + ".tmp_replace")
            tmp.write_text(new_text, encoding="utf-8")
            tmp.replace(path)  # atomic swap, so a crash can't leave a half-written file

    print()
    verb = "Changed" if args.apply else "Would change"
    print(f"{verb} {total_hits} occurrence(s) in {files_changed} file(s). Skipped {skipped} unreadable file(s).")
    if not args.apply and files_changed:
        print("Dry run only. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
