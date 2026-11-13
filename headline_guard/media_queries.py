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
# Discrete features: (the desktop screen's value, every valid value). A value outside the list
# makes Chrome drop the whole query, even under 'not'.
DISCRETE_FEATURES = {
    "orientation": ("landscape", ("portrait", "landscape")),
    "prefers-color-scheme": ("light", ("light", "dark")),
    "prefers-reduced-motion": ("no-preference", ("no-preference", "reduce")),
    "prefers-reduced-transparency": ("no-preference", ("no-preference", "reduce")),
    "prefers-contrast": ("no-preference", ("no-preference", "more", "less", "custom")),
    "forced-colors": ("none", ("none", "active")),
    "inverted-colors": ("none", ("none", "inverted")),
    "scripting": ("enabled", ("none", "initial-only", "enabled")),
    "hover": ("hover", ("none", "hover")),
    "any-hover": ("hover", ("none", "hover")),
    "pointer": ("fine", ("none", "coarse", "fine")),
    "any-pointer": ("fine", ("none", "coarse", "fine")),
    "update": ("fast", ("none", "slow", "fast")),
    "overflow-block": ("scroll", ("none", "scroll", "paged")),
    "overflow-inline": ("scroll", ("none", "scroll")),
    "color-gamut": ("srgb", ("srgb", "p3", "rec2020")),
    "dynamic-range": ("standard", ("standard", "high")),
    "video-dynamic-range": ("standard", ("standard", "high")),
    "display-mode": ("browser", ("fullscreen", "standalone", "minimal-ui", "browser", "picture-in-picture",
                                 "window-controls-overlay")),
    "grid": ("0", ("0", "1")),
}
SCREEN_MEDIA_TYPES = ("all", "screen")
# CSS white space and case folding are ASCII only: a no-break space is not a separator, and a
# KELVIN SIGN does not become 'k' (Python's \s and str.lower() would do both).
CSS_WHITE_SPACE = " \t\n\r\f"
_ASCII_LOWERCASE = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_COMPARISON = re.compile(r"[ \t\n\r\f]*(<=|>=|<|>|=)[ \t\n\r\f]*")
# A keyword must be followed by white space: 'and(' is a function in CSS, and makes the query invalid.
_KEYWORD = re.compile(r"(and|or|not)[ \t\n\r\f]+")
_NOT_GROUP = re.compile(r"not[ \t\n\r\f]+\(")
_WHITE_SPACE = re.compile(r"[ \t\n\r\f]*")
_MEDIA_TYPE_QUERY = re.compile(
    r"(?:(not|only)[ \t\n\r\f]+)?([a-z-]+)(?:[ \t\n\r\f]+and[ \t\n\r\f]+(.+))?", flags=re.S
)
_RESOLUTION = re.compile(r"(\d*\.?\d+)(dppx|x|dpi|dpcm)")


class _Unparsable(Exception):
    pass


def media_query_applies(media_text):
    """True when a media query list (an @media prelude or a media attribute) matches the screen."""
    media_text = (media_text or "").translate(_ASCII_LOWERCASE).strip(CSS_WHITE_SPACE)
    if not media_text:
        return True
    for query in _split_top_level(media_text, ","):
        try:
            if _query_matches(query.strip(CSS_WHITE_SPACE)) is True:
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
            depth = max(0, depth - 1)  # a stray ')' spoils only its own query, as in Chrome
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
    if query.startswith("(") or _NOT_GROUP.match(query):
        return _condition_matches(query)
    match = _MEDIA_TYPE_QUERY.fullmatch(query)
    if match is None:
        raise _Unparsable(query)
    modifier, media_type, condition = match.groups()
    matches = media_type in SCREEN_MEDIA_TYPES
    if condition is not None:
        matches = _both(matches, _condition_matches(condition))
    if modifier == "not":
        matches = _negated(matches)
    return matches


class _Condition:
    """One parenthesized level of a condition while it is read: '(a) and (b)', 'not (a)'."""

    def __init__(self):
        self.value = None
        self.has_value = False
        self.operator = None
        self.operator_pending = False
        self.negate_next = False
        self.negated = False

    def add(self, value):
        if self.negate_next:
            value = _negated(value)
            self.negate_next = False
            self.negated = True
        if not self.has_value:
            self.value = value
        elif self.operator == "and":
            self.value = _both(self.value, value)
        else:
            self.value = _either(self.value, value)
        self.has_value = True
        self.operator_pending = False

    def expects_operand(self):
        return not self.has_value or self.operator_pending

    def result(self):
        if self.expects_operand():
            raise _Unparsable("condition ends without an operand")
        return self.value


