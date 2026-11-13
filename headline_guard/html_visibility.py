"""Separates the text a reader sees from text hidden in the HTML.

This works without a browser. It understands inline styles, the `hidden` attribute,
<template>/<noscript>/<datalist>, closed <details>, SVG tooltip text, old presentational
attributes (<font color>, bgcolor), comments, and CSS rules: with tinycss2 and
cssselect2 installed, a real cascade (see css_cascade); otherwise simple `.class`,
`#id` and `tag` rules in <style> blocks.

"Hidden" includes "practically invisible": tiny fonts, near-zero opacity, text whose
color barely differs from its background, text collapsed onto itself, text covered by
an opaque overlay drawn over its box, and text drawn behind an enclosing background.

Without layout it cannot see overlap between unrelated parts of the page, and it never
runs JavaScript. For those, render the page in a browser (browser_visibility).
"""

import re
import unicodedata
from dataclasses import dataclass

import lxml.html
from lxml import etree

from .css_values import NAMED_COLORS, length_in_pixels, numeric_value, parse_color, plain_number

# Contents are code or metadata, never headline text, so they are skipped without a flag.
NON_TEXT_TAGS = {"script", "style", "head", "meta", "link"}
# Contents are text a browser does not display.
HIDDEN_CONTENT_TAGS = {"template", "noscript", "datalist"}
BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "title", "details", "summary",
}

# Font sizes below these are unreadable, per unit.
MINIMUM_READABLE_FONT_SIZES = {
    "px": 2.0, "pt": 1.5, "em": 0.15, "rem": 0.15, "%": 15.0, "vw": 0.2, "vh": 0.2, "": 2.0,
}
MINIMUM_VISIBLE_OPACITY = 0.1
# WCAG contrast ratio; 1.0 means identical colors and 4.5 is the usual accessibility minimum.
MINIMUM_VISIBLE_CONTRAST = 1.5
# When no background is declared, assume the usual white page; an external stylesheet may disagree.
ASSUMED_PAGE_BACKGROUND = (255, 255, 255)
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
# Fewer strong left-to-right letters than this under a right-to-left override is not reordered text.
MINIMUM_REORDERED_LETTERS = 2

HIGH = "high"
MEDIUM = "medium"
SCREEN_READER_ONLY_REASON = "screen-reader-only box"

POSITIONED = ("relative", "absolute", "fixed", "sticky")
_COLOR_TOKEN = re.compile(r"(?:rgba?|hsla?|hwb|oklch|oklab|lch|lab)\([^()]*\)|#[0-9a-f]{3,8}\b|[a-z]+")


@dataclass
class HiddenFragment:
    text: str
    reason: str
    kind: str      # "hidden_element", "html_comment" or "reordered_text"
    severity: str  # "high", or "medium" when hiding depends on a guessed page background
    element: object = None  # the lxml element (or comment) that is hidden
    # For loose text rather than an element: (element, "text") or (element, "tail").
    text_of: tuple = None


def _parse_declarations(style_text):
    declarations = {}
    for declaration in style_text.split(";"):
        if ":" not in declaration:
            continue
        property_name, value = declaration.split(":", 1)
        value = value.replace("!important", "").strip().lower()
        declarations[property_name.strip().lower()] = value
    return declarations


def _leading_number(value):
    match = re.match(r"^\s*(-?\d*\.?\d+)", value)
    if match is None:
        return None
    return float(match.group(1))


def _parse_color(value):
    """Returns (red, green, blue, alpha) or None when the color is unknown or not a plain color."""
    return parse_color(value)


