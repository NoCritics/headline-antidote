"""CSS value parsing for the visibility check: colors in every common syntax, and lengths,
including calc(), min(), max() and clamp() expressions.

Pure Python, no dependencies. Values the parser cannot evaluate return None, and the
callers treat None as "not hidden", so an unknown value never removes text.
"""

import functools
import math
import re

VIEWPORT_WIDTH_PIXELS = 1366
VIEWPORT_HEIGHT_PIXELS = 900
PIXELS_PER_EM = 16

PIXELS_PER_UNIT = {
    "px": 1.0,
    "em": PIXELS_PER_EM,
    "rem": PIXELS_PER_EM,
    "ex": PIXELS_PER_EM / 2,
    "ch": PIXELS_PER_EM / 2,
    "cap": PIXELS_PER_EM * 0.7,
    "lh": PIXELS_PER_EM * 1.2,
    "pt": 96 / 72,
    "pc": 16.0,
    "in": 96.0,
    "cm": 96 / 2.54,
    "mm": 96 / 25.4,
    "q": 96 / 101.6,
    "vw": VIEWPORT_WIDTH_PIXELS / 100,
    "vh": VIEWPORT_HEIGHT_PIXELS / 100,
    "svw": VIEWPORT_WIDTH_PIXELS / 100,
    "svh": VIEWPORT_HEIGHT_PIXELS / 100,
    "lvw": VIEWPORT_WIDTH_PIXELS / 100,
    "lvh": VIEWPORT_HEIGHT_PIXELS / 100,
    "dvw": VIEWPORT_WIDTH_PIXELS / 100,
    "dvh": VIEWPORT_HEIGHT_PIXELS / 100,
    "vmin": VIEWPORT_HEIGHT_PIXELS / 100,
    "vmax": VIEWPORT_WIDTH_PIXELS / 100,
}

