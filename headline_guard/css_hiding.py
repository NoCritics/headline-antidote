"""Thresholds and checks that decide whether one CSS value hides text.

html_visibility applies them to an element's declarations, css_cascade uses them to find the
rules that could hide text, and browser_visibility passes the same thresholds to the browser.
"""

import re

from .css_values import PIXELS_PER_EM, length_in_pixels, numeric_value, parse_color, plain_number

# Font sizes below these are unreadable, per unit.
MINIMUM_READABLE_FONT_SIZES = {
    "px": 2.0, "pt": 1.5, "em": 0.15, "rem": 0.15, "%": 15.0, "vw": 0.2, "vh": 0.2, "": 2.0,
}
MINIMUM_VISIBLE_OPACITY = 0.1
# WCAG contrast ratio; 1.0 means identical colors and 4.5 is the usual accessibility minimum.
MINIMUM_VISIBLE_CONTRAST = 1.5
OFF_SCREEN_THRESHOLD_PIXELS = -500
# A box at most this tall or wide, with its overflow clipped, shows no readable text.
CLIPPED_BOX_MAXIMUM_PIXELS = 1.0
# Letters pulled this far together are drawn on top of each other.
COLLAPSED_LETTER_SPACING_EM = -0.5
COLLAPSED_LETTER_SPACING_PIXELS = -8.0
# Blur that makes text unreadable.
UNREADABLE_BLUR_PIXELS = 8.0
# An overlay must be at least this opaque to cover the text under it.
OPAQUE_ALPHA = 0.9
_COLOR_TOKEN = re.compile(r"(?:rgba?|hsla?|hwb|oklch|oklab|lch|lab)\([^()]*\)|#[0-9a-f]{3,8}\b|[a-z]+")


def leading_number(value):
    match = re.match(r"^\s*(-?\d*\.?\d+)", value)
    if match is None:
        return None
    return float(match.group(1))


