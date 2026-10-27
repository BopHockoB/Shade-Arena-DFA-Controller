#!/usr/bin/env python3
"""
Fix duplicated provider/model segments in transcript paths.

Turns:
  task_pairs/<task>/transcripts/<provider>/<model>/<provider>/<model>/transcript_N.json
into:
  task_pairs/<task>/transcripts/<model>/<model>/transcript_N.json

Usage:
  python3 fix_transcript_paths.py /path/to/root          # dry run, just prints
  python3 fix_transcript_paths.py /path/to/root --apply  # actually moves files
"""
import sys
import re
from pathlib import Path

def models_from_json(p: Path):
    """Return (agent_model, monitor_model) stored in the file, if any."""
    try:
        with open(p) as f:
            d = json.load(f)
        return d.get("agent_model"), d.get("monitor_model")
    except Exception:
        return None, None

def find_targets(root: Path):
    """Yield (old_path, new_path) for every JSON file with split provider/model folders."""
    for p in root.rglob("*.json"):
        parts = p.parts
        if len(parts) < 6:
            continue
        # the four folders directly above the file:
        # ... / provider / model / provider / model / file.json
        prov1, model1, prov2, model2 = parts[-5:-1]

        same_model = prov1 == prov2 and model1 == model2
        agent, monitor = models_from_json(p)
        matches_json = agent == f"{prov1}/{model1}" and monitor == f"{prov2}/{model2}"

        if same_model or matches_json:
            new_path = Path(*parts[:-5], model1, model2, parts[-1])
            yield p, new_path

def main():
    if len(sys.argv) < 2:
        print("Usage: fix_transcript_paths.py <root_dir> [--apply]")
        sys.exit(1)

    root = Path(sys.argv[1]).resolve()
    apply = "--apply" in sys.argv

    changes = list(find_targets(root))
    if not changes:
        print("No matching paths found.")
        return

    for old, new in changes:
        print(f"{old}\n  -> {new}\n")

    if apply:
        moved = 0
        for old, new in changes:
            if new.exists():
                print(f"SKIP (target exists): {new}")
                continue
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            moved += 1
        print(f"Moved {moved} file(s).")

        # clean up now-empty directories left behind
        for old, _ in changes:
            d = old.parent
            while d != root and d.exists() and not any(d.iterdir()):
                empty = d
                d = d.parent
                empty.rmdir()
    else:
        print(f"{len(changes)} file(s) would be moved. Re-run with --apply to do it.")

if __name__ == "__main__":
    main()