# The CSS named colors (CSS Color Module Level 4).
NAMED_COLORS = {
    "aliceblue": (240, 248, 255), "antiquewhite": (250, 235, 215), "aqua": (0, 255, 255),
    "aquamarine": (127, 255, 212), "azure": (240, 255, 255), "beige": (245, 245, 220),
    "bisque": (255, 228, 196), "black": (0, 0, 0), "blanchedalmond": (255, 235, 205),
    "blue": (0, 0, 255), "blueviolet": (138, 43, 226), "brown": (165, 42, 42),
    "burlywood": (222, 184, 135), "cadetblue": (95, 158, 160), "chartreuse": (127, 255, 0),
    "chocolate": (210, 105, 30), "coral": (255, 127, 80), "cornflowerblue": (100, 149, 237),
    "cornsilk": (255, 248, 220), "crimson": (220, 20, 60), "cyan": (0, 255, 255),
    "darkblue": (0, 0, 139), "darkcyan": (0, 139, 139), "darkgoldenrod": (184, 134, 11),
    "darkgray": (169, 169, 169), "darkgreen": (0, 100, 0), "darkgrey": (169, 169, 169),
    "darkkhaki": (189, 183, 107), "darkmagenta": (139, 0, 139), "darkolivegreen": (85, 107, 47),
    "darkorange": (255, 140, 0), "darkorchid": (153, 50, 204), "darkred": (139, 0, 0),
    "darksalmon": (233, 150, 122), "darkseagreen": (143, 188, 143), "darkslateblue": (72, 61, 139),
    "darkslategray": (47, 79, 79), "darkslategrey": (47, 79, 79), "darkturquoise": (0, 206, 209),
    "darkviolet": (148, 0, 211), "deeppink": (255, 20, 147), "deepskyblue": (0, 191, 255),
    "dimgray": (105, 105, 105), "dimgrey": (105, 105, 105), "dodgerblue": (30, 144, 255),
    "firebrick": (178, 34, 34), "floralwhite": (255, 250, 240), "forestgreen": (34, 139, 34),
    "fuchsia": (255, 0, 255), "gainsboro": (220, 220, 220), "ghostwhite": (248, 248, 255),
    "gold": (255, 215, 0), "goldenrod": (218, 165, 32), "gray": (128, 128, 128),
    "green": (0, 128, 0), "greenyellow": (173, 255, 47), "grey": (128, 128, 128),
    "honeydew": (240, 255, 240), "hotpink": (255, 105, 180), "indianred": (205, 92, 92),
    "indigo": (75, 0, 130), "ivory": (255, 255, 240), "khaki": (240, 230, 140),
    "lavender": (230, 230, 250), "lavenderblush": (255, 240, 245), "lawngreen": (124, 252, 0),
    "lemonchiffon": (255, 250, 205), "lightblue": (173, 216, 230), "lightcoral": (240, 128, 128),
    "lightcyan": (224, 255, 255), "lightgoldenrodyellow": (250, 250, 210), "lightgray": (211, 211, 211),
    "lightgreen": (144, 238, 144), "lightgrey": (211, 211, 211), "lightpink": (255, 182, 193),
    "lightsalmon": (255, 160, 122), "lightseagreen": (32, 178, 170), "lightskyblue": (135, 206, 250),
    "lightslategray": (119, 136, 153), "lightslategrey": (119, 136, 153), "lightsteelblue": (176, 196, 222),
    "lightyellow": (255, 255, 224), "lime": (0, 255, 0), "limegreen": (50, 205, 50),
    "linen": (250, 240, 230), "magenta": (255, 0, 255), "maroon": (128, 0, 0),
    "mediumaquamarine": (102, 205, 170), "mediumblue": (0, 0, 205), "mediumorchid": (186, 85, 211),
    "mediumpurple": (147, 112, 219), "mediumseagreen": (60, 179, 113), "mediumslateblue": (123, 104, 238),
    "mediumspringgreen": (0, 250, 154), "mediumturquoise": (72, 209, 204), "mediumvioletred": (199, 21, 133),
    "midnightblue": (25, 25, 112), "mintcream": (245, 255, 250), "mistyrose": (255, 228, 225),
    "moccasin": (255, 228, 181), "navajowhite": (255, 222, 173), "navy": (0, 0, 128),
    "oldlace": (253, 245, 230), "olive": (128, 128, 0), "olivedrab": (107, 142, 35),
    "orange": (255, 165, 0), "orangered": (255, 69, 0), "orchid": (218, 112, 214),
    "palegoldenrod": (238, 232, 170), "palegreen": (152, 251, 152), "paleturquoise": (175, 238, 238),
    "palevioletred": (219, 112, 147), "papayawhip": (255, 239, 213), "peachpuff": (255, 218, 185),
    "peru": (205, 133, 63), "pink": (255, 192, 203), "plum": (221, 160, 221),
    "powderblue": (176, 224, 230), "purple": (128, 0, 128), "rebeccapurple": (102, 51, 153),
    "red": (255, 0, 0), "rosybrown": (188, 143, 143), "royalblue": (65, 105, 225),
    "saddlebrown": (139, 69, 19), "salmon": (250, 128, 114), "sandybrown": (244, 164, 96),
    "seagreen": (46, 139, 87), "seashell": (255, 245, 238), "sienna": (160, 82, 45),
    "silver": (192, 192, 192), "skyblue": (135, 206, 235), "slateblue": (106, 90, 205),
    "slategray": (112, 128, 144), "slategrey": (112, 128, 144), "snow": (255, 250, 250),
    "springgreen": (0, 255, 127), "steelblue": (70, 130, 180), "tan": (210, 180, 140),
    "teal": (0, 128, 128), "thistle": (216, 191, 216), "tomato": (255, 99, 71),
    "turquoise": (64, 224, 208), "violet": (238, 130, 238), "wheat": (245, 222, 179),
    "white": (255, 255, 255), "whitesmoke": (245, 245, 245), "yellow": (255, 255, 0),
    "yellowgreen": (154, 205, 50),
}

_COLOR_FUNCTION = re.compile(r"(rgba?|hsla?|hwb|oklch|oklab|lch|lab)\((.*)\)")