def relative_luminance(color):
    channels = []
    for channel in color[:3]:
        fraction = channel / 255
        if fraction <= 0.03928:
            channels.append(fraction / 12.92)
        else:
            channels.append(((fraction + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first_color, second_color):
    first_luminance = relative_luminance(first_color)
    second_luminance = relative_luminance(second_color)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def colors_in(text):
    """Every color a value such as a background or text-shadow mentions, in order."""
    colors = []
    for token in _COLOR_TOKEN.findall(text or ""):
        color = parse_color(token)
        if color is not None:
            colors.append(color)
    return colors


def declared_background_color(declarations):
    """The element's own background color when it is a plain, visible color; None otherwise."""
    background = declarations.get("background-color")
    if background is not None:
        color = parse_color(background)
    else:
        background = declarations.get("background")
        if background is None:
            return None
        without_images = re.sub(r"url\([^)]*\)", " ", background)
        if "gradient(" in without_images or "image-set(" in without_images:
            return None
        colors = colors_in(without_images)
        color = colors[-1] if colors else None
    if color is None or color[3] < MINIMUM_VISIBLE_OPACITY:
        return None
    return color


def font_size_is_unreadable(value):
    value = (value or "").strip().lower()
    match = re.fullmatch(r"(-?\d*\.?\d+)\s*([a-z%]*)", value)
    if match is not None:
        minimum_size = MINIMUM_READABLE_FONT_SIZES.get(match.group(2))
        if minimum_size is not None:
            return float(match.group(1)) < minimum_size
        pixels = length_in_pixels(value)
        return pixels is not None and pixels < MINIMUM_READABLE_FONT_SIZES["px"]
    if value.startswith(("calc(", "min(", "max(", "clamp(")):
        parsed = numeric_value(value)
        if parsed is None:
            return False
        number, kind = parsed
        if kind == "length":
            return number < MINIMUM_READABLE_FONT_SIZES["px"]
        if kind == "percent":
            return number < MINIMUM_READABLE_FONT_SIZES["%"]
        return number == 0
    return False


def font_shorthand_size(value):
    """The size in a `font` shorthand ('bold 0/0 a' -> '0'), or None."""
    for token in (value or "").split():
        size_text = token.split("/")[0]
        if "/" in token or size_text == "0" or re.fullmatch(r"-?\d*\.?\d+[a-z%]+", size_text):
            return size_text
    return None


def is_off_screen_offset(value):
    pixels = length_in_pixels(value or "")
    if pixels is not None:
        return pixels <= OFF_SCREEN_THRESHOLD_PIXELS
    parsed = numeric_value(value or "")
    return parsed is not None and parsed[1] == "percent" and parsed[0] <= -100


def translation_is_off_screen(transform_value, translate_value):
    lengths = []
    for function_name, arguments in re.findall(r"(translate3d|translatex|translatey|translate)\(([^()]*)\)",
                                               transform_value or ""):
        for argument in arguments.split(","):
            lengths.append(argument.strip())
    for part in (translate_value or "").split():
        lengths.append(part)
    for length in lengths:
        pixels = length_in_pixels(length)
        if pixels is not None and pixels <= OFF_SCREEN_THRESHOLD_PIXELS:
            return True
    return False


def filter_hiding_reason(filter_value):
    if not filter_value or filter_value == "none":
        return None
    for function_name, argument in re.findall(r"([a-z-]+)\(([^()]*)\)", filter_value):
        if function_name == "opacity":
            amount = plain_number(argument.strip())
            if amount is not None and amount < MINIMUM_VISIBLE_OPACITY:
                return f"filter:opacity({argument.strip()})"
        elif function_name == "blur":
            radius = length_in_pixels(argument.strip())
            if radius is not None and radius >= UNREADABLE_BLUR_PIXELS:
                return f"filter:blur({argument.strip()})"
    return None


def letters_collapsed(letter_spacing):
    parsed = numeric_value(letter_spacing or "")
    if parsed is None:
        return False
    text = letter_spacing.strip()
    if text.endswith("em") and not text.endswith("rem"):
        return parsed[0] / PIXELS_PER_EM <= COLLAPSED_LETTER_SPACING_EM
    return parsed[1] == "length" and parsed[0] <= COLLAPSED_LETTER_SPACING_PIXELS


def _is_stretched_over_its_box(declarations):
    inset = declarations.get("inset")
    if inset is not None:
        for part in inset.split():
            if length_in_pixels(part) != 0:
                return False
        return True
    top = length_in_pixels(declarations.get("top", ""))
    left = length_in_pixels(declarations.get("left", ""))
    if top != 0 or left != 0:
        return False
    right = length_in_pixels(declarations.get("right", ""))
    bottom = length_in_pixels(declarations.get("bottom", ""))
    width = numeric_value(declarations.get("width", ""))
    height = numeric_value(declarations.get("height", ""))
    full_width = right == 0 or (width is not None and width[1] == "percent" and width[0] >= 100)
    full_height = bottom == 0 or (height is not None and height[1] == "percent" and height[0] >= 100)
    return full_width and full_height


def is_covering_overlay(declarations):
    """An absolutely positioned, opaque box stretched over its containing block."""
    if declarations.get("position") != "absolute":
        return False
    if declarations.get("display") == "none" or declarations.get("visibility") in ("hidden", "collapse"):
        return False
    background = declared_background_color(declarations)
    if background is None or background[3] < OPAQUE_ALPHA:
        return False
    opacity = plain_number(declarations.get("opacity", "1"))
    if opacity is not None and opacity < OPAQUE_ALPHA:
        return False
    z_index = leading_number(declarations.get("z-index", ""))
    if z_index is not None and z_index < 0:
        return False
    return _is_stretched_over_its_box(declarations)


def opacity_is_invisible(value):
    opacity = plain_number(value)
    return opacity is not None and opacity < MINIMUM_VISIBLE_OPACITY


def font_shorthand_is_unreadable(value):
    shorthand_size = font_shorthand_size(value)
    return shorthand_size is not None and font_size_is_unreadable(shorthand_size)


def line_height_collapsed(value):
    pixels = length_in_pixels(value)
    return (pixels is not None and pixels <= CLIPPED_BOX_MAXIMUM_PIXELS) or plain_number(value) == 0


def scale_is_zero(value):
    return re.fullmatch(r"0(\.0*)?(\s+0(\.0*)?)?", value.strip()) is not None


def first_offset_is_off_screen(value):
    """Whether the first length of an offset value ('left', 'inset', ...) is far off-screen."""
    words = value.split()
    return bool(words) and is_off_screen_offset(words[0])
