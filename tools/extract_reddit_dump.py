"""Extrait d'un dump mensuel Pushshift (RS_YYYY-MM.zst, tous les posts Reddit)
uniquement les posts des subreddits boursiers, en flux (rien n'est stocké en
entier sur disque). Écrit un fichier .jsonl.gz compact par mois.

Usage : python tools/extract_reddit_dump.py YYYY-MM OUT_DIR
"""

import gzip
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import zstandard

BASE = "https://huggingface.co/datasets/Binxk/pushshift-reddit/resolve/main/original_dump/submissions"
SUBREDDITS = [
    "wallstreetbets", "stocks", "investing", "stockmarket", "options",
    "pennystocks", "daytrading", "smallstreetbets", "securityanalysis",
    "valueinvesting", "dividends", "thetagang", "wallstreetbetselite",
]
SUB_RE = re.compile(rb'"subreddit"\s*:\s*"(' + b"|".join(s.encode() for s in SUBREDDITS) + rb')"', re.I)
MAX_SELFTEXT = 1500


def extract(month, out_dir, retries=4):
    out = Path(out_dir) / f"RS_{month}.jsonl.gz"
    if out.exists():
        print(f"{month}: déjà fait", flush=True)
        return
    url = f"{BASE}/RS_{month}.zst"
    for attempt in range(1, retries + 1):
        tmp = out.with_suffix(".tmp")
        t0, seen, kept = time.time(), 0, 0
        proc = subprocess.Popen(
            ["curl", "-sS", "-L", "--fail", url], stdout=subprocess.PIPE
        )
        try:
            reader = zstandard.ZstdDecompressor(max_window_size=2**31).stream_reader(proc.stdout)
            text = io.BufferedReader(reader, buffer_size=1 << 22)
            with gzip.open(tmp, "wb", compresslevel=3) as fout:
                for line in text:
                    seen += 1
                    if not SUB_RE.search(line):
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    rec = {
                        "t": d.get("created_utc"),
                        "sub": d.get("subreddit"),
                        "title": d.get("title") or "",
                        "text": (d.get("selftext") or "")[:MAX_SELFTEXT],
                        "score": d.get("score"),
                        "n": d.get("num_comments"),
                    }
                    fout.write((json.dumps(rec, ensure_ascii=False) + "\n").encode())
                    kept += 1
            if proc.wait() != 0:
                raise RuntimeError(f"curl a échoué (code {proc.returncode})")
            tmp.rename(out)
            print(f"{month}: {kept} posts gardés sur {seen} en {time.time() - t0:.0f}s", flush=True)
            return
        except Exception as exc:  # réseau coupé en cours de route : on recommence le mois
            proc.kill()
            print(f"{month}: tentative {attempt} échouée ({exc})", flush=True)
            time.sleep(5 * attempt)
    print(f"{month}: ABANDON", flush=True)


if __name__ == "__main__":
    Path(sys.argv[2]).mkdir(parents=True, exist_ok=True)
    extract(sys.argv[1], sys.argv[2])