def _component(text, percent_scale, default=None):
    """A color component: a number, or a percentage of percent_scale. 'none' is 0."""
    if text == "none":
        return 0.0
    try:
        if text.endswith("%"):
            return float(text[:-1]) / 100 * percent_scale
        for suffix in ("deg", "turn", "rad", "grad"):
            if text.endswith(suffix):
                number = float(text[:-len(suffix)])
                if suffix == "turn":
                    return number * 360
                if suffix == "rad":
                    return math.degrees(number)
                if suffix == "grad":
                    return number * 0.9
                return number
        return float(text)
    except ValueError:
        return default


def _hsl_to_rgb(hue, saturation, lightness):
    hue = (hue % 360) / 360
    if saturation == 0:
        return (lightness, lightness, lightness)

    def channel(offset):
        k = (offset + hue * 12) % 12
        amount = saturation * min(lightness, 1 - lightness)
        return lightness - amount * max(-1, min(k - 3, 9 - k, 1))
    return (channel(0), channel(8), channel(4))


def _oklab_to_rgb(lightness, a, b):
    l_root = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_root = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_root = lightness - 0.0894841775 * a - 1.2914855480 * b
    l_value = l_root ** 3
    m_value = m_root ** 3
    s_value = s_root ** 3
    linear = (
        4.0767416621 * l_value - 3.3077115913 * m_value + 0.2309699292 * s_value,
        -1.2684380046 * l_value + 2.6097574011 * m_value - 0.3413193965 * s_value,
        -0.0041960863 * l_value - 0.7034186147 * m_value + 1.7076147010 * s_value,
    )
    encoded = []
    for channel in linear:
        channel = max(0.0, min(1.0, channel))
        if channel <= 0.0031308:
            encoded.append(12.92 * channel)
        else:
            encoded.append(1.055 * channel ** (1 / 2.4) - 0.055)
    return tuple(encoded)


def parse_color(value):
    """(red, green, blue, alpha) with channels 0-255 and alpha 0-1, or None when unknown.

    Understands names, #rgb/#rgba/#rrggbb/#rrggbbaa, rgb()/rgba() and hsl()/hsla() in the
    comma and the modern space syntax, hwb(), oklab() and oklch(). For lab() and lch()
    only the lightness and alpha are used (as a gray), which is enough for contrast.
    """
    if not value:
        return None
    color = value.strip().lower()
    if color == "transparent":
        return (0, 0, 0, 0.0)
    if color in NAMED_COLORS:
        red, green, blue = NAMED_COLORS[color]
        return (red, green, blue, 1.0)
    hex_match = re.fullmatch(r"#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})", color)
    if hex_match:
        digits = hex_match.group(1)
        if len(digits) <= 4:
            expanded_digits = []
            for digit in digits:
                expanded_digits.append(digit * 2)
            digits = "".join(expanded_digits)
        alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), alpha)

    function_match = _COLOR_FUNCTION.fullmatch(color)
    if function_match is None:
        return None
    function_name = function_match.group(1)
    arguments = function_match.group(2)
    if "(" in arguments:
        return None  # calc(), var() or relative colors: not evaluated
    parts = []
    for part in re.split(r"[\s,/]+", arguments.strip()):
        if part:
            parts.append(part)
    if len(parts) < 3:
        return None
    alpha = 1.0
    if len(parts) >= 4:
        alpha = _component(parts[3], 1.0)
        if alpha is None:
            return None
        alpha = max(0.0, min(1.0, alpha))

    if function_name.startswith("rgb"):
        channels = []
        for part in parts[:3]:
            channel = _component(part, 255.0)
            if channel is None:
                return None
            channels.append(channel)
        fractions = (channels[0] / 255, channels[1] / 255, channels[2] / 255)
    elif function_name.startswith("hsl"):
        hue = _component(parts[0], 360.0)
        saturation = _component(parts[1], 1.0)
        lightness = _component(parts[2], 1.0)
        if hue is None or saturation is None or lightness is None:
            return None
        if not parts[1].endswith("%"):
            saturation = saturation / 100
        if not parts[2].endswith("%"):
            lightness = lightness / 100
        fractions = _hsl_to_rgb(hue, max(0.0, min(1.0, saturation)), max(0.0, min(1.0, lightness)))
    elif function_name == "hwb":
        hue = _component(parts[0], 360.0)
        whiteness = _component(parts[1], 1.0)
        blackness = _component(parts[2], 1.0)
        if hue is None or whiteness is None or blackness is None:
            return None
        if whiteness + blackness >= 1:
            gray = whiteness / (whiteness + blackness)
            fractions = (gray, gray, gray)
        else:
            pure = _hsl_to_rgb(hue, 1.0, 0.5)
            fractions = []
            for channel in pure:
                fractions.append(channel * (1 - whiteness - blackness) + whiteness)
            fractions = tuple(fractions)
    elif function_name in ("oklab", "oklch"):
        lightness = _component(parts[0], 1.0)
        if lightness is None:
            return None
        if function_name == "oklab":
            a = _component(parts[1], 0.4)
            b = _component(parts[2], 0.4)
        else:
            chroma = _component(parts[1], 0.4)
            hue = _component(parts[2], 360.0)
            if chroma is None or hue is None:
                return None
            a = chroma * math.cos(math.radians(hue))
            b = chroma * math.sin(math.radians(hue))
        if a is None or b is None:
            return None
        fractions = _oklab_to_rgb(lightness, a, b)
    else:  # lab(), lch(): CIE lightness 0-100, used as a gray
        lightness = _component(parts[0], 100.0)
        if lightness is None:
            return None
        lightness = max(0.0, min(100.0, lightness))
        linear = ((lightness + 16) / 116) ** 3 if lightness > 8 else lightness / 903.3
        if linear <= 0.0031308:
            gray = 12.92 * linear
        else:
            gray = 1.055 * linear ** (1 / 2.4) - 0.055
        fractions = (gray, gray, gray)

    channels = []
    for fraction in fractions:
        channels.append(int(round(max(0.0, min(1.0, fraction)) * 255)))
    return (channels[0], channels[1], channels[2], alpha)


