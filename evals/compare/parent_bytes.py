#!/usr/bin/env python3
"""Bytes of file body that reached the parent's own context.

`parent_added_utf8_bytes` (judge.py) counts the text the parent wrote and
received, which is what the isolation check needs and not what "the body
entered the parent's context" means. Choosing it as the primary metric cost
a measurement (reviews/redmine-effect-aborted-2026-09-17.md section 3).

This counts one thing: what a Read returned to the parent itself. A Read
issued inside a subagent carries `parent_tool_use_id`, and is exactly the
body the product exists to keep out, so it is not counted.

Not part of the release gate.
"""
import json
import os
import sys


def _text(content):
    """The result payload as text, whether a string or content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(b.get('text', '') for b in content
                       if isinstance(b, dict) and isinstance(b.get('text'), str))
    return ''


def parent_read_bytes(transcript, root=None):
    """UTF-8 bytes returned by Reads the parent itself issued.

    `root` restricts the count to paths under one directory: a run also
    reads the plugin's own files, which are not the corpus under test.
    """
    reads, total = {}, 0
    try:
        source = open(transcript, encoding='utf-8', errors='replace')
    except OSError:
        return 0
    with source:
        for line in source:
            try:
                row = json.loads(line)
            except ValueError:
                # A truncated transcript still has to yield a number.
                continue
            if not isinstance(row, dict) or row.get('parent_tool_use_id') is not None:
                continue
            content = ((row.get('message') or {}).get('content')
                       if isinstance(row.get('message'), dict) else None)
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'tool_use' and block.get('name') == 'Read':
                    path = (block.get('input') or {}).get('file_path')
                    if isinstance(path, str) and path:
                        reads[block.get('id')] = path
                elif block.get('type') == 'tool_result':
                    path = reads.get(block.get('tool_use_id'))
                    if path is None:
                        continue
                    if root is not None and not os.path.abspath(path).startswith(
                            os.path.abspath(root) + os.sep):
                        continue
                    total += len(_text(block.get('content')).encode('utf-8'))
    return total


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    if argv and argv[0] == '--root':
        if len(argv) < 2:
            print('usage: parent_bytes.py [--root DIR] <transcript.jsonl> [...]',
                  file=sys.stderr)
            return 2
        root, argv = argv[1], argv[2:]
    if not argv:
        print('usage: parent_bytes.py [--root DIR] <transcript.jsonl> [...]',
              file=sys.stderr)
        return 2
    for path in argv:
        print('%d\t%s' % (parent_read_bytes(path, root), path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
