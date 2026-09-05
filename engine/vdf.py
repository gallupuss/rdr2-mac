"""Valve KeyValues parser with source spans, preserving unrelated app settings."""
from dataclasses import dataclass
import re


@dataclass
class Entry:
    key: str
    value: object
    start: int
    end: int
    close: int = 0


def tokens(text):
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
        elif text.startswith('//', pos):
            end = text.find('\n', pos)
            pos = len(text) if end < 0 else end + 1
        elif text[pos] in '{}':
            yield text[pos], pos, pos + 1
            pos += 1
        elif text[pos] == '"':
            start = pos
            pos += 1
            value = ''
            while pos < len(text) and text[pos] != '"':
                if text[pos] == '\\' and pos + 1 < len(text) and text[pos + 1] in '\\"':
                    pos += 1
                value += text[pos]
                pos += 1
            if pos == len(text):
                raise ValueError('Unterminated KeyValues string')
            pos += 1
            yield value, start, pos
        else:
            match = re.match(r'[^\s{}"]+', text[pos:])
            if not match:
                raise ValueError('Invalid KeyValues token')
            end = pos + len(match[0])
            yield text[pos:end], pos, end
            pos = end


def parse(text):
    stream = iter(tokens(text))
    def block(nested=False, depth=0):
        if depth > 32:
            raise ValueError('KeyValues nesting limit exceeded')
        entries = []
        for key, start, end in stream:
            if text[start:end] == '}':
                if not nested:
                    raise ValueError('Unexpected KeyValues brace')
                return entries, start
            if text[start:end] == '{':
                raise ValueError('Missing KeyValues key')
            try:
                value, vs, ve = next(stream)
            except StopIteration:
                raise ValueError('Missing KeyValues value') from None
            if text[vs:ve] == '{':
                children, close = block(True, depth + 1)
                entries.append(Entry(key, children, vs, close + 1, close))
            elif text[vs:ve] == '}':
                raise ValueError('Missing KeyValues value')
            else:
                entries.append(Entry(key, value, vs, ve))
        if nested:
            raise ValueError('Unclosed KeyValues object')
        return entries, len(text)
    return block()[0]


def get(entries, key):
    matches = [e for e in entries if e.key.casefold() == key.casefold()]
    if len(matches) > 1:
        raise ValueError('Ambiguous duplicate KeyValues key')
    return matches[0] if matches else None


def at(entries, *keys):
    entry = None
    for key in keys:
        entry = get(entries, key)
        if entry is None:
            return None
        entries = entry.value if isinstance(entry.value, list) else []
    return entry


def quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def launch_options(text, dimensions=None):
    root = parse(text)
    app = at(root, 'UserLocalConfigStore', 'Software', 'Valve', 'Steam', 'apps', '1174180')
    if app is None or not isinstance(app.value, list):
        return None
    entry = get(app.value, 'LaunchOptions')
    if entry and not isinstance(entry.value, str):
        raise ValueError('Invalid launch options')
    options = entry.value if entry else ''
    options = re.sub(r'(?i)(?<!\S)-sgadriver(?:=|\s+)\S+', '', options)
    if dimensions:
        options = re.sub(r'(?i)(?<!\S)-(?:width|height)(?:=|\s+)\d+(?=\s|$)', '', options)
    options = options.strip() + ' -sgadriver=d3d12'
    if dimensions:
        options += f' -width {dimensions[0]} -height {dimensions[1]}'
    options = options.strip()
    if entry:
        return text[:entry.start] + quote(options) + text[entry.end:]
    return text[:app.close] + '\n\t\t"LaunchOptions" ' + quote(options) + '\n' + text[app.close:]
