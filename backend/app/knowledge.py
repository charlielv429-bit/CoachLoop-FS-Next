import json
import re
from pathlib import Path

SOURCE_FILE = Path(__file__).resolve().parents[2] / 'data' / 'sources.json'


def sources():
    return json.loads(SOURCE_FILE.read_text(encoding='utf-8'))


def tokens(text):
    text = text.lower()
    words = re.findall(r'[a-z0-9]+', text)
    chinese = re.findall(r'[\u4e00-\u9fff]+', text)
    return set(words + [s[i:i+2] for s in chinese for i in range(max(1, len(s)-1))])


def retrieve(query, limit=4):
    query_tokens = tokens(query)
    ranked = []
    for source in sources():
        if not (source['verification_status'] in ('verified', 'confirmed') or source.get('scan_checked') is True) or not source['content'].strip():
            continue
        score = len(query_tokens & tokens(source['title'] + ' ' + source['content']))
        if score:
            ranked.append((score, source))
    return [item for _, item in sorted(ranked, key=lambda x: x[0], reverse=True)[:limit]]
