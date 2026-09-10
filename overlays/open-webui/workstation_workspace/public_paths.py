"""Hide execution paths before they enter public chat history, including split SSE tokens."""
import copy
import re


WORKSPACE = re.compile(r'(?<![\w:/])/workspace(?:/|(?=$|[\s`"\']))')
INTERNAL = re.compile(r'''(?<![\w:/])/(?:home|app|opt|state|tmp|root|proc|var|etc|usr)(?:/[^\s`"'<>)]*)?(?=$|[\s`"'<>),])''')
FILE_URI = re.compile(r'''(?<![\w])file://(?:localhost)?/(?:workspace|home|app|opt|state|tmp|root|proc|var|etc|usr)(?:/[^\s`"'<>)]*)?(?=$|[\s`"'<>),])''', re.IGNORECASE)


def clean_text(text):
    text = FILE_URI.sub('[内部路径]', text)
    text = WORKSPACE.sub('', text)
    return INTERNAL.sub('[内部路径]', text)


def clean_object(value):
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [clean_object(v) for v in value]
    if isinstance(value, dict):
        return {k: clean_object(v) for k, v in value.items()}
    return value


class PublicDeltaFilter:
    def __init__(self):
        self.pending = {}
        self.word_context = {}

    def transform(self, data):
        result = copy.deepcopy(data)
        for choice in result.get('choices', []):
            for field in ('content', 'reasoning_content', 'reasoning', 'thinking'):
                delta = choice.get('delta', {})
                value = delta.get(field)
                if not isinstance(value, str):
                    continue
                key = (choice.get('index', 0), field)
                sentinel = 'a' if self.word_context.get(key) else '\n'
                combined = sentinel + self.pending.get(key, '') + value
                # Preserve a possibly split absolute path until a delimiter.
                # Ordinary text streams immediately unless its suffix could be
                # a path; a malformed extremely long path is redacted as a unit.
                # Also retain a partial file:// scheme; otherwise a split just
                # before its slash could emit the scheme before path filtering.
                match = re.search(r'''(?<![\w:/])/(?:[^\s`"'<>)]*)$|(?<!\w)(?:f|fi|fil|file|file:|file:/|file://[^\s`"'<>)]*)$''', combined, re.IGNORECASE)
                if match and not choice.get('finish_reason'):
                    prefix, suffix = combined[:match.start()], combined[match.start():]
                    if len(prefix) > 1:
                        self.word_context[key] = bool(re.match(r'[\w:/]', prefix[-1]))
                    if len(suffix) > 4096:
                        self.pending[key] = ''
                        delta[field] = clean_text(prefix)[1:] + '[过长路径已省略]'
                    else:
                        self.pending[key] = suffix
                        delta[field] = clean_text(prefix)[1:]
                else:
                    self.pending[key] = ''
                    delta[field] = clean_text(combined)[1:]
                    if len(combined) > 1:
                        self.word_context[key] = bool(re.match(r'[\w:/]', combined[-1]))
        return result

    def flush(self):
        choices = {}
        for (index, field), value in self.pending.items():
            if value:
                sentinel = 'a' if self.word_context.get((index, field)) else '\n'
                choices.setdefault(index, {})[field] = clean_text(sentinel + value)[1:]
        self.pending.clear()
        return {'choices': [{'index': index, 'delta': delta} for index, delta in choices.items()]} if choices else None
