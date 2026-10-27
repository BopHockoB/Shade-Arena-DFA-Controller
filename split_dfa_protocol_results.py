#!/usr/bin/env python3
"""
Split protocol results into DFA / non-DFA, moving each data file and its
transcript file together.

  protocol_results/intervention_data/<task>/<type>/<protocol>/<agent>/<monitor>/transcript_N.json
  protocol_results/intervention_transcripts/<task>/<type>/<protocol>/<agent>/<monitor>/transcript_N.json

A pair is DFA if its DATA file contains a message with "role": "DFAController"
(transcript files never do). Both files move to <type>_dfa, rest of the path unchanged.

Usage:
  python split_dfa_protocol_results.py protocol_results --dry-run   # preview
  python split_dfa_protocol_results.py protocol_results             # move
"""
import argparse
import re
import shutil
from collections import Counter
from pathlib import Path

DFA_RE = re.compile(r'"role"\s*:\s*"DFAController"')
IDX_RE = re.compile(r'(\d+)\.json$')
SUFFIX = "_dfa"
TYPE_LEVEL = 1  # <task>/<type>/... -> index of <type> in the relative path


def find_partner(data_file: Path, data_root: Path, tr_root: Path) -> Path | None:
    """Transcript file for a data file: same relative path, else same dir + same index."""
    rel = data_file.relative_to(data_root)
    same = tr_root / rel
    if same.exists():
        return same
    m = IDX_RE.search(data_file.name)
    if m and same.parent.is_dir():
        hits = [p for p in same.parent.glob(f"*{m.group(1)}.json")
                if IDX_RE.search(p.name) and IDX_RE.search(p.name).group(1) == m.group(1)]
        if len(hits) == 1:
            return hits[0]
    return None


def dfa_dest(path: Path, root: Path) -> Path:
    parts = list(path.relative_to(root).parts)
    parts[TYPE_LEVEL] += SUFFIX
    return root.joinpath(*parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="protocol_results dir")
    ap.add_argument("--data-dir", default="intervention_data")
    ap.add_argument("--transcripts-dir", default="intervention_transcripts")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data_root = (args.root / args.data_dir).resolve()
    tr_root = (args.root / args.transcripts_dir).resolve()
    for r in (data_root, tr_root):
        if not r.is_dir():
            raise SystemExit(f"not a directory: {r}")

    stats = Counter()
    matched_transcripts = set()

    for data_file in sorted(data_root.rglob("*.json")):
        rel = data_file.relative_to(data_root).parts
        if len(rel) <= TYPE_LEVEL + 1 or rel[TYPE_LEVEL].endswith(SUFFIX):
            continue
        stats["data_scanned"] += 1

        partner = find_partner(data_file, data_root, tr_root)
        if partner is None:
            print(f"  ! no transcript for {data_file.relative_to(data_root)} (left in place)")
            stats["orphan_data"] += 1
            continue
        matched_transcripts.add(partner.resolve())

        try:
            is_dfa = bool(DFA_RE.search(data_file.read_text(encoding="utf-8", errors="ignore")))
        except OSError as e:
            print(f"  ! cannot read {data_file}: {e}")
            stats["unreadable"] += 1
            continue
        if not is_dfa:
            stats["non_dfa"] += 1
            continue

        d_dest, t_dest = dfa_dest(data_file, data_root), dfa_dest(partner, tr_root)
        clash = [p for p in (d_dest, t_dest) if p.exists()]
        if clash:
            print(f"  ! destination exists, skipping pair: {', '.join(map(str, clash))}")
            stats["skipped_exists"] += 1
            continue

        tag = "[dry] " if args.dry_run else ""
        print(f"{tag}{data_file.relative_to(data_root)}  (+ transcript) -> {d_dest.relative_to(data_root).parts[TYPE_LEVEL]}")
        if not args.dry_run:
            d_dest.parent.mkdir(parents=True, exist_ok=True)
            t_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(data_file), str(d_dest))
            try:
                shutil.move(str(partner), str(t_dest))
            except Exception as e:  # keep the pair together: undo the first move
                shutil.move(str(d_dest), str(data_file))
                print(f"  ! failed to move transcript ({e}); data file restored")
                stats["failed"] += 1
                continue
        stats["moved_pairs"] += 1

    # transcripts with no data file
    for t in tr_root.rglob("*.json"):
        rel = t.relative_to(tr_root).parts
        if len(rel) > TYPE_LEVEL + 1 and not rel[TYPE_LEVEL].endswith(SUFFIX) and t.resolve() not in matched_transcripts:
            print(f"  ! no data file for transcript {t.relative_to(tr_root)} (left in place)")
            stats["orphan_transcripts"] += 1

    verb = "would move" if args.dry_run else "moved"
    print(f"\nScanned {stats['data_scanned']} data files: {verb} {stats['moved_pairs']} DFA pairs, "
          f"{stats['non_dfa']} non-DFA left, {stats['orphan_data']} data orphans, "
          f"{stats['orphan_transcripts']} transcript orphans, {stats['skipped_exists']} skipped (exists), "
          f"{stats['failed'] + stats['unreadable']} errors.")


if __name__ == "__main__":
    main()