_QUOTED_TEXT = re.compile(r'"((?:[^"\\]|\\.)*)"' + r"|'((?:[^'\\]|\\.)*)'")


def quoted_strings(value):
    """The quoted strings in a CSS value, such as content: "Breaking: " attr(x)."""
    strings = []
    for double_quoted, single_quoted in _QUOTED_TEXT.findall(value or ""):
        strings.append(double_quoted or single_quoted)
    return strings


# ---- numbers and lengths -------------------------------------------------

# Chrome drops a declaration whose math functions and the parentheses inside them nest deeper than
# this (measured in Chrome 157); stopping there also keeps the recursive parser off the call-stack limit.
MAXIMUM_MATH_DEPTH = 100
# Chrome clamps an infinite length to this many pixels (measured: calc(-infinity * 1px) is -3.35544e+07px).
LARGEST_LENGTH_PIXELS = 33554400.0
MATH_FUNCTIONS = (
    "calc", "min", "max", "clamp", "abs", "sign", "round", "mod", "rem", "sin", "cos", "tan", "asin", "acos",
    "atan", "atan2", "pow", "sqrt", "hypot", "log", "exp", "progress",
)
_TOKEN = re.compile(
    r"\s*(?:([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)([a-z%]*)|([a-z][a-z0-9-]*)\(|(-?[a-z][a-z-]*)|([-+*/(),]))"
)
_CONSTANTS = {"e": math.e, "pi": math.pi, "infinity": math.inf, "-infinity": -math.inf, "nan": math.nan}
DEGREES_PER_UNIT = {"deg": 1.0, "grad": 0.9, "rad": 180 / math.pi, "turn": 360.0}
_ROUNDING_STRATEGIES = ("nearest", "up", "down", "to-zero")
# Kinds whose values compare and add with each other. 'mixed' is a percentage plus a length; its
# number is the pair (pixels, percent).
_LENGTH_KINDS = ("length", "percent", "mixed")


def _divided(dividend, divisor):
    """dividend / divisor as CSS computes it: dividing by zero gives an infinity (or NaN for 0/0)."""
    if divisor == 0:
        if dividend == 0 or math.isnan(dividend):
            return math.nan
        return math.copysign(math.inf, dividend) * math.copysign(1.0, divisor)
    return dividend / divisor


def _pixels_and_percent(number, kind):
    if kind == "length":
        return number, 0.0
    if kind == "percent":
        return 0.0, number
    return number