def _relative_luminance(color):
    channels = []
    for channel in color[:3]:
        fraction = channel / 255
        if fraction <= 0.03928:
            channels.append(fraction / 12.92)
        else:
            channels.append(((fraction + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(first_color, second_color):
    first_luminance = _relative_luminance(first_color)
    second_luminance = _relative_luminance(second_color)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _colors_in(text):
    """Every color a value such as a background or text-shadow mentions, in order."""
    colors = []
    for token in _COLOR_TOKEN.findall(text or ""):
        color = parse_color(token)
        if color is not None:
            colors.append(color)
    return colors


def _background_color(declarations):
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
        colors = _colors_in(without_images)
        color = colors[-1] if colors else None
    if color is None or color[3] < MINIMUM_VISIBLE_OPACITY:
        return None
    return color


def _font_size_is_unreadable(value):
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


def _font_shorthand_size(value):
    """The size in a `font` shorthand ('bold 0/0 a' -> '0'), or None."""
    for token in (value or "").split():
        size_text = token.split("/")[0]
        if "/" in token or size_text == "0" or re.fullmatch(r"-?\d*\.?\d+[a-z%]+", size_text):
            return size_text
    return None


def _is_off_screen_offset(value):
    pixels = length_in_pixels(value or "")
    if pixels is not None:
        return pixels <= OFF_SCREEN_THRESHOLD_PIXELS
    parsed = numeric_value(value or "")
    return parsed is not None and parsed[1] == "percent" and parsed[0] <= -100


def _translation_is_off_screen(transform_value, translate_value):
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


def _filter_hiding_reason(filter_value):
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


def _letters_collapsed(letter_spacing):
    parsed = numeric_value(letter_spacing or "")
    if parsed is None:
        return False
    text = letter_spacing.strip()
    if text.endswith("em") and not text.endswith("rem"):
        return parsed[0] / 16 <= COLLAPSED_LETTER_SPACING_EM
    return parsed[1] == "length" and parsed[0] <= COLLAPSED_LETTER_SPACING_PIXELS


def _text_painted_another_way(declarations):
    """Transparent text that is still drawn: by a background clipped to the text, or a shadow."""
    clip = declarations.get("background-clip", "") + " " + declarations.get("-webkit-background-clip", "")
    if "text" in clip.split():
        background = declarations.get("background", "") + " " + declarations.get("background-image", "")
        if "gradient(" in background or "url(" in background:
            return True
        background_color = _background_color(declarations)
        if background_color is not None and background_color[3] >= MINIMUM_VISIBLE_OPACITY:
            return True
    for shadow_color in _colors_in(declarations.get("text-shadow", "")):
        if shadow_color[3] >= MINIMUM_VISIBLE_OPACITY:
            return True
    return False


def _text_color(declarations):
    """(parsed color, declared value) of the color glyphs are filled with, or (None, None)."""
    fill = declarations.get("-webkit-text-fill-color")
    if fill and fill not in ("currentcolor", "inherit", "initial", "unset", "revert"):
        parsed = parse_color(fill)
        if parsed is not None:
            return parsed, fill
    color = declarations.get("color")
    return parse_color(color), color


def _hiding_reason_from_declarations(declarations, background_color, background_lookup=None):
    """Returns (reason, severity) when the declarations hide text, otherwise None.

    background_lookup: when the rules can compute an element's real background from the
    stylesheets, it is asked only here, for elements whose text color matters.
    """
    if declarations.get("display") == "none":
        return ("display:none", HIGH)
    if declarations.get("content-visibility") == "hidden":
        return ("content-visibility:hidden", HIGH)
    if declarations.get("visibility") in ("hidden", "collapse"):
        return ("visibility:" + declarations["visibility"], HIGH)
    if "opacity" in declarations:
        opacity = plain_number(declarations["opacity"])
        if opacity is not None and opacity < MINIMUM_VISIBLE_OPACITY:
            return (f"opacity:{declarations['opacity']}", HIGH)
    filter_reason = _filter_hiding_reason(declarations.get("filter"))
    if filter_reason is not None:
        return (filter_reason, HIGH)
    if "font-size" in declarations and _font_size_is_unreadable(declarations["font-size"]):
        return ("font-size:" + declarations["font-size"], HIGH)
    if "font" in declarations:
        shorthand_size = _font_shorthand_size(declarations["font"])
        if shorthand_size is not None and _font_size_is_unreadable(shorthand_size):
            return ("font:" + declarations["font"], HIGH)
    if _letters_collapsed(declarations.get("letter-spacing")):
        return ("letter-spacing:" + declarations["letter-spacing"] + " draws the letters on top of each other", HIGH)

    text_color, declared_color = _text_color(declarations)
    if text_color is not None and not _text_painted_another_way(declarations):
        if text_color[3] < MINIMUM_VISIBLE_OPACITY:
            return ("transparent text color", HIGH)
        if background_lookup is not None:
            background_color = background_lookup()
        if background_color is not None:
            if _contrast_ratio(text_color, background_color) < MINIMUM_VISIBLE_CONTRAST:
                return (f"text color {declared_color} nearly matches its background", HIGH)
        elif _contrast_ratio(text_color, ASSUMED_PAGE_BACKGROUND) < MINIMUM_VISIBLE_CONTRAST:
            return (
                f"text color {declared_color} is invisible on a white page "
                "(page background not declared here, so this is a guess)",
                MEDIUM,
            )

    clip = declarations.get("clip", "").replace(" ", "").replace("px", "")
    if clip.startswith("rect(0,0,0,0") or clip.startswith("rect(0000"):
        return ("clip:rect(0 0 0 0)", HIGH)
    clip_path = declarations.get("clip-path", "").replace(" ", "")
    if clip_path.startswith("inset(50%") or clip_path.startswith("circle(0"):
        return ("clip-path", HIGH)
    transform = declarations.get("transform", "").replace(" ", "")
    if re.search(r"scale[xy]?\(0(\.0*)?[,)]", transform):
        return ("transform:scale(0)", HIGH)
    if re.fullmatch(r"0(\.0*)?(\s+0(\.0*)?)?", declarations.get("scale", "").strip()):
        return ("scale:0", HIGH)
    if _translation_is_off_screen(declarations.get("transform"), declarations.get("translate")):
        return ("moved off-screen by a transform", HIGH)

    overflow_words = []
    for overflow_property in ("overflow", "overflow-x", "overflow-y"):
        for word in declarations.get(overflow_property, "").split():
            overflow_words.append(word)
    if "hidden" in overflow_words or "clip" in overflow_words:
        for size_property in ("width", "height", "max-width", "max-height"):
            if size_property in declarations:
                pixels = length_in_pixels(declarations[size_property])
                if pixels is not None and pixels <= CLIPPED_BOX_MAXIMUM_PIXELS:
                    reason = f"{size_property}:{declarations[size_property]} with overflow:hidden"
                    if pixels > 0:
                        # The usual "visually hidden" pattern for labels read only by screen readers.
                        reason = f"{SCREEN_READER_ONLY_REASON} ({reason})"
                    return (reason, HIGH)
        line_height = declarations.get("line-height")
        if line_height is not None and "height" not in declarations and "min-height" not in declarations:
            line_pixels = length_in_pixels(line_height)
            line_number = plain_number(line_height)
            if (line_pixels is not None and line_pixels <= CLIPPED_BOX_MAXIMUM_PIXELS) or line_number == 0:
                return (f"line-height:{line_height} with overflow:hidden", HIGH)
    if declarations.get("position") in ("absolute", "fixed"):
        for offset_property in ("left", "top", "right", "bottom", "margin-left", "margin-top", "inset"):
            offset_value = declarations.get(offset_property, "")
            first_offset = offset_value.split()[0] if offset_value.split() else ""
            if first_offset and _is_off_screen_offset(first_offset):
                return (f"positioned off-screen ({offset_property}:{offset_value})", HIGH)
    if _is_off_screen_offset(declarations.get("text-indent", "")):
        return ("text-indent off-screen", HIGH)
    return None


# ---- overlays and stacking ------------------------------------------------

def _full_declarations(rules, element):
    """Every winning declaration of an element (the real cascade when the rules have one)."""
    if hasattr(rules, "full_declarations"):
        return rules.full_declarations(element)
    tag = element.tag.lower() if isinstance(element.tag, str) else ""
    return rules.declarations_for(element, tag)


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


def _is_covering_overlay(declarations):
    """An absolutely positioned, opaque box stretched over its containing block."""
    if declarations.get("position") != "absolute":
        return False
    if declarations.get("display") == "none" or declarations.get("visibility") in ("hidden", "collapse"):
        return False
    background = _background_color(declarations)
    if background is None or background[3] < OPAQUE_ALPHA:
        return False
    opacity = plain_number(declarations.get("opacity", "1"))
    if opacity is not None and opacity < OPAQUE_ALPHA:
        return False
    z_index = _leading_number(declarations.get("z-index", ""))
    if z_index is not None and z_index < 0:
        return False
    return _is_stretched_over_its_box(declarations)


def _has_positioned_container(element, rules):
    """True when an absolutely positioned child of element is sized by element or an ancestor
    below <body>. Overlays sized by the whole page (paywalls, cookie banners) are not counted."""
    node = element
    while node is not None and isinstance(node.tag, str):
        tag = node.tag.lower()
        if tag in ("body", "html"):
            return False
        declarations = _full_declarations(rules, node)
        if declarations.get("position") in POSITIONED:
            return True
        if declarations.get("transform", "none") not in ("", "none"):
            return True
        node = node.getparent()
    return False


def _covering_pseudo_element(element, rules):
    if not hasattr(rules, "pseudo_declarations"):
        return None
    pseudo_declarations = rules.pseudo_declarations(element)
    for pseudo_name in ("before", "after"):
        declarations = pseudo_declarations.get(pseudo_name)
        if not declarations:
            continue
        if declarations.get("content", "normal") in ("none", "normal"):
            continue
        if _is_covering_overlay(declarations):
            return f"covered by its own ::{pseudo_name} overlay"
    return None


def _covering_child(element, rules):
    """The child element that is an opaque overlay over element's content, or None."""
    for child in element:
        if not isinstance(child.tag, str):
            continue
        child_tag = child.tag.lower()
        if child_tag in NON_TEXT_TAGS:
            continue
        if _is_covering_overlay(_declarations_with_hints(rules, child, child_tag)):
            return child
    return None


def _creates_stacking_context(declarations):
    position = declarations.get("position")
    if position in ("fixed", "sticky"):
        return True
    if position in ("relative", "absolute") and declarations.get("z-index", "auto") not in ("", "auto"):
        return True
    opacity = plain_number(declarations.get("opacity", "1"))
    if opacity is not None and opacity < 1:
        return True
    for property_name in ("transform", "filter", "clip-path", "mask", "perspective"):
        if declarations.get(property_name, "none") not in ("", "none"):
            return True
    if declarations.get("isolation") == "isolate":
        return True
    if declarations.get("mix-blend-mode", "normal") not in ("", "normal"):
        return True
    return False


def _drawn_behind_background(element, declarations, rules):
    """A negative z-index draws an element under the backgrounds of enclosing boxes, up to the
    nearest one that starts a stacking context."""
    if declarations.get("position") not in POSITIONED:
        return None
    z_index = _leading_number(declarations.get("z-index", ""))
    if z_index is None or z_index >= 0:
        return None
    for ancestor in element.iterancestors():
        if not isinstance(ancestor.tag, str) or ancestor.tag.lower() in ("body", "html"):
            return None
        ancestor_declarations = _full_declarations(rules, ancestor)
        if _creates_stacking_context(ancestor_declarations):
            return None
        background = _background_color(ancestor_declarations)
        if background is not None and background[3] >= OPAQUE_ALPHA:
            return f"drawn behind an enclosing background (z-index:{declarations['z-index']})"
    return None


# ---- presentational HTML --------------------------------------------------

def _presentational_hints(element, tag):
    """Styles set by old HTML attributes: <font color>, bgcolor."""
    hints = None
    if tag == "font" and element.get("color"):
        hints = {"color": element.get("color").strip().lower()}
    bgcolor = element.get("bgcolor")
    if bgcolor:
        if hints is None:
            hints = {}
        hints["background-color"] = bgcolor.strip().lower()
    return hints


def _declarations_with_hints(rules, element, tag):
    declarations = rules.declarations_for(element, tag)
    hints = _presentational_hints(element, tag)
    if hints is None:
        return declarations
    merged = dict(hints)
    merged.update(declarations)
    return merged


def _is_svg_tooltip(element, tag):
    if tag not in ("title", "desc"):
        return False
    for ancestor in element.iterancestors():
        if isinstance(ancestor.tag, str) and ancestor.tag.lower() == "svg":
            return True
    return False


def _is_closed_details(element, tag):
    return tag == "details" and element.get("open") is None


def _reordering_reason(element, tag, declarations):
    """Right-to-left override of left-to-right letters: the reader sees them in reverse order."""
    if tag == "bdo":
        direction = (element.get("dir") or "").lower()
        if direction != "rtl":
            return None
        reason = '<bdo dir="rtl">'
    elif declarations.get("unicode-bidi") in ("bidi-override", "isolate-override"):
        direction = declarations.get("direction") or (element.get("dir") or "").lower()
        if not direction:
            for ancestor in element.iterancestors():
                if isinstance(ancestor.tag, str) and ancestor.get("dir"):
                    direction = ancestor.get("dir").lower()
                    break
        if direction != "rtl":
            return None
        reason = "unicode-bidi:" + declarations["unicode-bidi"] + " with direction:rtl"
    else:
        return None
    left_to_right_letters = 0
    for character in element.text_content():
        if unicodedata.bidirectional(character) == "L":
            left_to_right_letters += 1
    if left_to_right_letters < MINIMUM_REORDERED_LETTERS:
        return None
    return reason


class _StylesheetRules:
    """Declarations from <style> blocks, for simple `.class`, `#id` and `tag` selectors only."""

    def __init__(self, root):
        self.by_class = {}
        self.by_id = {}
        self.by_tag = {}
        for style_element in root.iter("style"):
            css_text = re.sub(r"/\*.*?\*/", "", style_element.text or "", flags=re.DOTALL)
            for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css_text):
                declarations = _parse_declarations(body)
                for selector in selectors.split(","):
                    selector = selector.strip()
                    if re.fullmatch(r"\.[\w-]+", selector):
                        self.by_class.setdefault(selector[1:], {}).update(declarations)
                    elif re.fullmatch(r"#[\w-]+", selector):
                        self.by_id.setdefault(selector[1:], {}).update(declarations)
                    elif re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", selector):
                        self.by_tag.setdefault(selector.lower(), {}).update(declarations)

    def declarations_for(self, element, tag):
        declarations = {}
        declarations.update(self.by_tag.get(tag, {}))
        for class_name in (element.get("class") or "").split():
            declarations.update(self.by_class.get(class_name, {}))
        element_id = element.get("id")
        if element_id:
            declarations.update(self.by_id.get(element_id, {}))
        declarations.update(_parse_declarations(element.get("style") or ""))
        return declarations


def _parse(html):
    lowered_start = html.lstrip()[:200].lower()
    if lowered_start.startswith("<!doctype") or "<html" in lowered_start or "<body" in lowered_start:
        return lxml.html.document_fromstring(html)
    return lxml.html.fragment_fromstring(html, create_parent="div")


def _collapse_whitespace(text):
    return re.sub(r"\s+", " ", text).strip()


def _background_lookup(rules, element):
    """A function giving the element's real background, when the rules can compute it."""
    if not hasattr(rules, "background_for"):
        return None

    def lookup():
        return rules.background_for(element)
    return lookup


def _element_hiding(element, tag, rules, inherited_background):
    """(reason, severity, background) for one element: why it is hidden (or None), and the
    background its children inherit."""
    if tag in HIDDEN_CONTENT_TAGS:
        return (f"inside <{tag}>", HIGH), inherited_background, None
    if element.get("hidden") is not None:
        return ("hidden attribute", HIGH), inherited_background, None
    if tag == "input" and (element.get("type") or "").lower() == "hidden":
        return ("hidden input", HIGH), inherited_background, None
    if _is_svg_tooltip(element, tag):
        return ("SVG tooltip text", HIGH), inherited_background, None
    declarations = _declarations_with_hints(rules, element, tag)
    own_background = _background_color(declarations)
    if own_background is not None:
        inherited_background = own_background
    hiding = _hiding_reason_from_declarations(
        declarations, inherited_background, _background_lookup(rules, element)
    )
    if hiding is None:
        behind = _drawn_behind_background(element, declarations, rules)
        if behind is not None:
            hiding = (behind, HIGH)
    if hiding is None:
        pseudo_reason = _covering_pseudo_element(element, rules)
        if pseudo_reason is not None and _has_positioned_container(element, rules):
            hiding = (pseudo_reason, HIGH)
    return hiding, inherited_background, declarations


def _ancestor_state(element, rules):
    """Background color and hiding inherited from the element's ancestors, outermost first."""
    ancestors = []
    for ancestor in element.iterancestors():
        ancestors.append(ancestor)
    ancestors.reverse()
    inherited_background = None
    path = ancestors + [element]
    for position, ancestor in enumerate(ancestors):
        ancestor_tag = ancestor.tag.lower() if isinstance(ancestor.tag, str) else ""
        hiding, inherited_background, _ = _element_hiding(ancestor, ancestor_tag, rules, inherited_background)
        if hiding is not None:
            return inherited_background, (f"an enclosing element is hidden ({hiding[0]})", hiding[1])
        child_on_path = path[position + 1]
        if _is_closed_details(ancestor, ancestor_tag):
            child_tag = child_on_path.tag.lower() if isinstance(child_on_path.tag, str) else ""
            if child_tag != "summary":
                return inherited_background, ("inside a closed <details>", HIGH)
        overlay = _covering_child(ancestor, rules)
        if overlay is not None and overlay is not child_on_path and _has_positioned_container(ancestor, rules):
            return inherited_background, ("covered by an opaque overlay drawn over it", HIGH)
    return inherited_background, None


def _hide_loose_content(element, keep_child, reason, hidden_fragments):
    """Records element's own text, tails and children (except keep_child) as hidden."""
    if element.text and element.text.strip():
        hidden_fragments.append(HiddenFragment(
            _collapse_whitespace(element.text), reason, "hidden_element", HIGH, None, (element, "text"),
        ))
    for child in element:
        if child is not keep_child and isinstance(child.tag, str):
            child_tag = child.tag.lower()
            child_text = _collapse_whitespace(child.text_content())
            if child_tag not in NON_TEXT_TAGS and child_text:
                hidden_fragments.append(HiddenFragment(child_text, reason, "hidden_element", HIGH, child))
        if child.tail and child.tail.strip():
            hidden_fragments.append(HiddenFragment(
                _collapse_whitespace(child.tail), reason, "hidden_element", HIGH, None, (child, "tail"),
            ))


def _visit(element, inherited_background, rules, visible_parts, hidden_fragments):
    """Collects visible text and the outermost hidden elements under element."""
    tag = element.tag.lower() if isinstance(element.tag, str) else ""
    if tag in NON_TEXT_TAGS:
        return
    hiding, inherited_background, declarations = _element_hiding(element, tag, rules, inherited_background)
    if hiding is not None:
        hidden_text = _collapse_whitespace(element.text_content())
        if hidden_text:
            hidden_fragments.append(
                HiddenFragment(hidden_text, hiding[0], "hidden_element", hiding[1], element)
            )
        return

    reordering = _reordering_reason(element, tag, declarations)
    if reordering is not None:
        hidden_fragments.append(HiddenFragment(
            _collapse_whitespace(element.text_content()),
            f"shown to readers in reverse order ({reordering})", "reordered_text", HIGH, element,
        ))

    if tag in BLOCK_TAGS:
        visible_parts.append(" ")

    if _is_closed_details(element, tag):
        summary = None
        for child in element:
            if isinstance(child.tag, str) and child.tag.lower() == "summary":
                summary = child
                break
        _hide_loose_content(element, summary, "inside a closed <details>", hidden_fragments)
        if summary is not None:
            _visit(summary, inherited_background, rules, visible_parts, hidden_fragments)
        visible_parts.append(" ")
        return

    overlay = _covering_child(element, rules)
    if overlay is not None and _has_positioned_container(element, rules):
        _hide_loose_content(element, overlay, "covered by an opaque overlay drawn over it", hidden_fragments)
        _visit(overlay, inherited_background, rules, visible_parts, hidden_fragments)
        visible_parts.append(" ")
        return

    if element.text:
        visible_parts.append(element.text)
    for child in element:
        if isinstance(child, etree._Comment):
            comment_text = _collapse_whitespace(child.text or "")
            if comment_text:
                hidden_fragments.append(HiddenFragment(comment_text, "HTML comment", "html_comment", MEDIUM, child))
        elif isinstance(child.tag, str):
            _visit(child, inherited_background, rules, visible_parts, hidden_fragments)
        if child.tail:
            visible_parts.append(child.tail)
    if tag in BLOCK_TAGS:
        visible_parts.append(" ")


def parse_document(html, stylesheets=None):
    """Parses an HTML page or fragment and collects its CSS rules: (root, rules).

    stylesheets: CSS text of the page's external stylesheets, in document order, if the
    caller has fetched them (see linked_stylesheet_urls). With tinycss2 and cssselect2
    installed, a real cascade is used; otherwise a simple reader of .class/#id/tag rules
    in <style> blocks, which ignores external stylesheets.
    """
    root = _parse(html)
    try:
        from .css_cascade import CascadeRules
    except ImportError:
        return root, _StylesheetRules(root)
    return root, CascadeRules(root, stylesheets or ())


def linked_stylesheet_urls(html, base_url):
    """Absolute URLs of the page's <link rel="stylesheet"> files that apply to a screen, in order."""
    from urllib.parse import urljoin

    try:
        from .css_cascade import media_query_applies
    except ImportError:
        def media_query_applies(media_text):
            return "print" not in (media_text or "").lower()
    root = _parse(html)
    urls = []
    for link in root.iter("link"):
        relations = (link.get("rel") or "").lower().split()
        href = link.get("href")
        if "stylesheet" in relations and "alternate" not in relations and href:
            if media_query_applies(link.get("media")):
                urls.append(urljoin(base_url, href))
    return urls


def visible_text_of_element(element, rules):
    """(visible_text, hidden_fragments) for one element of a page parsed with parse_document().

    Enclosing elements still apply: if an ancestor is hidden, the whole element is.
    """
    starting_background, ancestor_hiding = _ancestor_state(element, rules)
    if ancestor_hiding is not None:
        hidden_fragments = []
        hidden_text = _collapse_whitespace(element.text_content())
        if hidden_text:
            hidden_fragments.append(
                HiddenFragment(hidden_text, ancestor_hiding[0], "hidden_element", ancestor_hiding[1], element)
            )
        return "", hidden_fragments
    visible_parts = []
    hidden_fragments = []
    _visit(element, starting_background, rules, visible_parts, hidden_fragments)
    return _collapse_whitespace("".join(visible_parts)), hidden_fragments


def extract_visible_text(html, headline_xpath=None, stylesheets=None):
    """Returns (visible_text, hidden_fragments) for an HTML headline or page.

    With headline_xpath (for example "//h1"), only the first matching element is
    read, but <style> rules and enclosing elements of the whole page still apply.
    Returns (None, []) when the xpath matches nothing.
    """
    root, rules = parse_document(html, stylesheets)
    if headline_xpath is None:
        return visible_text_of_element(root, rules)
    matches = root.xpath(headline_xpath)
    if not matches:
        return None, []
    return visible_text_of_element(matches[0], rules)
