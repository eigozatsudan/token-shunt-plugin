"""Presentation normalization for explicit evidence fields, never inferred values."""
import re


def plain_report(text):
    lines = []
    for line in (text or '').splitlines():
        line = line.strip()
        line = re.sub(r'^[-*+]\s+', '', line)
        # Only unwrap whole-line markup or markup around a field label/value.
        for marker in ('**', '__', '`'):
            if line.startswith(marker) and line.endswith(marker):
                line = line[len(marker):-len(marker)].strip()
        line = re.sub(r'^[-*+]\s+', '', line)
        line = re.sub(r'^(status|stop_reason|fallback_reason|retry_reason):\s*[`*_]+([^`*_]+)[`*_]+$',
                      r'\1: \2', line)
        lines.append(line)
    return '\n'.join(lines)