def _length_value(pixels, percent, kinds):
    """A sum of lengths and percentages, as (number, kind): plain when one of them is absent."""
    if "percent" not in kinds and "mixed" not in kinds:
        return pixels, "length"
    if "length" not in kinds and "mixed" not in kinds:
        return percent, "percent"
    return (pixels, percent), "mixed"


def _scaled(number, kind, factor):
    if kind == "mixed":
        return (number[0] * factor, number[1] * factor), kind
    return number * factor, kind


def _rounded(strategy, value, step):
    if step == 0 or math.isinf(value) or math.isnan(value):
        return math.nan
    if math.isinf(step):
        return value if strategy != "nearest" else math.copysign(0.0, value)
    quotient = value / step
    if strategy == "up":
        return math.ceil(quotient) * step
    if strategy == "down":
        return math.floor(quotient) * step
    if strategy == "to-zero":
        return math.trunc(quotient) * step
    return math.floor(quotient + 0.5) * step


def _remainder(dividend, divisor, sign_of_divisor):
    """mod() (sign of the divisor) or rem() (sign of the dividend)."""
    if divisor == 0 or math.isinf(dividend) or math.isnan(dividend) or math.isnan(divisor):
        return math.nan
    if math.isinf(divisor):
        if sign_of_divisor and (dividend < 0) != (divisor < 0) and dividend != 0:
            return math.nan
        return dividend
    if sign_of_divisor:
        return dividend - divisor * math.floor(dividend / divisor)
    return math.fmod(dividend, divisor)


def _square_root(number):
    if number < 0 or math.isnan(number):
        return math.nan
    return math.sqrt(number)


def _logarithm(number, base):
    if number < 0 or math.isnan(number) or base <= 0 or base == 1:
        return math.nan
    if number == 0:
        return -math.inf
    if math.isinf(number):
        return math.inf
    return math.log(number) / math.log(base)


def _power(base, exponent):
    try:
        return math.pow(base, exponent)
    except OverflowError:
        return math.inf
    except ValueError:  # a negative base with a fractional exponent
        return math.nan


def _exponential(number):
    try:
        return math.exp(number)
    except OverflowError:
        return math.inf


def _trigonometric(function_name, number, kind):
    radians = math.radians(number) if kind == "angle" else number
    if math.isinf(radians) or math.isnan(radians):
        return math.nan
    if function_name == "sin":
        return math.sin(radians)
    if function_name == "cos":
        return math.cos(radians)
    return math.tan(radians)


def _inverse_trigonometric(function_name, number):
    if function_name == "atan":
        return math.degrees(math.atan(number))
    if math.isnan(number) or number < -1 or number > 1:
        return math.nan
    if function_name == "asin":
        return math.degrees(math.asin(number))
    return math.degrees(math.acos(number))


