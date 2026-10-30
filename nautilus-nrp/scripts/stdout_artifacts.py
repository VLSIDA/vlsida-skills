#!/usr/bin/env python3
"""Move files out of a Nautilus Pod through its stdout, then reassemble and verify them on the host.

Worker side (inside the Pod; standard library only):

    from stdout_artifacts import Emitter
    out = Emitter(budget_b64=7_000_000)          # stay well under the kubelet's ~10 MiB container-log rotation
    out.file('run42', 'congestion', Path('run42_congestion.png'))
    out.event('RUN_COMPLETE', run_id='run42')

Each file becomes base64 chunk lines `UCRC <sha256> <index> <data>` followed by one event line
`UCR {"event":"ARTIFACT",...,"sha256":...,"bytes":...,"chunks":...}`. Past the budget a file is not sent; an
`ARTIFACT_STORED` event names it so a follow-up Pod can send it. Only ONE process may write these lines: with worker
processes, have them return paths and let the parent emit (pipe writes above PIPE_BUF interleave mid-line).

Host side (no cluster access; read a saved `kubectl logs` file):

    python3 stdout_artifacts.py collect --log pod.log --out ./artifacts --json summary.json

Every artifact is written only if its chunks are complete and its SHA-256 and size match; damaged or missing ones are
listed so their cases can be sent again. Parts written by the bash exporter (examples/stdout_export.sh) carry
`part`/`parts`/`full_sha256`; `assemble()` joins parts from any number of Pods and checks the whole file's hash.
"""
import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

CHUNK = 12000


class Emitter:
    """Single-writer stdout exporter with a per-Pod base64 budget."""

    def __init__(self, budget_b64=7_000_000, stream=None):
        self.budget, self.used = budget_b64, 0
        self.stream = stream or sys.stdout

    def event(self, event_name, /, **fields):   # positional-only: artifact events carry their own 'name' field
        self.stream.write('UCR ' + json.dumps({'event': event_name, **fields}, separators=(',', ':'), allow_nan=False) + '\n')
        self.stream.flush()

    def file(self, run_id, kind, path, **extra):
        data = Path(path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        text = base64.b64encode(data).decode()
        if self.used + len(text) > self.budget:
            self.event('ARTIFACT_STORED', run_id=run_id, kind=kind, name=Path(path).name, sha256=digest, bytes=len(data), path=str(path), **extra)
            return False
        chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or ['']
        self.stream.write(''.join(f'UCRC {digest} {i} {c}\n' for i, c in enumerate(chunks)))
        self.used += len(text)
        self.event('ARTIFACT', run_id=run_id, kind=kind, name=Path(path).name, sha256=digest, bytes=len(data), chunks=len(chunks), **extra)
        return True


def parse(text):
    """(chunks {sha: {index: data}}, events [dict]) from a Pod log; lines from other writers are ignored."""
    chunks, events = {}, []
    for line in text.splitlines():
        if line.startswith('UCRC '):
            parts = line.split(' ', 3)
            if len(parts) == 4 and parts[2].isdigit():
                chunks.setdefault(parts[1], {})[int(parts[2])] = parts[3]
        elif line.startswith('UCR '):
            try:
                event = json.loads(line[4:])
                if isinstance(event, dict):
                    events.append(event)
            except ValueError:
                pass
    return chunks, events


def artifact_bytes(chunks, event):
    """The verified bytes of one ARTIFACT event; ValueError when chunks are missing or the hash/size differ."""
    parts = chunks.get(event['sha256'], {})
    if sorted(parts) != list(range(event['chunks'])):
        raise ValueError(f"missing chunks for {event.get('name')}")
    data = base64.b64decode(''.join(parts[i] for i in range(event['chunks'])))
    if hashlib.sha256(data).hexdigest() != event['sha256'] or len(data) != event['bytes']:
        raise ValueError(f"checksum or size differs for {event.get('name')}")
    return data


def assemble(parts, full_sha256, full_bytes, count):
    """Join {part_index: bytes} into the whole file, or None when a part is missing or the full hash differs."""
    if sorted(parts) != list(range(count)):
        return None
    data = b''.join(parts[k] for k in range(count))
    return data if hashlib.sha256(data).hexdigest() == full_sha256 and len(data) == full_bytes else None


def artifact_target(out_dir, run_id, name):
    """Keep log-supplied names and existing symlinks inside the chosen output directory."""
    for field, value in (('run_id', run_id), ('name', name)):
        if (not isinstance(value, str) or not value or value in ('.', '..')
                or any(c in value for c in ('/', '\\', '\0'))):
            raise ValueError(f'unsafe artifact {field}: expected a single path component')
    root = Path(out_dir).resolve()
    target = root / run_id / name
    if not target.resolve().is_relative_to(root):
        raise ValueError('artifact path escapes the output directory through a symlink')
    return target


def collect(text, out_dir):
    """Write every verified artifact under out_dir/<run_id>/; return a summary of written, damaged and stored ones."""
    chunks, events = parse(text)
    out_dir = Path(out_dir)
    summary = {'written': [], 'damaged': [], 'stored_only': [], 'parts': [], 'events': [e for e in events if e.get('event') != 'ARTIFACT']}
    for e in events:
        if e.get('event') != 'ARTIFACT':
            continue
        try:
            # Validate the original name before adding a multipart suffix.
            run_id, name = e.get('run_id', 'unknown'), e['name']
            artifact_target(out_dir, run_id, name)
            part_metadata = {}
            if 'part' in e:
                part = int(e['part'])
                part_metadata = {k: e[k] for k in ('part', 'parts', 'full_sha256', 'full_bytes')}
                if not 0 <= part < int(e['parts']):
                    raise ValueError('artifact part index is outside the declared part count')
                name = f'{name}.part{part:03d}'
            target = artifact_target(out_dir, run_id, name)
            data = artifact_bytes(chunks, e)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Recheck after creating directories, before writing any artifact bytes.
            target = artifact_target(out_dir, run_id, name)
            target.write_bytes(data)
        except (KeyError, ValueError, TypeError, OSError) as error:
            summary['damaged'].append({**{k: e.get(k) for k in ('run_id', 'kind', 'name', 'sha256')}, 'error': str(error)})
            continue
        record = {**{k: e.get(k) for k in ('run_id', 'kind', 'name', 'sha256', 'bytes')}, 'path': str(target)}
        (summary['parts'] if 'part' in e else summary['written']).append({**record, **part_metadata})
    summary['stored_only'] = [e for e in events if e.get('event') in ('ARTIFACT_STORED', 'HTMLVIZ_PART_DEFERRED', 'PART_DEFERRED')]
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('collect', help='reassemble and verify artifacts from a saved Pod log')
    c.add_argument('--log', required=True, type=Path)
    c.add_argument('--out', required=True, type=Path)
    c.add_argument('--json', type=Path, help='write the summary here')
    a = ap.parse_args(argv)
    summary = collect(a.log.read_text(errors='replace'), a.out)
    text = json.dumps(summary, indent=1)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(text + '\n')
    print(json.dumps({k: len(v) for k, v in summary.items()}))
    return 1 if summary['damaged'] else 0


if __name__ == '__main__':
    sys.exit(main())