def _condition_matches(text):
    """Reads a condition left to right with an explicit stack, so any nesting depth works (Chrome
    has no limit). An unclosed '(' closes at the end of the text, as in Chrome."""
    stack = [_Condition()]
    position = _WHITE_SPACE.match(text, 0).end()
    length = len(text)
    while position < length:
        current = stack[-1]
        if current.expects_operand():
            if text[position] == "(":
                position = _WHITE_SPACE.match(text, position + 1).end()
                if position < length and (text[position] == "(" or _NOT_GROUP.match(text, position)):
                    stack.append(_Condition())
                else:
                    feature_end = _closing_parenthesis(text, position)
                    current.add(_feature_matches(text[position:feature_end]))
                    position = feature_end + 1
            else:
                keyword = _KEYWORD.match(text, position)
                if keyword is None or keyword.group(1) != "not" or current.has_value or current.negate_next:
                    raise _Unparsable(text)
                current.negate_next = True
                position = keyword.end()
        elif text[position] == ")":
            if len(stack) == 1:
                raise _Unparsable(text)
            finished = stack.pop()
            stack[-1].add(finished.result())
            position += 1
        else:
            keyword = _KEYWORD.match(text, position)
            if keyword is None or keyword.group(1) == "not" or current.negated:
                raise _Unparsable(text)
            if current.operator not in (None, keyword.group(1)):
                raise _Unparsable(text)  # 'and' and 'or' mixed without parentheses
            current.operator = keyword.group(1)
            current.operator_pending = True
            position = keyword.end()
        position = _WHITE_SPACE.match(text, position).end()
    while len(stack) > 1:
        finished = stack.pop()
        stack[-1].add(finished.result())
    return stack[0].result()


def _closing_parenthesis(text, start):
    """The position of the ')' that closes a feature starting at start (its value may hold
    calc(...)), or the end of the text when it is never closed."""
    depth = 1
    position = start
    while position < len(text):
        if text[position] == "(":
            depth += 1
        elif text[position] == ")":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    return len(text)


def _feature_matches(content):
    """True, False, or None for a feature this reader (and so Chrome, for unknown names) cannot judge."""
    if _COMPARISON.search(content) and ":" not in content:
        return _range_matches(content)
    if ":" in content:
        name, value = content.split(":", 1)
        return _plain_feature_matches(name.strip(CSS_WHITE_SPACE), value.strip(CSS_WHITE_SPACE))
    name = content.strip(CSS_WHITE_SPACE)
    if name in RANGE_FEATURES:
        return RANGE_FEATURES[name][1] != 0
    if name in DISCRETE_FEATURES:
        return DISCRETE_FEATURES[name][0] not in ("none", "no-preference", "0")
    return None


def _plain_feature_matches(name, value):
    if name in DISCRETE_FEATURES:
        screen_value, valid_values = DISCRETE_FEATURES[name]
        if value not in valid_values:
            raise _Unparsable(value)
        return value == screen_value
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
    parts = _COMPARISON.split(content.strip(CSS_WHITE_SPACE))
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
        both_rising = first_operator in ("<", "<=") and second_operator in ("<", "<=")
        both_falling = first_operator in (">", ">=") and second_operator in (">", ">=")
        if not both_rising and not both_falling:
            raise _Unparsable(content)
        return _both(_compare_with_screen(name, _flipped(first_operator), low),
                     _compare_with_screen(name, second_operator, high))
    raise _Unparsable(content)


def _flipped(operator):
    return {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "=": "="}[operator]


def _compare_with_screen(name, operator, value_text):
    """The screen's value of a range feature compared with value_text: screen OPERATOR value."""
    kind, screen_value = RANGE_FEATURES[name]
    value = _range_value(kind, value_text.strip(CSS_WHITE_SPACE))
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
    if not text.isascii():
        return None  # every valid value is ASCII; Python's parsers would accept a no-break space
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