class _ExpressionParser:
    """Evaluates CSS math (calc(), min(), round(), sin(), ... and the constants) to (number, kind):
    kind 'length' (in pixels), 'number', 'percent', 'angle' (in degrees) or 'mixed' (a percentage
    plus a length, number (pixels, percent)). NaN and infinities follow IEEE arithmetic, as in
    Chrome. Raises ValueError on anything it does not understand, on mixed values a function other
    than calc() would need to compare, or nesting deeper than MAXIMUM_MATH_DEPTH."""

    def __init__(self, text):
        self.tokens = []
        position = 0
        text = text.strip()
        while position < len(text):
            match = _TOKEN.match(text, position)
            if match is None or match.end() == position:
                raise ValueError(text)
            self.tokens.append(match.groups())
            position = match.end()
            while position < len(text) and text[position].isspace():
                position += 1
        self.position = 0
        self.depth = 0

    def _peek(self):
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None

    def _take_operator(self, operators):
        token = self._peek()
        if token is not None and token[4] in operators:
            self.position += 1
            return token[4]
        return None

    def parse(self):
        value = self._sum()
        if self._peek() is not None:
            raise ValueError("trailing tokens")
        return value

    def _sum(self):
        number, kind = self._product()
        while True:
            operator = self._take_operator(("+", "-"))
            if operator is None:
                return number, kind
            other_number, other_kind = self._product()
            if operator == "-":
                other_number, other_kind = _scaled(other_number, other_kind, -1)
            if kind in _LENGTH_KINDS and other_kind in _LENGTH_KINDS:
                pixels, percent = _pixels_and_percent(number, kind)
                other_pixels, other_percent = _pixels_and_percent(other_number, other_kind)
                number, kind = _length_value(pixels + other_pixels, percent + other_percent, (kind, other_kind))
                continue
            if other_kind != kind:
                raise ValueError("mixed units")
            number = number + other_number

    def _product(self):
        number, kind = self._factor()
        while True:
            operator = self._take_operator(("*", "/"))
            if operator is None:
                return number, kind
            other_number, other_kind = self._factor()
            if operator == "*":
                if kind == "number":
                    number, kind = _scaled(other_number, other_kind, number)
                elif other_kind == "number":
                    number, kind = _scaled(number, kind, other_number)
                else:
                    raise ValueError("length times length")
            elif other_kind == "number":
                if kind == "mixed":
                    number = (_divided(number[0], other_number), _divided(number[1], other_number))
                else:
                    number = _divided(number, other_number)
            elif other_kind == kind and kind != "mixed":
                number, kind = _divided(number, other_number), "number"  # 10px / 1px is the number 10
            else:
                raise ValueError("bad division")

    def _arguments(self):
        values = [self._argument()]
        while self._take_operator((",",)):
            values.append(self._argument())
        if self._take_operator((")",)) is None:
            raise ValueError("missing )")
        return values

    def _argument(self):
        token = self._peek()
        if token is not None and token[3] in _ROUNDING_STRATEGIES:
            self.position += 1
            return token[3], "strategy"
        return self._sum()

    def _factor(self):
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end")
        number_text, unit, function_name, identifier, operator = token
        self.position += 1
        if number_text is not None:
            number = float(number_text)
            if unit == "":
                return number, "number"
            if unit == "%":
                return number, "percent"
            if unit in PIXELS_PER_UNIT:
                return number * PIXELS_PER_UNIT[unit], "length"
            if unit in DEGREES_PER_UNIT:
                return number * DEGREES_PER_UNIT[unit], "angle"
            raise ValueError("unknown unit " + unit)
        if identifier is not None:
            if identifier in _CONSTANTS:
                return _CONSTANTS[identifier], "number"
            raise ValueError("unknown name " + identifier)
        if function_name is not None or operator == "(":
            self.depth += 1
            if self.depth > MAXIMUM_MATH_DEPTH:
                raise ValueError("nested too deep")
        if function_name is not None:
            arguments = self._arguments()
            self.depth -= 1
            return _function_value(function_name, arguments)
        if operator == "(":
            value = self._sum()
            if self._take_operator((")",)) is None:
                raise ValueError("missing )")
            self.depth -= 1
            return value
        raise ValueError("unexpected " + str(operator))


