"""Media queries answered as the verifying Chrome answers them (Media Queries level 4).

The screen is the browser check's: a 1366 x 900 desktop window in light mode, pixel ratio 1,
scripting on, no reduced motion, contrast or forced colors. Like Chrome, a query that uses a
feature it does not know, or that does not parse, matches nothing.
"""

import re

from .css_values import VIEWPORT_HEIGHT_PIXELS, VIEWPORT_WIDTH_PIXELS, length_in_pixels

# Range features: (kind of value, the desktop screen's value).
RANGE_FEATURES = {
    "width": ("length", VIEWPORT_WIDTH_PIXELS),
    "height": ("length", VIEWPORT_HEIGHT_PIXELS),
    "device-width": ("length", VIEWPORT_WIDTH_PIXELS),
    "device-height": ("length", VIEWPORT_HEIGHT_PIXELS),
    "aspect-ratio": ("ratio", VIEWPORT_WIDTH_PIXELS / VIEWPORT_HEIGHT_PIXELS),
    "device-aspect-ratio": ("ratio", VIEWPORT_WIDTH_PIXELS / VIEWPORT_HEIGHT_PIXELS),
    "resolution": ("resolution", 1.0),
    "-webkit-device-pixel-ratio": ("number", 1.0),
    "color": ("number", 8.0),
    "color-index": ("number", 0.0),
    "monochrome": ("number", 0.0),
}
# Discrete features: the desktop screen's value.
DISCRETE_FEATURES = {
    "orientation": "landscape",
    "prefers-color-scheme": "light",
    "prefers-reduced-motion": "no-preference",
    "prefers-reduced-transparency": "no-preference",
    "prefers-contrast": "no-preference",
    "forced-colors": "none",
    "inverted-colors": "none",
    "scripting": "enabled",
    "hover": "hover",
    "any-hover": "hover",
    "pointer": "fine",
    "any-pointer": "fine",
    "update": "fast",
    "overflow-block": "scroll",
    "overflow-inline": "scroll",
    "color-gamut": "srgb",
    "dynamic-range": "standard",
    "video-dynamic-range": "standard",
    "display-mode": "browser",
    "grid": "0",
}
SCREEN_MEDIA_TYPES = ("all", "screen")
_COMPARISON = re.compile(r"\s*(<=|>=|<|>|=)\s*")
_RESOLUTION = re.compile(r"(\d*\.?\d+)(dppx|x|dpi|dpcm)")


class _Unparsable(Exception):
    pass


def media_query_applies(media_text):
    """True when a media query list (an @media prelude or a media attribute) matches the screen."""
    media_text = (media_text or "").strip().lower()
    if not media_text:
        return True
    for query in _split_top_level(media_text, ","):
        try:
            if _query_matches(query.strip()) is True:
                return True
        except _Unparsable:
            continue
    return False


def _split_top_level(text, separator):
    parts = []
    depth = 0
    start = 0
    for position, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == separator and depth == 0:
            parts.append(text[start:position])
            start = position + 1
    parts.append(text[start:])
    return parts


def _both(first, second):
    """Three-valued 'and': None means unknown."""
    if first is False or second is False:
        return False
    if first is None or second is None:
        return None
    return True


def _either(first, second):
    """Three-valued 'or': None means unknown."""
    if first is True or second is True:
        return True
    if first is None or second is None:
        return None
    return False


def _negated(value):
    if value is None:
        return None
    return not value


def _query_matches(query):
    if query.startswith("(") or re.match(r"not\s*\(", query):
        return _condition_matches(query)
    match = re.fullmatch(r"(?:(not|only)\s+)?([a-z-]+)(?:\s+and\s+(.+))?", query, flags=re.S)
    if match is None:
        raise _Unparsable(query)
    modifier, media_type, condition = match.groups()
    matches = media_type in SCREEN_MEDIA_TYPES
    if condition is not None:
        matches = _both(matches, _condition_matches(condition))
    if modifier == "not":
        matches = _negated(matches)
    return matches


def _parenthesized_groups(text):
    """[(word before the group, group content)] for 'a (x) and (y)'-shaped text."""
    groups = []
    position = 0
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        word_match = re.match(r"([a-z]+)\s*", text[position:])
        word = ""
        if word_match is not None and text[position] != "(":
            word = word_match.group(1)
            position += word_match.end()
        if position >= len(text) or text[position] != "(":
            raise _Unparsable(text)
        depth = 0
        start = position
        while position < len(text):
            if text[position] == "(":
                depth += 1
            elif text[position] == ")":
                depth -= 1
                if depth == 0:
                    break
            position += 1
        if depth != 0:
            raise _Unparsable(text)
        groups.append((word, text[start + 1:position]))
        position += 1
    return groups


