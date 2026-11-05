"""Read exported JSON array/JSONL: tenant_id,url,text,html?,timestamp?,status?. No writes."""
import json
import sys
from collections import Counter

from app.services.ir_content_guard import normalized_digest, soft_404

with open(sys.argv[1]) as source:
    raw = source.read()
try:
    rows = json.loads(raw)
except json.JSONDecodeError:
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
seen = set()
counts = Counter()
daily = Counter()
cap = int(sys.argv[2]) if len(sys.argv) > 2 else 20
for row in sorted(rows, key=lambda r: r.get("timestamp", "")):
    counts["total"] += 1
    url, text = row.get("final_url") or row.get("url") or row["source_url"], row.get("text", "")
    if row.get("status") in [404, 410] or soft_404(url, text, html=row.get("html", False)):
        counts["soft404_avoided"] += 1
        continue
    digest = normalized_digest(text, html=row.get("html", False)) if text else row.get("normalized_chunk_text_sha256")
    if not digest:
        counts["unverifiable_missing_text"] += 1
        continue
    if not text:
        counts["using_exported_whitespace_hash"] += 1
    key = (row["tenant_id"], url, digest)
    if key in seen:
        counts["duplicate_avoided"] += 1
        continue
    seen.add(key)
    day = (row["tenant_id"], (row.get("timestamp") or row.get("created_at", "unknown"))[:10])
    if daily[day] >= cap:
        counts["daily_deferred"] += 1
        continue
    daily[day] += 1
    counts["would_call"] += 1
print(json.dumps(dict(counts), indent=2))