def _function_value(function_name, arguments):
    """The (number, kind) of one math function applied to its evaluated arguments."""
    strategy = "nearest"
    if function_name == "round" and arguments and arguments[0][1] == "strategy":
        strategy = arguments[0][0]
        arguments = arguments[1:]
    kinds = set()
    numbers = []
    for argument_number, kind in arguments:
        if kind == "strategy":
            raise ValueError("misplaced rounding strategy")
        kinds.add(kind)
        numbers.append(argument_number)
    if len(kinds) != 1:
        raise ValueError("mixed kinds")
    kind = arguments[0][1]
    if function_name == "calc" and len(numbers) == 1:
        return numbers[0], kind
    if kind == "mixed":
        raise ValueError("cannot compare a percentage with a length here")
    for number in numbers:
        if math.isnan(number) and function_name in ("min", "max", "clamp", "hypot"):
            return math.nan, kind
    if function_name == "min":
        return min(numbers), kind
    if function_name == "max":
        return max(numbers), kind
    if function_name == "clamp" and len(numbers) == 3:
        return max(numbers[0], min(numbers[1], numbers[2])), kind
    if function_name == "hypot":
        return math.hypot(*numbers), kind
    if function_name == "progress" and len(numbers) == 3:
        # Clamped to 0..1 (measured: calc(progress(2, 0, 1) - 1) is 0).
        return max(0.0, min(1.0, _divided(numbers[0] - numbers[1], numbers[2] - numbers[1]))), "number"
    if len(numbers) == 1:
        number = numbers[0]
        if function_name == "abs":
            return abs(number), kind
        if function_name == "sign":
            if number == 0 or math.isnan(number):
                return number, "number"
            return math.copysign(1.0, number), "number"
        if function_name == "round" and kind == "number":
            return _rounded(strategy, number, 1.0), kind
        if function_name in ("sin", "cos", "tan") and kind in ("number", "angle"):
            return _trigonometric(function_name, number, kind), "number"
        if kind == "number":
            if function_name in ("asin", "acos", "atan"):
                return _inverse_trigonometric(function_name, number), "angle"
            if function_name == "sqrt":
                return _square_root(number), kind
            if function_name == "exp":
                return _exponential(number), kind
            if function_name == "log":
                return _logarithm(number, math.e), kind
    if len(numbers) == 2:
        if function_name == "round":
            return _rounded(strategy, numbers[0], numbers[1]), kind
        if function_name == "mod":
            return _remainder(numbers[0], numbers[1], True), kind
        if function_name == "rem":
            return _remainder(numbers[0], numbers[1], False), kind
        if function_name == "atan2":
            return math.degrees(math.atan2(numbers[0], numbers[1])), "angle"
        if kind == "number":
            if function_name == "pow":
                return _power(numbers[0], numbers[1]), kind
            if function_name == "log":
                return _logarithm(numbers[0], numbers[1]), kind
    raise ValueError("unsupported function " + function_name)


def _finite(number):
    """A top-level math result as Chrome uses it: NaN becomes 0, an infinity the largest length."""
    if math.isnan(number):
        return 0.0
    return max(-LARGEST_LENGTH_PIXELS, min(LARGEST_LENGTH_PIXELS, number))


def _evaluated(value):
    """(number, kind) of a whole value, with NaN and infinities made finite; None when unknown."""
    if not value:
        return None
    text = value.strip().lower()
    if not text or "var(" in text:
        return None
    try:
        number, kind = _ExpressionParser(text).parse()
    except (ValueError, OverflowError):
        return None
    if kind == "mixed":
        pixels = _finite(number[0])
        percent = _finite(number[1])
        # A zero part is zero whatever the percentage is of: calc(0px + 0%) is the length 0px.
        if percent == 0:
            return pixels, "length"
        if pixels == 0:
            return percent, "percent"
        return (pixels, percent), kind
    return _finite(number), kind


def numeric_value(value):
    """(number, kind) for a CSS number, percentage, angle or length (kind 'length' is in pixels,
    'angle' in degrees), including math functions; None when it cannot be evaluated or mixes a
    percentage with a length (see length_and_percent)."""
    evaluated = _evaluated(value)
    if evaluated is None or evaluated[1] == "mixed":
        return None
    return evaluated


def length_and_percent(value):
    """(pixels, percent) for a length, a percentage or a sum of both such as calc(-100% - 10px);
    None otherwise."""
    evaluated = _evaluated(value)
    if evaluated is None or evaluated[1] not in _LENGTH_KINDS:
        return None
    number, kind = evaluated
    if kind == "length":
        return number, 0.0
    if kind == "percent":
        return 0.0, number
    return number


def length_in_pixels(value):
    """Pixels for a length (unitless 0 counts as 0px); None for percentages, keywords and unknowns."""
    parsed = numeric_value(value)
    if parsed is None:
        return None
    number, kind = parsed
    if kind == "length":
        return number
    if kind == "number" and number == 0:
        return 0.0
    return None


def plain_number(value):
    """A unitless number (or a percentage as a fraction, 50% -> 0.5); None otherwise."""
    parsed = numeric_value(value)
    if parsed is None:
        return None
    number, kind = parsed
    if kind == "number":
        return number
    if kind == "percent":
        return number / 100
    return None


# ---- splitting and simplifying values -------------------------------------

