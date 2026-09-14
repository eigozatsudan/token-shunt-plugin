"""Substitute fixture paths without changing catalog shell quoting or operators."""
import shlex
import sys


def render(command, fixture):
    output = []
    quote = None
    i = 0
    while i < len(command):
        if command.startswith('@FIX@', i):
            if quote == "'":
                value = fixture.replace("'", "'\"'\"'")
            elif quote == '"':
                value = ''.join('\\' + c if c in '\\"$`' else c for c in fixture)
            else:
                value = shlex.quote(fixture)
            output.append(value)
            i += 5
            continue
        char = command[i]
        output.append(char)
        if char == '\\' and quote != "'" and i + 1 < len(command):
            i += 1
            output.append(command[i])
        elif char in "'\"":
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        i += 1
    return ''.join(output)


if __name__ == '__main__':
    print(render(*sys.argv[1:]))
