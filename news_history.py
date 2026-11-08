"""First-seen headline archive, separate from the legacy latest-headline cache."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


def stamp(value=None):
    t = pd.Timestamp(value) if value is not None else pd.Timestamp.now(tz='UTC')
    if t.tzinfo is None:
        raise ValueError('News timestamps require an explicit timezone')
    return t.tz_convert('UTC')


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def archive_current(root, observed_at=None):
    root, now = Path(root), stamp(observed_at)
    path = root / 'data' / 'news_history' / 'headlines-v1.jsonl'
    old = _rows(path)
    ids = {r['id'] for r in old}
    added = []
    for cache in sorted((root / 'data' / 'raw' / 'news').glob('*.json')):
        try:
            items = json.loads(cache.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if not isinstance(items, list):
            continue
        symbol = cache.stem.removeprefix('yahoo_').upper() if cache.stem.startswith('yahoo_') else '*'
        for item in items:
            if not isinstance(item, dict) or not item.get('title'):
                continue
            url = str(item.get('url') or '')
            if not url.startswith(('https://', 'http://')):
                continue
            content = {'symbol': symbol, 'title': str(item['title']), 'url': url,
                       'publisher': str(item.get('publisher') or ''),
                       'published_at': str(item.get('time') or '') or None}
            identity = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
            if identity in ids:
                continue
            row = {**content, 'id': identity, 'first_seen_at': now.isoformat(),
                   'available_at': now.isoformat(), 'archive_version': 1,
                   'availability_basis': 'first_archived_receipt',
                   'source_cache': cache.name}
            added.append(row)
            ids.add(identity)
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            for row in added:
                stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
    return {'added': len(added), 'total': len(old) + len(added), 'as_of': now.isoformat()}


def load(root, symbol, as_of=None, limit=20):
    now = stamp(as_of)
    result = []
    for row in _rows(Path(root) / 'data' / 'news_history' / 'headlines-v1.jsonl'):
        if row.get('symbol') not in (symbol.upper(), '*'):
            continue
        if stamp(row['available_at']) > now:
            continue
        if row.get('published_at'):
            try:
                if stamp(row['published_at']) > now:
                    continue
            except (ValueError, TypeError):
                continue
        result.append(row)
    # Multiple article revisions remain auditable, but the workspace shows latest known version per URL.
    latest = {}
    for row in sorted(result, key=lambda r: r['available_at']):
        latest[row['url']] = row
    def ordering(row):
        try:
            published = stamp(row['published_at']) if row.get('published_at') else stamp(row['first_seen_at'])
        except (ValueError, TypeError):
            published = stamp(row['first_seen_at'])
        return published, stamp(row['first_seen_at'])
    return sorted(latest.values(), key=ordering, reverse=True)[:limit]