def _condition_matches(condition):
    groups = _parenthesized_groups(condition.strip())
    if not groups:
        raise _Unparsable(condition)
    first_word, first_content = groups[0]
    if first_word == "not":
        if len(groups) != 1:
            raise _Unparsable(condition)
        return _negated(_in_parentheses_matches(first_content))
    if first_word:
        raise _Unparsable(condition)
    combined = _in_parentheses_matches(first_content)
    joining_words = set()
    for word, content in groups[1:]:
        joining_words.add(word)
        if word == "and":
            combined = _both(combined, _in_parentheses_matches(content))
        elif word == "or":
            combined = _either(combined, _in_parentheses_matches(content))
        else:
            raise _Unparsable(condition)
    if len(joining_words) > 1:
        raise _Unparsable(condition)  # 'and' and 'or' mixed without parentheses
    return combined


def _in_parentheses_matches(content):
    content = content.strip()
    if content.startswith("(") or re.match(r"not\s*\(", content):
        return _condition_matches(content)
    return _feature_matches(content)


def _feature_matches(content):
    """True, False, or None for a feature this reader (and so Chrome, for unknown names) cannot judge."""
    if _COMPARISON.search(content) and ":" not in content:
        return _range_matches(content)
    if ":" in content:
        name, value = content.split(":", 1)
        return _plain_feature_matches(name.strip(), value.strip())
    name = content.strip()
    if name in RANGE_FEATURES:
        return RANGE_FEATURES[name][1] != 0
    if name in DISCRETE_FEATURES:
        return DISCRETE_FEATURES[name] not in ("none", "no-preference", "0")
    return None


def _plain_feature_matches(name, value):
    if name in DISCRETE_FEATURES:
        return value == DISCRETE_FEATURES[name]
    for prefix, comparison in (("min-", ">="), ("max-", "<=")):
        base_name = None
        if name.startswith(prefix):
            base_name = name[len(prefix):]
        elif name.startswith("-webkit-" + prefix):
            base_name = "-webkit-" + name[len("-webkit-" + prefix):]
        if base_name is not None:
            if base_name not in RANGE_FEATURES:
                return None
            return _compare_with_screen(base_name, comparison, value)
    if name in RANGE_FEATURES:
        return _compare_with_screen(name, "=", value)
    return None


def _range_matches(content):
    parts = _COMPARISON.split(content.strip())
    if len(parts) == 3:
        left, operator, right = parts
        if left in RANGE_FEATURES:
            return _compare_with_screen(left, operator, right)
        if right in RANGE_FEATURES:
            return _compare_with_screen(right, _flipped(operator), left)
        return None
    if len(parts) == 5:
        low, first_operator, name, second_operator, high = parts
        if name not in RANGE_FEATURES:
            return None
        return _both(_compare_with_screen(name, _flipped(first_operator), low),
                     _compare_with_screen(name, second_operator, high))
    raise _Unparsable(content)


def _flipped(operator):
    return {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "=": "="}[operator]


def _compare_with_screen(name, operator, value_text):
    """The screen's value of a range feature compared with value_text: screen OPERATOR value."""
    kind, screen_value = RANGE_FEATURES[name]
    value = _range_value(kind, value_text.strip())
    if value is None:
        raise _Unparsable(value_text)  # Chrome drops the whole query, even under 'not'
    if operator == "<":
        return screen_value < value
    if operator == ">":
        return screen_value > value
    if operator == "<=":
        return screen_value <= value
    if operator == ">=":
        return screen_value >= value
    return screen_value == value


def _range_value(kind, text):
    if kind == "length":
        return length_in_pixels(text)
    if kind == "ratio":
        parts = text.split("/")
        try:
            if len(parts) == 2:
                denominator = float(parts[1])
                return float(parts[0]) / denominator if denominator else None
            return float(text)
        except ValueError:
            return None
    if kind == "resolution":
        match = _RESOLUTION.fullmatch(text)
        if match is None:
            return None
        number = float(match.group(1))
        unit = match.group(2)
        if unit == "dpi":
            return number / 96
        if unit == "dpcm":
            return number * 2.54 / 96
        return number
    try:
        return float(text)
    except ValueError:
        return None