_MATH_FUNCTION_START = re.compile(r"(?<![\w-])(" + "|".join(MATH_FUNCTIONS) + r")\(", re.IGNORECASE)
_STRING_OR_URL = re.compile(r'"(?:[^"\\]|\\.)*"|' + r"'(?:[^'\\]|\\.)*'|url\([^)]*\)", re.IGNORECASE)
_UNITS_BY_KIND = {"length": "px", "percent": "%", "angle": "deg", "number": ""}


def _closing_parenthesis(text, opening):
    """The index of the parenthesis closing the one at opening, or None."""
    depth = 0
    for index in range(opening, len(text)):
        character = text[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _literal(number, kind):
    if number == int(number):
        digits = str(int(number))
    else:
        digits = f"{number:.10f}".rstrip("0").rstrip(".")
    if digits in ("-0", ""):
        digits = "0"
    return digits + _UNITS_BY_KIND[kind]


def _with_math_evaluated_outside_strings(text):
    pieces = []
    position = 0
    while True:
        match = _MATH_FUNCTION_START.search(text, position)
        if match is None:
            pieces.append(text[position:])
            return "".join(pieces)
        closing = _closing_parenthesis(text, match.end() - 1)
        if closing is None:
            pieces.append(text[position:])
            return "".join(pieces)
        evaluated = _evaluated(text[match.start():closing + 1])
        if evaluated is None:
            # Not evaluable as a whole: the math functions inside it may still be.
            pieces.append(text[position:match.end()])
            position = match.end()
            continue
        number, kind = evaluated
        if kind == "mixed":
            pieces.append(text[position:closing + 1])  # kept whole: see length_and_percent
            position = closing + 1
            continue
        literal = _literal(number, kind)
        before = text[match.start() - 1] if match.start() > 0 else " "
        after = text[closing + 1] if closing + 1 < len(text) else " "
        if before not in " ,(/":
            literal = " " + literal
        if after not in " ,)/":
            literal = literal + " "
        pieces.append(text[position:match.start()])
        pieces.append(literal)
        position = closing + 1


def with_math_evaluated(text):
    """text with each math function this parser can evaluate replaced by its value, as Chrome
    computes it (translateX(calc(0px - 9999px)) -> translateX(-9999px), calc(nan) -> 0). Sums of a
    percentage and a length stay as written. Quoted strings and url() are left alone.

    Use it only on a value Chrome accepts, after any var() is substituted: the result can be a
    value Chrome would reject as written (font-size: calc(-5px) is valid, -5px is not)."""
    if "(" not in text:
        return text
    # Short texts (nearly all) are cached, so the cache stays within a few megabytes.
    if len(text) > 1000:
        return _math_evaluated(text)
    return _cached_math_evaluated(text)


@functools.lru_cache(maxsize=4096)
def _cached_math_evaluated(text):
    return _math_evaluated(text)


def _math_evaluated(text):
    pieces = []
    position = 0
    for match in _STRING_OR_URL.finditer(text):
        pieces.append(_with_math_evaluated_outside_strings(text[position:match.start()]))
        pieces.append(match.group(0))
        position = match.end()
    pieces.append(_with_math_evaluated_outside_strings(text[position:]))
    return "".join(pieces)


def top_level_words(text):
    """The whitespace-separated words of a value, keeping each function whole:
    'calc(0px - 9999px) auto' -> ['calc(0px - 9999px)', 'auto']."""
    words = []
    current = []
    depth = 0
    for character in text or "":
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character.isspace() and depth <= 0:
            if current:
                words.append("".join(current))
                current = []
            continue
        current.append(character)
    if current:
        words.append("".join(current))
    return words


def top_level_arguments(text):
    """The comma-separated arguments of a list such as 'calc(1px, 2px), 3px', stripped."""
    arguments = []
    current = []
    depth = 0
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            arguments.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    arguments.append("".join(current).strip())
    return arguments


def function_arguments(text, function_names):
    """For each top-level call of one of function_names in text, (name, its arguments)."""
    calls = []
    pattern = re.compile(r"(?<![\w-])(" + "|".join(function_names) + r")\(")
    position = 0
    while True:
        match = pattern.search(text or "", position)
        if match is None:
            return calls
        closing = _closing_parenthesis(text, match.end() - 1)
        if closing is None:
            return calls
        calls.append((match.group(1), top_level_arguments(text[match.end():closing])))
        position = closing + 1
