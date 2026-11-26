"""Separates the text a reader sees from text hidden in the HTML.

This works without a browser. It understands inline styles, the `hidden` attribute,
<template>/<noscript>/<datalist>, a <title> in the body, closed <details>, SVG text that is
not drawn (tooltips, text outside <text>, definitions, <switch> branches), old presentational
attributes (<font color>, bgcolor), comments, and CSS rules: with tinycss2 and cssselect2
installed, a real cascade (see css_cascade); otherwise simple `.class`, `#id` and `tag` rules in
<style> blocks.

"Hidden" includes "practically invisible": tiny fonts, near-zero opacity, text whose
color barely differs from its background, text collapsed onto itself, text covered by
an opaque overlay drawn over its box, and text drawn behind an enclosing background.

Without layout it cannot see overlap between unrelated parts of the page, and it never
runs JavaScript. For those, render the page in a browser (browser_visibility).
"""

import re
import sys
import unicodedata
from dataclasses import dataclass, replace
from typing import NamedTuple

from lxml import etree

from .css_hiding import (
    CLIPPED_BOX_MAXIMUM_PIXELS, MINIMUM_VISIBLE_CONTRAST, MINIMUM_VISIBLE_OPACITY, OPAQUE_ALPHA, colors_in,
    contrast_ratio, declared_background_color, filter_hiding, any_offset_is_off_screen,
    font_shorthand_is_unreadable, font_size_is_unreadable, is_covering_overlay, is_off_screen_offset,
    letters_collapsed, line_height_collapsed, opacity_is_invisible, scale_is_zero, translation_is_off_screen,
    z_index_is_negative,
)
from .css_values import length_in_pixels, parse_color, plain_number, with_math_evaluated
from .document_mode import is_quirks_mode
from .html_tree import PageTooComplex, parse_html

# Contents are code or metadata, never headline text, so they are skipped without a flag.
NON_TEXT_TAGS = {"script", "style", "head", "meta", "link"}
# Contents are text a browser does not display.
HIDDEN_CONTENT_TAGS = {"template", "noscript", "datalist", "title"}
BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "details", "summary",
}

# When no background is declared, assume the usual white page; an external stylesheet may disagree.
ASSUMED_PAGE_BACKGROUND = (255, 255, 255)
# Fewer strong left-to-right letters than this under a right-to-left override is not reordered text.
MINIMUM_REORDERED_LETTERS = 2

HIGH = "high"
MEDIUM = "medium"
SCREEN_READER_ONLY_REASON = "screen-reader-only box"

POSITIONED = ("relative", "absolute", "fixed", "sticky")

# SVG, as Chrome 157 draws it (see tests/test_svg_text.py).
SVG_DEFINITION_TAGS = {"defs", "symbol", "mask", "clippath", "pattern", "marker"}
# The only requiredExtensions Chrome supports.
SVG_SUPPORTED_EXTENSIONS = {"http://www.w3.org/1999/xhtml", "http://www.w3.org/1998/Math/MathML"}
# An SVG length or percentage, as the width and height attributes and properties take it.
_SVG_LENGTH = re.compile(
    r"([+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?)"
    r"(px|em|ex|ch|rem|vw|vh|vmin|vmax|in|cm|mm|q|pt|pc|%)?"
)
_OVERFLOW_KEYWORDS = {"visible", "hidden", "clip", "scroll", "auto"}
_DIGIT_RUN = re.compile(r"\d+")
# SVG presentation attributes read when their value hides text. Lengths are in the drawing's user
# units, which a viewBox or a transform may scale up; a font-size is read as CSS reads it only
# where nothing does, and otherwise counts only when it is zero.
SVG_HIDING_ATTRIBUTES = ("display", "visibility", "opacity", "font-size", "transform", "clip-path", "filter")
_ZERO_SCALE = re.compile(r"scale[xy]?\(0(\.0*)?[,)]")
# How SVG text is painted: inherited properties, with their initial values.
SVG_PAINT_PROPERTIES = {
    "fill": "black", "fill-opacity": "1", "stroke": "none", "stroke-opacity": "1", "stroke-width": "1",
    "color": "black",
}
# Elements whose paint may be what SVG text is drawn on.
SVG_SHAPE_TAGS = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "image", "use", "foreignobject"}
# The elements a url() paint can use.
SVG_PAINT_SERVER_TAGS = {"lineargradient", "radialgradient", "pattern"}
GRADIENT_TAGS = ("lineargradient", "radialgradient")
# Gradient attributes that place it other than across the painted box from left to right.
GRADIENT_GEOMETRY_ATTRIBUTES = ("x1", "y1", "x2", "y2", "gradientunits", "gradienttransform")
SVG_BASIC_SHAPE_TAGS = ("rect", "circle", "ellipse", "line", "polyline", "polygon", "path")
# Children that draw nothing where they stand.
SVG_NON_RENDERING_TAGS = SVG_DEFINITION_TAGS | SVG_PAINT_SERVER_TAGS | {
    "title", "desc", "metadata", "style", "script", "filter",
}


class Hiding(NamedTuple):
    """Why text is hidden: the reason in words (read by gate scripts), how severe it is, the cause
    (a name from docs/report_format.md, "Causes") and the CSS rule when a rule hides it."""
    reason: str
    severity: str  # "high", or "medium" when hiding depends on a guess
    cause: str
    css: str = None


@dataclass
class HiddenFragment:
    text: str
    reason: str
    kind: str      # "hidden_element", "html_comment" or "reordered_text"
    severity: str  # "high", or "medium" when hiding depends on a guessed page background
    element: object = None  # the lxml element (or comment) that is hidden
    # For loose text rather than an element: (element, "text") or (element, "tail").
    text_of: tuple = None
    # Whether a browser's rendering decides it (SVG text placed outside its drawing).
    settled_by_rendering: bool = False
    # The cause of hiding (every hidden element has one) and the CSS rule, when a rule hides or
    # reorders the text (reordered text has one).
    cause: str = None
    css: str = None

    def __post_init__(self):
        if self.kind == "hidden_element" and self.cause is None:
            raise ValueError(f"hidden text without a cause: {self.reason}")
        if self.kind == "reordered_text" and self.css is None:
            raise ValueError(f"reordered text without a rule: {self.reason}")

    @classmethod
    def hidden(cls, text, hiding, element=None, text_of=None, settled_by_rendering=False):
        return cls(text, hiding.reason, "hidden_element", hiding.severity, element, text_of,
                   settled_by_rendering, hiding.cause, hiding.css)


CLOSED_DETAILS_HIDING = Hiding("inside a closed <details>", HIGH, "closed_details")
COVERED_BY_OVERLAY_HIDING = Hiding("covered by an opaque overlay drawn over it", HIGH, "covered")
SVG_TEXT_OUTSIDE_TEXT_HIDING = Hiding("SVG text outside <text>", HIGH, "svg_not_drawn")


def _parse_declarations(style_text):
    declarations = {}
    for declaration in style_text.split(";"):
        if ":" not in declaration:
            continue
        property_name, value = declaration.split(":", 1)
        value = with_math_evaluated(value.replace("!important", "").strip().lower())
        declarations[property_name.strip().lower()] = value
    return declarations


def _text_painted_another_way(declarations):
    """Transparent text that is still drawn: by a background clipped to the text, or a shadow."""
    clip = declarations.get("background-clip", "") + " " + declarations.get("-webkit-background-clip", "")
    if "text" in clip.split():
        background = declarations.get("background", "") + " " + declarations.get("background-image", "")
        if "gradient(" in background or "url(" in background:
            return True
        background_color = declared_background_color(declarations)
        if background_color is not None:  # declared_background_color drops colors below MINIMUM_VISIBLE_OPACITY
            return True
    for shadow_color in colors_in(declarations.get("text-shadow", "")):
        if shadow_color[3] >= MINIMUM_VISIBLE_OPACITY:
            return True
    return False


def _text_color(declarations):
    """(parsed color, the property that declares it, its declared value) for the color glyphs are
    filled with, or (None, None, None)."""
    fill = declarations.get("-webkit-text-fill-color")
    if fill and fill not in ("currentcolor", "inherit", "initial", "unset", "revert"):
        parsed = parse_color(fill)
        if parsed is not None:
            return parsed, "-webkit-text-fill-color", fill
    color = declarations.get("color")
    return parse_color(color), "color", color


def _hiding_from_declarations(declarations, background_color, background_lookup=None, painted_by_fill=False):
    """Returns a Hiding when the declarations hide text, otherwise None.

    background_lookup: when the rules can compute an element's real background from the
    stylesheets, it is asked only here, for elements whose text color matters.
    painted_by_fill: an SVG element, whose text is painted with fill and stroke, not color
    (see _svg_paint_hiding).
    """
    if declarations.get("display") == "none":
        return Hiding("display:none", HIGH, "display_none", "display:none")
    if declarations.get("content-visibility") == "hidden":
        return Hiding("content-visibility:hidden", HIGH, "content_visibility_hidden", "content-visibility:hidden")
    if declarations.get("visibility") in ("hidden", "collapse"):
        rule = "visibility:" + declarations["visibility"]
        return Hiding(rule, HIGH, "visibility_hidden", rule)
    if "opacity" in declarations and opacity_is_invisible(declarations["opacity"]):
        rule = f"opacity:{declarations['opacity']}"
        return Hiding(rule, HIGH, "transparent", rule)
    filter_cause_and_rule = filter_hiding(declarations.get("filter"))
    if filter_cause_and_rule is not None:
        cause, rule = filter_cause_and_rule
        return Hiding(rule, HIGH, cause, rule)
    if "font-size" in declarations and font_size_is_unreadable(declarations["font-size"]):
        rule = "font-size:" + declarations["font-size"]
        return Hiding(rule, HIGH, "tiny_font", rule)
    if "font" in declarations and font_shorthand_is_unreadable(declarations["font"]):
        rule = "font:" + declarations["font"]
        return Hiding(rule, HIGH, "tiny_font", rule)
    if letters_collapsed(declarations.get("letter-spacing")):
        rule = "letter-spacing:" + declarations["letter-spacing"]
        return Hiding(rule + " draws the letters on top of each other", HIGH, "letters_stacked", rule)

    text_color, color_property, declared_color = (None, None, None) if painted_by_fill else _text_color(declarations)
    if text_color is not None and not _text_painted_another_way(declarations):
        color_rule = f"{color_property}:{declared_color}"
        if text_color[3] < MINIMUM_VISIBLE_OPACITY:
            return Hiding("transparent text color", HIGH, "transparent", color_rule)
        if background_lookup is not None:
            background_color = background_lookup()
        if background_color is not None:
            if contrast_ratio(text_color, background_color) < MINIMUM_VISIBLE_CONTRAST:
                return Hiding(f"text color {declared_color} nearly matches its background", HIGH,
                              "same_color_as_background", color_rule)
        elif contrast_ratio(text_color, ASSUMED_PAGE_BACKGROUND) < MINIMUM_VISIBLE_CONTRAST:
            return Hiding(
                f"text color {declared_color} is invisible on a white page "
                "(page background not declared here, so this is a guess)",
                MEDIUM, "same_color_as_background", color_rule,
            )

    clip = declarations.get("clip", "").replace(" ", "").replace("px", "")
    if clip.startswith("rect(0,0,0,0") or clip.startswith("rect(0000"):
        return Hiding("clip:rect(0 0 0 0)", HIGH, "clipped", "clip:" + declarations["clip"])
    clip_path = declarations.get("clip-path", "").replace(" ", "")
    if clip_path.startswith("inset(50%") or clip_path.startswith("circle(0"):
        return Hiding("clip-path", HIGH, "clipped", "clip-path:" + declarations["clip-path"])
    transform = declarations.get("transform", "").replace(" ", "")
    if re.search(r"scale[xy]?\(0(\.0*)?[,)]", transform):
        return Hiding("transform:scale(0)", HIGH, "scaled_to_zero", "transform:" + declarations["transform"])
    if scale_is_zero(declarations.get("scale", "")):
        return Hiding("scale:0", HIGH, "scaled_to_zero", "scale:" + declarations["scale"])
    if translation_is_off_screen(declarations.get("transform"), declarations.get("translate")):
        moving_property = "transform" if translation_is_off_screen(declarations.get("transform"), None) else "translate"
        return Hiding("moved off-screen by a transform", HIGH, "off_screen",
                      f"{moving_property}:{declarations[moving_property]}")

    overflow_words = []
    for overflow_property in ("overflow", "overflow-x", "overflow-y"):
        for word in declarations.get(overflow_property, "").split():
            overflow_words.append(word)
    if "hidden" in overflow_words or "clip" in overflow_words:
        clipping = "overflow:hidden" if "hidden" in overflow_words else "overflow:clip"
        for size_property in ("width", "height", "max-width", "max-height"):
            if size_property in declarations:
                pixels = length_in_pixels(declarations[size_property])
                if pixels is not None and pixels <= CLIPPED_BOX_MAXIMUM_PIXELS:
                    reason = f"{size_property}:{declarations[size_property]} with overflow:hidden"
                    rule = f"{size_property}:{declarations[size_property]}; {clipping}"
                    if pixels > 0:
                        # The usual "visually hidden" pattern for labels read only by screen readers.
                        return Hiding(f"{SCREEN_READER_ONLY_REASON} ({reason})", HIGH, "screen_reader_only", rule)
                    return Hiding(reason, HIGH, "clipped", rule)
        line_height = declarations.get("line-height")
        if line_height is not None and "height" not in declarations and "min-height" not in declarations:
            if line_height_collapsed(line_height):
                return Hiding(f"line-height:{line_height} with overflow:hidden", HIGH, "clipped",
                              f"line-height:{line_height}; {clipping}")
    if declarations.get("position") in ("absolute", "fixed"):
        for offset_property in ("left", "top", "right", "bottom", "margin-left", "margin-top", "inset"):
            offset_value = declarations.get(offset_property, "")
            if any_offset_is_off_screen(offset_value):
                return Hiding(f"positioned off-screen ({offset_property}:{offset_value})", HIGH, "off_screen",
                              f"{offset_property}:{offset_value}")
    if is_off_screen_offset(declarations.get("text-indent", "")):
        return Hiding("text-indent off-screen", HIGH, "off_screen", "text-indent:" + declarations["text-indent"])
    return None


# ---- overlays and stacking ------------------------------------------------

def _full_declarations(rules, element):
    """Every winning declaration of an element (the real cascade when the rules have one)."""
    if hasattr(rules, "full_declarations"):
        return rules.full_declarations(element)
    tag = element.tag.lower() if isinstance(element.tag, str) else ""
    return rules.declarations_for(element, tag)


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
        if is_covering_overlay(declarations):
            return Hiding(f"covered by its own ::{pseudo_name} overlay", HIGH, "covered")
    return None


def _covering_child(element, rules):
    """The child element that is an opaque overlay over element's content, or None."""
    for child in element:
        if not isinstance(child.tag, str):
            continue
        child_tag = child.tag.lower()
        if child_tag in NON_TEXT_TAGS:
            continue
        if is_covering_overlay(_declarations_with_hints(rules, child, child_tag)):
            return child
        if hasattr(rules, "declaration_alternatives"):
            alternatives = rules.declaration_alternatives(child)
            if alternatives is None:
                return child  # too many undecided combinations to rule out an overlay
            for alternative in alternatives:
                if is_covering_overlay(alternative):
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
    if not z_index_is_negative(declarations.get("z-index", "")):
        return None
    for ancestor in element.iterancestors():
        if not isinstance(ancestor.tag, str) or ancestor.tag.lower() in ("body", "html"):
            return None
        ancestor_declarations = _full_declarations(rules, ancestor)
        if _creates_stacking_context(ancestor_declarations):
            return None
        background = declared_background_color(ancestor_declarations)
        if background is not None and background[3] >= OPAQUE_ALPHA:
            return Hiding(f"drawn behind an enclosing background (z-index:{declarations['z-index']})", HIGH,
                          "behind_background", f"z-index:{declarations['z-index']}")
    return None


# ---- presentational HTML --------------------------------------------------

def _is_svg_element(element, tag):
    """Whether element is an SVG element: an <svg>, or inside one and not in a <foreignObject>'s HTML."""
    if tag == "svg":
        return True
    for ancestor in element.iterancestors():
        if not isinstance(ancestor.tag, str):
            continue
        ancestor_tag = ancestor.tag.lower()
        if ancestor_tag == "svg":
            return True
        if ancestor_tag == "foreignobject":
            return False
    return False


def _svg_attribute_value(element, name):
    """An SVG presentation attribute's value as CSS reads it, or None when it is not set."""
    value = element.get(name)
    if value is None:
        return None
    return with_math_evaluated(value.strip(" \t\n\f\r").lower())


def _svg_size(value):
    """"positive", "zero", "negative", "auto" (no size given) or "unknown" for a width or height."""
    if value is None or value in ("", "auto"):
        return "auto"
    match = _SVG_LENGTH.fullmatch(value)
    if match is None:
        return "unknown"
    number = float(match.group(1))
    if number > 0:
        return "positive"
    return "zero" if number == 0 else "negative"


def _is_scaled_svg(element):
    """Whether a viewBox or a transform attribute on element or an enclosing SVG element may make
    element's user units differ from CSS pixels."""
    node = element
    while node is not None and isinstance(node.tag, str):
        tag = node.tag.lower()
        if tag == "foreignobject" and node is not element:
            return False
        if node.get("transform") is not None or (tag == "svg" and node.get("viewbox") is not None):
            return True
        node = node.getparent()
    return False


def _svg_attribute_hides(name, value, element):
    if name == "display":
        return value == "none"
    if name == "visibility":
        return value in ("hidden", "collapse")
    if name == "opacity":
        return opacity_is_invisible(value)
    if name == "font-size":
        if _svg_size(value) == "zero":
            return True
        return font_size_is_unreadable(value) and not _is_scaled_svg(element)
    if name == "transform":
        return _ZERO_SCALE.search(value) is not None
    if name == "clip-path":
        return value.replace(" ", "").startswith(("inset(50%", "circle(0"))
    return filter_hiding(value) is not None


def _is_valid_css_value(name, value):
    """False when CSS rejects value for the property (then Chrome ignores the attribute)."""
    try:
        import tinycss2

        from .css_validity import INVALID, QUIRKS_ONLY, declaration_validity
    except ImportError:
        return True
    try:
        tokens = tinycss2.parse_component_value_list(value)
    except ValueError:
        return True  # a number too long for tinycss2 to read; the value is judged as written
    validity = declaration_validity(name, tokens)
    return validity not in (INVALID, QUIRKS_ONLY)


def _has_svg_hiding_attribute(element):
    for name in SVG_HIDING_ATTRIBUTES:
        if element.get(name) is not None:
            return True
    return False


def _svg_presentation_hints(element, tag):
    """Styles set by SVG presentation attributes that can hide text, as Chrome reads them: CSS
    wins over them, and a value they cannot take is ignored."""
    hints = {}
    for name in SVG_HIDING_ATTRIBUTES:
        value = _svg_attribute_value(element, name)
        if value is None:
            continue
        if name == "font-size":
            length = _SVG_LENGTH.fullmatch(value)
            if length is not None:
                if length.group(2) is None:
                    value += "px"  # SVG attributes take lengths without a unit, in user units
                # Written plainly ("1e0" is "1"), as the CSS checks read numbers.
                number = f"{float(length.group(1)):.6f}".rstrip("0").rstrip(".")
                value = (number if number not in ("", "-0") else "0") + (length.group(2) or "px")
        if name == "transform":
            # The attribute separates numbers with spaces or commas, CSS with commas.
            value = re.sub(r"\s+", ",", re.sub(r"\s*([(),])\s*", r"\1", value))
        elif not _is_valid_css_value(name, value):
            continue
        if _svg_attribute_hides(name, value, element):
            hints[name] = value
    if tag == "foreignobject":
        for name in ("width", "height"):
            value = _svg_attribute_value(element, name)
            if value is not None and _svg_size(value) != "unknown":
                hints[name] = value
        overflow = _svg_attribute_value(element, "overflow")
        if overflow in _OVERFLOW_KEYWORDS:
            hints["overflow"] = overflow
    elif tag == "svg":
        for name in ("width", "height"):
            value = _svg_attribute_value(element, name)
            if value is not None and _svg_size(value) == "zero":
                hints[name] = value
    return hints


def _svg_size_hiding(tag, declarations):
    """Why an <svg> or <foreignObject> paints nothing because of its size, or None."""
    if tag == "svg":
        for name in ("width", "height"):
            if _svg_size(declarations.get(name)) == "zero":
                return Hiding(f"zero-size <svg> ({name}:{declarations[name]})", HIGH, "svg_not_drawn")
        return None
    overflow_words = declarations.get("overflow", "").split()
    overflow_x = declarations.get("overflow-x") or (overflow_words[0] if overflow_words else "")
    overflow_y = declarations.get("overflow-y") or (overflow_words[-1] if overflow_words else "")
    if overflow_x == "visible" and overflow_y == "visible":
        return None
    for name in ("width", "height"):
        if _svg_size(declarations.get(name)) != "positive":
            return Hiding(f"SVG <foreignObject> with no {name}, which clips its content away", HIGH, "svg_not_drawn")
    return None


def _presentational_hints(element, tag):
    """Styles set by old HTML attributes (<font color>, bgcolor) and by SVG presentation attributes."""
    hints = None
    if (tag in ("svg", "foreignobject") or _has_svg_hiding_attribute(element)) and _is_svg_element(element, tag):
        hints = _svg_presentation_hints(element, tag) or None
    if tag == "font" and element.get("color"):
        hints = {"color": element.get("color").strip().lower()}
    bgcolor = element.get("bgcolor")
    if bgcolor:
        if hints is None:
            hints = {}
        hints["background-color"] = bgcolor.strip().lower()
    return hints


def _declarations_with_hints(rules, element, tag):
    hints = _presentational_hints(element, tag)
    if hints is None and tag != "foreignobject":
        return rules.declarations_for(element, tag)
    # Every winning declaration: CSS overrides a hint even with a value that cannot hide, and
    # sizes a <foreignObject>.
    declarations = _full_declarations(rules, element)
    if hints is None:
        return declarations
    merged = dict(hints)
    merged.update(declarations)
    return merged


@dataclass(frozen=True)
class _SvgPlace:
    """Where an element's children sit inside an <svg>, which decides what they draw. Outside SVG,
    and inside <foreignObject>, the place is None."""
    in_text: bool                  # inside <text>, where text is drawn
    inside_link: bool = False      # an <a> here would be nested in another <a>, which draws nothing
    allows_text_path: bool = False
    in_switch: bool = False        # the children of a <switch>, which draws only switch_choice
    switch_choice: object = None
    off_drawing: tuple = None      # (reason, severity) when the <text> lies outside its drawing


_SVG_ROOT_PLACE = _SvgPlace(in_text=False)


def _svg_condition(element):
    """"holds", "fails" or "unknown": the element's SVG conditional attributes, as Chrome reads them."""
    extensions = element.get("requiredextensions")
    if extensions is not None:
        names = re.split(r"[ \t\n\f\r]+", extensions.strip(" \t\n\f\r"))
        for name in names:
            if name not in SVG_SUPPORTED_EXTENSIONS:
                return "fails"
    if element.get("systemlanguage") is not None:
        return "unknown"  # it names languages, and holds when one is the browser's
    return "holds"


def _switch_choice(switch):
    """The child a <switch> draws: its first element child whose conditions hold, or None when
    none does or the choice depends on the browser."""
    for child in switch:
        if not isinstance(child.tag, str):
            continue
        condition = _svg_condition(child)
        if condition == "holds":
            return child
        if condition == "unknown":
            return None
    return None


def _svg_place(parent_place, element, tag):
    """(place of element's children, the reason element draws nothing or None). parent_place is
    the place element sits in."""
    if parent_place is None:
        if tag != "svg":
            return None, None
        parent_place = _SVG_ROOT_PLACE
    if tag in ("title", "desc"):
        return None, "SVG tooltip text"
    if parent_place.in_switch and element is not parent_place.switch_choice:
        return None, "SVG <switch> draws another child"
    condition = _svg_condition(element)
    if condition == "fails":
        return None, "SVG requiredExtensions the browser lacks"
    if condition == "unknown":
        return None, "SVG systemLanguage, drawn only for some browser languages"
    if parent_place.in_text:
        if tag == "tspan":
            return _SvgPlace(in_text=True, inside_link=parent_place.inside_link,
                             off_drawing=parent_place.off_drawing), None
        if tag == "textpath" and parent_place.allows_text_path:
            return _SvgPlace(in_text=True, inside_link=parent_place.inside_link,
                             off_drawing=parent_place.off_drawing), None
        if tag == "a" and not parent_place.inside_link:
            return _SvgPlace(in_text=True, inside_link=True, allows_text_path=parent_place.allows_text_path,
                             off_drawing=parent_place.off_drawing), None
        return None, "SVG element that draws no text inside <text>"
    if tag == "foreignobject":
        return None, None
    if tag == "text":
        return _SvgPlace(in_text=True, allows_text_path=True), None
    if tag in ("svg", "g"):
        return _SvgPlace(in_text=False, inside_link=parent_place.inside_link), None
    if tag == "switch":
        return _SvgPlace(in_text=False, inside_link=parent_place.inside_link, in_switch=True,
                         switch_choice=_switch_choice(element)), None
    if tag == "a" and not parent_place.inside_link:
        return _SvgPlace(in_text=False, inside_link=True), None
    if tag in SVG_DEFINITION_TAGS:
        return None, "SVG definitions, drawn only where something references them"
    return None, "SVG element that draws no text"


def _is_closed_details(element, tag):
    return tag == "details" and element.get("open") is None


def _reordering(element, tag, declarations):
    """(reason, rule) for a right-to-left override of left-to-right letters, which the reader sees
    in reverse order; None when there is none."""
    if tag == "bdo":
        direction = (element.get("dir") or "").lower()
        if direction != "rtl":
            return None
        reason = rule = '<bdo dir="rtl">'
    elif declarations.get("unicode-bidi") in ("bidi-override", "isolate-override"):
        direction = declarations.get("direction") or (element.get("dir") or "").lower()
        if not direction:
            for ancestor in element.iterancestors():
                if isinstance(ancestor.tag, str) and ancestor.get("dir"):
                    direction = ancestor.get("dir").lower()
                    break
        if direction != "rtl":
            return None
        rule = "unicode-bidi:" + declarations["unicode-bidi"]
        reason = rule + " with direction:rtl"
    else:
        return None
    left_to_right_letters = 0
    for character in element.text_content():
        if unicodedata.bidirectional(character) == "L":
            left_to_right_letters += 1
    if left_to_right_letters < MINIMUM_REORDERED_LETTERS:
        return None
    return reason, rule


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


def _collapse_whitespace(text):
    return re.sub(r"\s+", " ", text).strip()


def _background_lookup(rules, element):
    """A function giving the element's real background, when the rules can compute it."""
    if not hasattr(rules, "background_for"):
        return None

    def lookup():
        return rules.background_for(element)
    return lookup


def _element_hiding(element, tag, rules, inherited_background, svg_place):
    """(a Hiding or None, background, declarations or None, SVG place of its children) for
    one element in svg_place: why it is hidden, the background its children inherit, its declarations
    (None when markup alone hides it), and where its children sit in an SVG."""
    children_place, svg_reason = _svg_place(svg_place, element, tag)
    if svg_reason is not None:
        return Hiding(svg_reason, HIGH, "svg_not_drawn"), inherited_background, None, None
    if tag in HIDDEN_CONTENT_TAGS:
        return Hiding(f"inside <{tag}>", HIGH, "not_rendered_element"), inherited_background, None, None
    if element.get("hidden") is not None:
        return Hiding("hidden attribute", HIGH, "hidden_attribute"), inherited_background, None, None
    if tag == "input" and (element.get("type") or "").lower() == "hidden":
        return Hiding("hidden input", HIGH, "hidden_input"), inherited_background, None, None
    declarations = _declarations_with_hints(rules, element, tag)
    if tag == "svg" or (tag == "foreignobject" and svg_place is not None):
        size_hiding = _svg_size_hiding(tag, declarations)
        if size_hiding is not None:
            return size_hiding, inherited_background, declarations, None
    if tag == "foreignobject" and svg_place is not None and "color" not in declarations:
        color_hiding = _foreign_object_color_hiding(element, rules, inherited_background)
        if color_hiding is not None:
            return color_hiding, inherited_background, declarations, None
    own_background = declared_background_color(declarations)
    if own_background is not None:
        inherited_background = own_background
    hiding = _hiding_from_declarations(
        declarations, inherited_background, _background_lookup(rules, element),
        _is_painted_by_fill(tag, svg_place is not None or tag == "svg"),
    )
    if hiding is None:
        hiding = _drawn_behind_background(element, declarations, rules)
    if hiding is None:
        pseudo_overlay = _covering_pseudo_element(element, rules)
        if pseudo_overlay is not None and _has_positioned_container(element, rules):
            hiding = pseudo_overlay
    if hiding is None:
        hiding = _hiding_under_undecided_rules(element, tag, rules)
    if hiding is None and tag == "text" and children_place is not None and children_place.in_text:
        # Placed outside the drawing: its text is reported where nothing surer hides it (see _visit).
        children_place = replace(children_place, off_drawing=_svg_text_position_hiding(element, rules))
    return hiding, inherited_background, declarations, children_place


def _rule_worlds(rules, element):
    """The rules with every undecided CSS block applied, then (when such blocks can change how
    element is drawn) with none applied. See css_cascade.CascadeRules."""
    other_rules = getattr(rules, "without_undecided_blocks", None)
    if other_rules is None or not rules.undecided_rules_may_matter(element):
        return (rules,)
    return (rules, other_rules)


def _hiding_under_undecided_rules(element, tag, rules):
    """Why the element is hidden when only some of the page's undecided CSS blocks (@supports,
    @container, @scope) apply, as Chrome may apply any of them; None when no subset hides it."""
    if not hasattr(rules, "declaration_alternatives"):
        return None
    alternatives = rules.declaration_alternatives(element)
    if alternatives is None:
        return Hiding("CSS this reader cannot evaluate: too many rules under conditions it cannot answer "
                      "(@supports, @container, @scope), a value too long to resolve, or if(), attr() or a "
                      "custom function",
                      HIGH, "css_not_evaluated")
    hints = _presentational_hints(element, tag)
    sized_svg_element = tag == "svg" or (tag == "foreignobject" and _is_svg_element(element, tag))
    worlds = _rule_worlds(rules, element)
    # Asked only when some undecided CSS touches the element.
    painted_by_fill = (bool(alternatives) or len(worlds) > 1) and _is_painted_by_fill(tag, _is_svg_element(element, tag))
    parent = element.getparent()
    for alternative in alternatives:
        if hints is not None:
            merged = dict(hints)
            merged.update(alternative)
            alternative = merged

        def lookup(alternative=alternative):
            own_background = declared_background_color(alternative)
            if own_background is not None or parent is None:
                return own_background
            return rules.background_for(parent)
        hiding = _hiding_from_declarations(alternative, None, lookup, painted_by_fill)
        if hiding is None and sized_svg_element:
            hiding = _svg_size_hiding(tag, alternative)
        if hiding is None:
            hiding = _drawn_behind_background(element, alternative, rules)
        if hiding is not None:
            return hiding
    for world_rules in worlds[1:]:
        declarations = _declarations_with_hints(world_rules, element, tag)
        hiding = _hiding_from_declarations(
            declarations, None, _background_lookup(world_rules, element), painted_by_fill)
        if hiding is not None:
            return hiding
        if sized_svg_element:
            size_hiding = _svg_size_hiding(tag, declarations)
            if size_hiding is not None:
                return size_hiding
        behind = _drawn_behind_background(element, declarations, world_rules)
        if behind is not None:
            return behind
        pseudo_overlay = _covering_pseudo_element(element, world_rules)
        if pseudo_overlay is not None and _has_positioned_container(element, world_rules):
            return pseudo_overlay
    return None


def _overlay_over_content(element, rules, skip_child=None):
    """A child drawn as an opaque overlay over element's content (in either rule world), or None."""
    for world_rules in _rule_worlds(rules, element):
        overlay = _covering_child(element, world_rules)
        if overlay is not None and overlay is not skip_child and _has_positioned_container(element, world_rules):
            return overlay
    return None


def _ancestor_state(element, rules):
    """Background color, hiding and SVG place inherited from the element's ancestors, outermost first."""
    ancestors = []
    for ancestor in element.iterancestors():
        ancestors.append(ancestor)
    ancestors.reverse()
    inherited_background = None
    svg_place = None
    path = ancestors + [element]
    for position, ancestor in enumerate(ancestors):
        ancestor_tag = ancestor.tag.lower() if isinstance(ancestor.tag, str) else ""
        hiding, inherited_background, _, svg_place = _element_hiding(
            ancestor, ancestor_tag, rules, inherited_background, svg_place
        )
        if hiding is not None:
            return inherited_background, hiding._replace(reason=f"an enclosing element is hidden ({hiding.reason})"), None
        child_on_path = path[position + 1]
        if _is_closed_details(ancestor, ancestor_tag):
            child_tag = child_on_path.tag.lower() if isinstance(child_on_path.tag, str) else ""
            if child_tag != "summary":
                return inherited_background, CLOSED_DETAILS_HIDING, None
        if _overlay_over_content(ancestor, rules, skip_child=child_on_path) is not None:
            return inherited_background, COVERED_BY_OVERLAY_HIDING, None
    return inherited_background, None, svg_place


def _text_outside_code(element):
    """element's text, as text_content() gives it, without what is inside <style>, <script> and
    the other NON_TEXT_TAGS."""
    parts = []
    pending = [element]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item.tag, str) or item.tag.lower() in NON_TEXT_TAGS:
            continue
        if item.text:
            parts.append(item.text)
        for child in reversed(item):
            if child.tail:
                pending.append(child.tail)
            pending.append(child)
    return "".join(parts)


def _hide_loose_content(element, keep_child, hiding, hidden_fragments):
    """Records element's own text, tails and children (except keep_child) as hidden."""
    if element.text and element.text.strip():
        hidden_fragments.append(HiddenFragment.hidden(
            _collapse_whitespace(element.text), hiding, text_of=(element, "text"),
        ))
    for child in element:
        if child is not keep_child and isinstance(child.tag, str):
            child_text = _collapse_whitespace(_text_outside_code(child))
            if child_text:
                hidden_fragments.append(HiddenFragment.hidden(child_text, hiding, child))
        if child.tail and child.tail.strip():
            hidden_fragments.append(HiddenFragment.hidden(
                _collapse_whitespace(child.tail), hiding, text_of=(child, "tail"),
            ))


def _record_undrawn_svg_text(text, owner, hidden_fragments, hiding=SVG_TEXT_OUTSIDE_TEXT_HIDING,
                             settled_by_rendering=False):
    if text and text.strip():
        hidden_fragments.append(HiddenFragment.hidden(
            _collapse_whitespace(text), hiding, text_of=owner, settled_by_rendering=settled_by_rendering,
        ))


def _is_painted_by_fill(tag, is_svg_element):
    """SVG elements paint text with fill and stroke; a <foreignObject>'s content is HTML, colored by color."""
    return is_svg_element and tag != "foreignobject"


# Values that leave an inherited property to the parent.
_INHERITING_VALUES = (None, "", "inherit", "unset", "revert", "revert-layer")
# How many gradients a url() paint follows through href before giving up (Chrome stops at cycles).
MAXIMUM_GRADIENT_LINKS = 16


class _SvgPaintCache:
    """Per rule world: each element's inherited paint, whether it is an SVG element, its font size
    estimate, where it sits in a drawing and whether its text is anchored at its start; per page:
    elements by id, whether each drawing holds shapes and the ids <use> and animations point at."""

    def __init__(self):
        self.paint = {}
        self.svg_elements = {}
        self.ids = None
        self.has_shapes = {}
        self.referenced_ids = None
        self.font_pixels = {}
        self.drawing = {}
        self.anchored = {}


def _paint_cache(rules):
    cache = getattr(rules, "_svg_paint_cache", None)
    if cache is None:
        cache = _SvgPaintCache()
        rules._svg_paint_cache = cache
    return cache


def _is_svg_element_cached(cache, node):
    """_is_svg_element, remembered for every element on the way up."""
    chain = []
    current = node
    while current is not None and isinstance(current.tag, str) and current not in cache.svg_elements:
        chain.append(current)
        current = current.getparent()
    known = cache.svg_elements.get(current, False) if current is not None else False
    parent_tag = current.tag.lower() if current is not None and isinstance(current.tag, str) else ""
    for member in reversed(chain):
        tag = member.tag.lower()
        if tag == "svg":
            known = True
        elif parent_tag == "foreignobject" and known:
            known = False  # the HTML content of a <foreignObject>
        cache.svg_elements[member] = known
        parent_tag = tag
    return cache.svg_elements[node]


def _svg_own_value(rules, cache, node, name):
    """The value node itself gives property name (CSS over its presentation attribute), or None
    when it leaves it to its parent."""
    value = _full_declarations(rules, node).get(name)
    if value in _INHERITING_VALUES:
        value = None
        if node.get(name) is not None and _is_svg_element_cached(cache, node):
            value = _svg_attribute_value(node, name)
            if not _is_valid_css_value(name, value) or value == "inherit":
                value = None
    if value == "initial":
        return SVG_PAINT_PROPERTIES[name]
    return value


def _svg_paint(rules, element):
    """element's fill, fill-opacity, stroke, stroke-opacity, stroke-width and color, inherited
    from any ancestor; each element's is computed once."""
    cache = _paint_cache(rules)
    chain = []
    current = element
    while current is not None and isinstance(current.tag, str) and current not in cache.paint:
        chain.append(current)
        current = current.getparent()
    paint = cache.paint[current] if current is not None and current in cache.paint else SVG_PAINT_PROPERTIES
    for member in reversed(chain):
        own = None
        for name in SVG_PAINT_PROPERTIES:
            value = _svg_own_value(rules, cache, member, name)
            if value is not None:
                if own is None:
                    own = dict(paint)
                own[name] = value
        if own is not None:
            paint = own
        cache.paint[member] = paint
    return paint


def _element_with_id(rules, element, identifier):
    cache = _paint_cache(rules)
    if cache.ids is None:
        cache.ids = {}
        for node in element.getroottree().iter():
            if isinstance(node.tag, str):
                node_id = node.get("id")
                if node_id is not None and node_id not in cache.ids:
                    cache.ids[node_id] = node
    return cache.ids.get(identifier)


def _stop_property(rules, element, name, initial):
    """element's stop-color or stop-opacity. Neither is inherited: inherit (in CSS or the attribute)
    takes the parent's, initial, unset and revert give the initial value, and revert-layer the attribute."""
    cache = _paint_cache(rules)
    node = element
    while node is not None and isinstance(node.tag, str):
        value = _full_declarations(rules, node).get(name)
        if value in ("initial", "unset", "revert"):
            return initial
        if value in (None, "", "revert-layer"):
            value = _svg_attribute_value(node, name) if _is_svg_element_cached(cache, node) else None
            if value is None or value in ("initial", "unset", "revert", "revert-layer"):
                return initial
            if value != "inherit" and not _is_valid_css_value(name, value):
                return initial
        if value != "inherit":
            return value
        node = node.getparent()
    return initial


def _opacity_number(value):
    """An opacity value as a number from 0 to 1, or None when it cannot be read."""
    number = plain_number(value.rstrip("%"))
    if number is None:
        return None
    if value.endswith("%"):
        number /= 100
    return min(max(number, 0.0), 1.0)


def _linked_paint_server(rules, node, tags):
    """The SVG element with one of tags that node's href points at, or None."""
    link = (node.get("href") or node.get("xlink:href") or "").strip()
    if not link.startswith("#"):
        return None
    target = _element_with_id(rules, node, link[1:])
    if target is None or target.tag.lower() not in tags or not _is_svg_element_cached(_paint_cache(rules), target):
        return None
    return target


def _stop_color(rules, stop):
    color_value = _stop_property(rules, stop, "stop-color", "black")
    if color_value == "currentcolor":
        color_value = _svg_paint(rules, stop)["color"]
    color = parse_color(color_value) or (0, 0, 0, 1.0)
    opacity = _opacity_number(_stop_property(rules, stop, "stop-opacity", "1"))
    return color[:3] + (color[3] * (1.0 if opacity is None else opacity),)


def _gradient_colors(rules, gradient):
    """(the colors a gradient surely paints with, those it paints with only where its geometry
    reaches): a stop paints where it has width, and the first and last stops also fill what lies
    before and after them. Across the painted box from left to right (a linear gradient with no
    geometry of its own) that is exact; otherwise the stops between are taken as painted and the
    first and last as maybe."""
    stops = None
    placed = gradient.tag.lower() == "radialgradient"
    node = gradient
    for _ in range(MAXIMUM_GRADIENT_LINKS):
        if stops is None:
            own_stops = [child for child in node if isinstance(child.tag, str) and child.tag.lower() == "stop"]
            stops = own_stops or None
        if (any(node.get(name) is not None for name in GRADIENT_GEOMETRY_ATTRIBUTES)
                or _full_declarations(rules, node).get("transform", "none") != "none"):
            placed = True
        node = _linked_paint_server(rules, node, GRADIENT_TAGS)
        if node is None:
            break
    if stops is None:
        return [], []
    colors = []
    offsets = []
    largest = 0.0
    for stop in stops:
        largest = max(largest, _opacity_number((stop.get("offset") or "").strip(" \t\n\f\r")) or 0.0)
        offsets.append(largest)
        colors.append(_stop_color(rules, stop))
    if len(colors) == 1:
        return colors, []
    last = len(colors) - 1
    sure = []
    maybe = []
    for index, color in enumerate(colors):
        between = ((index > 0 and offsets[index - 1] < offsets[index])
                   or (index < last and offsets[index] < offsets[index + 1]))
        padding = (index == 0 and offsets[0] > 0) or (index == last and offsets[last] < 1)
        if between or (padding and not placed):
            sure.append(color)
        elif placed and index in (0, last):
            maybe.append(color)
    return sure, maybe


def _pattern_child_draws(rules, child):
    """Whether a child of a <pattern> may draw: a basic shape when its fill or stroke shows; any
    other drawing element is not evaluated and taken as drawing."""
    tag = child.tag.lower()
    if tag in SVG_NON_RENDERING_TAGS:
        return False
    if tag not in SVG_BASIC_SHAPE_TAGS:
        return True
    paint = _svg_paint(rules, child)
    for name in ("fill", "stroke"):
        if name == "stroke" and _svg_size(paint["stroke-width"]) in ("zero", "negative"):
            continue
        if paint[name].startswith("url("):
            return True  # another paint server: not followed from inside a pattern
        for color in _paint_colors(rules, child, paint, name)[0]:
            if color[3] >= MINIMUM_VISIBLE_OPACITY:
                return True
    return False


def _pattern_paints(rules, pattern):
    """Whether a <pattern> paints: a positive width and height and content that draws (each its
    own, or from the pattern it links to by href)."""
    sizes = {"width": None, "height": None}
    content = None
    node = pattern
    for _ in range(MAXIMUM_GRADIENT_LINKS):
        for name in sizes:
            if sizes[name] is None and node.get(name) is not None:
                sizes[name] = _svg_size(_svg_attribute_value(node, name))
        if content is None:
            content = [child for child in node if isinstance(child.tag, str)] or None
        node = _linked_paint_server(rules, node, ("pattern",))
        if node is None:
            break
    if any(size in (None, "zero", "negative") for size in sizes.values()) or content is None:
        return False
    return any(_pattern_child_draws(rules, child) for child in content)


def _paint_colors(rules, element, paint, name):
    """(the colors a fill or stroke surely paints with, those it paints with only where a gradient's
    geometry reaches), alpha including its opacity; both empty when it paints nothing."""
    value = paint[name]
    colors = None
    maybe = []
    if value.startswith("url("):
        reference, _, fallback = value.partition(")")
        target = reference[4:].strip(" \t\n\f\r\"'")
        server = _element_with_id(rules, element, target[1:]) if target.startswith("#") else None
        if (server is None or server.tag.lower() not in SVG_PAINT_SERVER_TAGS
                or not _is_svg_element_cached(_paint_cache(rules), server)):
            value = fallback.strip() or "none"
        elif server.tag.lower() == "pattern":
            colors = [(0, 0, 0, 1.0)] if _pattern_paints(rules, server) else []  # its colors are not evaluated
        else:
            colors, maybe = _gradient_colors(rules, server)
    if colors is None:
        if value in ("none", "context-fill", "context-stroke"):
            return [], []
        if value == "currentcolor":
            value = paint["color"]
        colors = [parse_color(value) or (0, 0, 0, 1.0)]  # a color this reader cannot evaluate counts as painted
    opacity = _opacity_number(paint[name + "-opacity"])
    if opacity is None:
        return colors, maybe
    return ([color[:3] + (color[3] * opacity,) for color in colors],
            [color[:3] + (color[3] * opacity,) for color in maybe])


def _drawing_has_shapes(rules, element):
    """Whether the outermost <svg> around element holds an element whose paint text may lie on."""
    outermost = None
    for ancestor in element.iterancestors("svg"):
        outermost = ancestor
    if outermost is None:
        return False
    cache = _paint_cache(rules)
    if outermost not in cache.has_shapes:
        found = False
        for shape in outermost.iter():
            if isinstance(shape.tag, str) and shape.tag.lower() in SVG_SHAPE_TAGS:
                found = True
                break
        cache.has_shapes[outermost] = found
    return cache.has_shapes[outermost]


def _paint_hiding_in(rules, element, inherited_background):
    paint = _svg_paint(rules, element)
    colors, maybe = _paint_colors(rules, element, paint, "fill")
    if _svg_size(paint["stroke-width"]) not in ("zero", "negative"):
        stroke_colors, stroke_maybe = _paint_colors(rules, element, paint, "stroke")
        colors = colors + stroke_colors
        maybe = maybe + stroke_maybe
    shown = [color for color in colors if color[3] >= MINIMUM_VISIBLE_OPACITY]
    maybe_shown = [color for color in maybe if color[3] >= MINIMUM_VISIBLE_OPACITY]
    paint_values = f"fill:{paint['fill']}, stroke:{paint['stroke']}"
    if not shown and maybe_shown:
        return Hiding(f"SVG text painted only by gradient stops that may lie outside it ({paint_values})", MEDIUM,
                      "svg_not_painted")
    if not shown:
        return Hiding(f"SVG text painted with no visible fill or stroke ({paint_values})", HIGH, "svg_not_painted")
    background = rules.background_for(element) if hasattr(rules, "background_for") else inherited_background
    reference = background if background is not None else ASSUMED_PAGE_BACKGROUND
    for color in shown:
        if contrast_ratio(color, reference) >= MINIMUM_VISIBLE_CONTRAST:
            return None
    severity = HIGH
    if (background is None or _drawing_has_shapes(rules, element)
            or any(contrast_ratio(color, reference) >= MINIMUM_VISIBLE_CONTRAST for color in maybe_shown)):
        severity = MEDIUM  # the background is a guess, the text may lie on a shape, or a maybe-stop shows it
    return Hiding(f"SVG text fill {paint['fill']} nearly matches the background", severity, "svg_not_painted")


def _svg_paint_hiding(element, rules, inherited_background):
    """A Hiding when neither fill nor stroke shows element's own text, or None; with and
    without the undecided CSS blocks (see _rule_worlds), as Chrome may apply either."""
    hiding = _paint_hiding_in(rules, element, inherited_background)
    other_rules = getattr(rules, "without_undecided_blocks", None)
    if hiding is None and other_rules is not None:
        hiding = _paint_hiding_in(other_rules, element, inherited_background)
    return hiding


# How far right of or below its drawing SVG text must start to count as off it, while the font
# stays under half this size (so no letter reaches back in).
FAR_OUTSIDE_DRAWING_PIXELS = 1000
# The size of an <svg> without width or height.
DEFAULT_SVG_SIZE = {"width": 300.0, "height": 150.0}
# Presentation attributes that move or turn SVG text away from where x and y put it.
SVG_TEXT_PLACING_ATTRIBUTES = (
    "transform", "dominant-baseline", "alignment-baseline", "baseline-shift", "writing-mode",
    "text-orientation", "glyph-orientation-vertical",
)
# The CSS properties among those the cascade keeps (the others are found by _SVG_PLACING_CSS).
SVG_TEXT_PLACING_CSS = ("transform", "translate", "scale")
SVG_TEXT_POSITION_ATTRIBUTES = ("x", "y", "dx", "dy", "rotate")
SVG_ANIMATION_TAGS = ("animate", "set", "animatetransform", "animatemotion")
# CSS the cascade does not keep, named anywhere in the page's CSS: what may move SVG text ("placing"),
# and what may resize an <svg> or anchor text at its end ("far", which only the far-off rule needs).
_SVG_PLACING_CSS = re.compile(
    r"(?<![\w-])(?:(dominant-baseline|alignment-baseline|baseline-shift|writing-mode|text-orientation"
    r"|glyph-orientation-vertical|rotate|offset(?:-[a-z]+)?|animation(?:-[a-z]+)?)"
    r"|(aspect-ratio|flex(?:-basis|-grow|-shrink)?|(?:min-|max-)?(?:inline|block)-size|min-width|zoom"
    r"|text-anchor|direction))\s*:",
    re.IGNORECASE,
)
# CSS the cascade keeps that can change an <svg>'s size from its width and height attributes.
SVG_SIZING_PROPERTIES = ("width", "height", "min-height", "max-width", "max-height")
_STRETCHING_DISPLAYS = ("flex", "inline-flex", "grid", "inline-grid")
# The largest absolute font-size keyword (xxx-large), and at most how much "larger" grows a size.
_LARGEST_FONT_KEYWORD_PIXELS = 48.0
_LARGER_FONT_FACTOR = 1.5
_FONT_SIZE_KEYWORDS = ("xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large", "xxx-large")


def _svg_pixels(value):
    """A single SVG coordinate or size in pixels (unitless or px), or None for anything else."""
    match = _SVG_LENGTH.fullmatch(with_math_evaluated(value.strip(" \t\n\f\r").lower()))
    if match is None or match.group(2) not in (None, "px"):
        return None
    return float(match.group(1))


def _rule_worlds_of(rules):
    other_rules = getattr(rules, "without_undecided_blocks", None)
    return (rules,) if other_rules is None else (rules, other_rules)


def _referenced_ids(rules, element):
    """Ids that a <use> or an animation element on the page points at: drawn or moved from there."""
    cache = _paint_cache(rules)
    if cache.referenced_ids is None:
        cache.referenced_ids = set()
        for node in element.getroottree().iter():
            if not isinstance(node.tag, str) or node.tag.lower() not in ("use",) + SVG_ANIMATION_TAGS:
                continue
            link = (node.get("href") or node.get("xlink:href") or "").strip()
            if link.startswith("#"):
                cache.referenced_ids.add(link[1:])
    return cache.referenced_ids


def _is_placed_elsewhere(node, worlds):
    """Whether an attribute or CSS on node may move or turn the text under it."""
    for name in SVG_TEXT_PLACING_ATTRIBUTES:
        if node.get(name) is not None:
            return True
    for world in worlds:
        declarations = _full_declarations(world, node)
        for name in SVG_TEXT_PLACING_CSS:
            if declarations.get(name, "none") != "none":
                return True
    return False


def _folded_down_the_tree(table, element, own, start):
    """own(node, parent's value) for element, computed from the root down and remembered in table
    for every element on the way, so each is computed once; start stands for the root's parent."""
    chain = []
    current = element
    while current is not None and isinstance(current.tag, str) and current not in table:
        chain.append(current)
        current = current.getparent()
    value = table[current] if current is not None and current in table else start
    for member in reversed(chain):
        value = own(member, value)
        table[member] = value
    return value


def _font_step(world, node, parent_sizes):
    """(font size, root font size) estimates at node from its parent's, or None when unknown."""
    if parent_sizes is None:
        return None
    size, root_size = parent_sizes
    value = _full_declarations(world, node).get("font-size")
    if value is None and node.get("font-size") is not None and _is_svg_element(node, node.tag.lower()):
        value = _svg_attribute_value(node, "font-size")
    match = None if value is None else _SVG_LENGTH.fullmatch(value)
    if value is None or value in _INHERITING_VALUES or value == "smaller":
        pass
    elif match is not None and match.group(2) in (None, "px"):
        size = float(match.group(1))
    elif match is not None and match.group(2) in ("em", "%"):
        size *= float(match.group(1)) / (100 if match.group(2) == "%" else 1)
    elif match is not None and match.group(2) == "rem":
        size = root_size * float(match.group(1))
    elif value == "larger":
        size *= _LARGER_FONT_FACTOR
    elif value in _FONT_SIZE_KEYWORDS:
        size = _LARGEST_FONT_KEYWORD_PIXELS
    else:
        return None
    return size, size if node.getparent() is None else root_size


def _largest_font_pixels(element, worlds):
    """An upper estimate of element's font size in pixels, or None when it cannot be estimated."""
    largest = 0.0
    for world in worlds:
        sizes = _folded_down_the_tree(_paint_cache(world).font_pixels, element,
                                      lambda node, parent_sizes: _font_step(world, node, parent_sizes),
                                      (16.0, 16.0))
        if sizes is None:
            return None
        largest = max(largest, sizes[0])
    return largest


def _drawing_step(worlds, referenced, node, parent_drawing):
    """(nearest <svg> or None, whether anything from it down to node may move text, how many <svg>
    enclose node) from the parent's."""
    svg, placed, svg_count = parent_drawing
    tag = node.tag.lower()
    if svg is None and tag != "svg":
        return parent_drawing  # outside SVG: nothing here places SVG text
    own_placing = (tag == "foreignobject" or _is_placed_elsewhere(node, worlds)
                   or node.get("id") in referenced)
    if tag == "svg":
        return node, own_placing, svg_count + 1
    return svg, placed or own_placing, svg_count


def _is_anchored_at_start(rules, element):
    """Whether no text-anchor or direction attribute on element or an ancestor may anchor its text elsewhere."""
    return _folded_down_the_tree(
        _paint_cache(rules).anchored, element,
        lambda node, anchored: anchored and node.get("text-anchor") is None and node.get("direction") is None,
        True,
    )


def _known_svg_size(svg, worlds):
    """The <svg>'s width and height in pixels from its attributes ({name: None} when unknown)."""
    sizes = {}
    for name in ("width", "height"):
        value = svg.get(name)
        sizes[name] = DEFAULT_SVG_SIZE[name] if value is None else _svg_pixels(value)
    parent = svg.getparent()
    for world in worlds:
        declarations = _full_declarations(world, svg)
        if any(name in declarations for name in SVG_SIZING_PROPERTIES):
            return {"width": None, "height": None}
        if parent is not None and _full_declarations(world, parent).get("display") in _STRETCHING_DISPLAYS:
            # A flex or grid container may stretch an <svg> that has no size of its own.
            for name in ("width", "height"):
                if svg.get(name) is None:
                    sizes[name] = None
    return sizes


def _clips_its_content(svg, worlds):
    """Whether the <svg> cuts off what is drawn outside it (unless both overflow axes are visible)."""
    for world in worlds:
        declarations = dict(_full_declarations(world, svg))
        if "overflow" not in declarations and svg.get("overflow") is not None:
            declarations["overflow"] = _svg_attribute_value(svg, "overflow")
        overflow_words = declarations.get("overflow", "").split()
        overflow_x = declarations.get("overflow-x") or (overflow_words[0] if overflow_words else "")
        overflow_y = declarations.get("overflow-y") or (overflow_words[-1] if overflow_words else "")
        if overflow_x == "visible" and overflow_y == "visible":
            return False
    return True


def _svg_text_position_hiding(element, rules):
    """A MEDIUM Hiding when a <text> is placed wholly outside the <svg> that clips it, or None.
    Only the plain cases: no viewBox, nested <svg> or <foreignObject>, nothing that moves or turns
    the text, and no <tspan> or <textPath> with a place of its own; the browser check reads the rest."""
    css_mentions = getattr(rules, "svg_css_mentions", frozenset(("placing", "far")))
    if "placing" in css_mentions:
        return None
    worlds = _rule_worlds_of(rules)
    referenced = _referenced_ids(rules, element)
    svg, placed, svg_count = _folded_down_the_tree(
        _paint_cache(rules).drawing, element,
        lambda node, parent_drawing: _drawing_step(worlds, referenced, node, parent_drawing), (None, False, 0),
    )
    if svg is None or placed or svg_count != 1 or svg.get("viewbox") is not None:
        return None
    for name in ("dx", "dy", "rotate"):
        if element.get(name) is not None:
            return None
    for descendant in element.iterdescendants():
        if not isinstance(descendant.tag, str):
            continue
        tag = descendant.tag.lower()
        if tag == "textpath" or tag in SVG_ANIMATION_TAGS or descendant.get("id") in referenced:
            return None
        if _is_placed_elsewhere(descendant, worlds):
            return None
        for name in SVG_TEXT_POSITION_ATTRIBUTES:
            if descendant.get(name) is not None:
                return None
    x = 0.0 if element.get("x") is None else _svg_pixels(element.get("x"))
    y = 0.0 if element.get("y") is None else _svg_pixels(element.get("y"))
    if x is None or y is None or not _clips_its_content(svg, worlds):
        return None
    if y <= 0:
        return Hiding(f"SVG text placed above its drawing (y={element.get('y', 'not set')}: its letters sit "
                      "above the top edge)", MEDIUM, "svg_off_drawing")
    if "far" in css_mentions:
        return None
    sizes = _known_svg_size(svg, worlds)
    far_below = sizes["height"] is not None and y >= sizes["height"] + FAR_OUTSIDE_DRAWING_PIXELS
    far_right = (sizes["width"] is not None and x >= sizes["width"] + FAR_OUTSIDE_DRAWING_PIXELS
                 and _is_anchored_at_start(rules, element))
    if not far_below and not far_right:
        return None
    font_pixels = _largest_font_pixels(element, worlds)
    if font_pixels is None or font_pixels >= FAR_OUTSIDE_DRAWING_PIXELS / 2:
        return None
    if far_below:
        return Hiding(f"SVG text placed far below its drawing (y={element.get('y')})", MEDIUM, "svg_off_drawing")
    return Hiding(f"SVG text placed far right of its drawing (x={element.get('x')})", MEDIUM, "svg_off_drawing")


def _foreign_object_color_hiding(element, rules, inherited_background):
    """Why the HTML in a <foreignObject> cannot be seen in the color it inherits from SVG
    ancestors (CSS or the color attribute), or None."""
    worlds = [rules]
    if getattr(rules, "without_undecided_blocks", None) is not None:
        worlds.append(rules.without_undecided_blocks)
    for world in worlds:
        color = _svg_paint(world, element)["color"]
        hiding = _hiding_from_declarations({"color": color}, inherited_background, _background_lookup(world, element))
        if hiding is not None:
            return hiding._replace(reason=f"{hiding.reason} (the color the <foreignObject> inherits)")
    return None


def _visit(element, inherited_background, rules, visible_parts, hidden_fragments, svg_place=None):
    """Collects visible text and the outermost hidden elements under element, which sits in svg_place."""
    tag = element.tag.lower() if isinstance(element.tag, str) else ""
    if tag in NON_TEXT_TAGS:
        return
    hiding, inherited_background, declarations, children_place = _element_hiding(
        element, tag, rules, inherited_background, svg_place
    )
    if hiding is not None:
        hidden_text = _collapse_whitespace(_text_outside_code(element))
        if hidden_text:
            hidden_fragments.append(HiddenFragment.hidden(hidden_text, hiding, element))
        return

    reordering = _reordering(element, tag, declarations)
    if reordering is not None:
        reason, rule = reordering
        hidden_fragments.append(HiddenFragment(
            _collapse_whitespace(element.text_content()),
            f"shown to readers in reverse order ({reason})", "reordered_text", HIGH, element, css=rule,
        ))

    # SVG text outside <text> is not drawn, and each <text> is set apart from what is around it.
    text_is_drawn = children_place is None or children_place.in_text
    text_hiding = None
    settled_by_rendering = False
    if children_place is not None and children_place.in_text:
        text_hiding = _svg_paint_hiding(element, rules, inherited_background)
        if text_hiding is None and children_place.off_drawing is not None:
            text_hiding = children_place.off_drawing
            settled_by_rendering = True
    starts_svg_text = children_place is not None and children_place.in_text and not svg_place.in_text
    is_block = tag in BLOCK_TAGS or starts_svg_text
    if is_block:
        visible_parts.append(" ")

    if _is_closed_details(element, tag):
        summary = None
        for child in element:
            if isinstance(child.tag, str) and child.tag.lower() == "summary":
                summary = child
                break
        _hide_loose_content(element, summary, CLOSED_DETAILS_HIDING, hidden_fragments)
        if summary is not None:
            _visit(summary, inherited_background, rules, visible_parts, hidden_fragments, children_place)
        visible_parts.append(" ")
        return

    overlay = _overlay_over_content(element, rules)
    if overlay is not None:
        _hide_loose_content(element, overlay, COVERED_BY_OVERLAY_HIDING, hidden_fragments)
        _visit(overlay, inherited_background, rules, visible_parts, hidden_fragments, children_place)
        visible_parts.append(" ")
        return

    if not text_is_drawn:
        _record_undrawn_svg_text(element.text, (element, "text"), hidden_fragments)
    elif text_hiding is not None:
        _record_undrawn_svg_text(element.text, (element, "text"), hidden_fragments, text_hiding, settled_by_rendering)
    elif element.text:
        visible_parts.append(element.text)
    for child in element:
        if isinstance(child, etree._Comment):
            comment_text = _collapse_whitespace(child.text or "")
            if comment_text:
                hidden_fragments.append(HiddenFragment(comment_text, "HTML comment", "html_comment", MEDIUM, child))
        elif isinstance(child.tag, str):
            _visit(child, inherited_background, rules, visible_parts, hidden_fragments, children_place)
        if not text_is_drawn:
            _record_undrawn_svg_text(child.tail, (child, "tail"), hidden_fragments)
        elif text_hiding is not None:
            _record_undrawn_svg_text(child.tail, (child, "tail"), hidden_fragments, text_hiding,
                                     settled_by_rendering)
        elif child.tail:
            visible_parts.append(child.tail)
    if is_block:
        visible_parts.append(" ")


def parse_document(html, stylesheets=None):
    """Parses an HTML page or fragment and collects its CSS rules: (root, rules).

    stylesheets: CSS text of the page's external stylesheets, in document order, if the
    caller has fetched them (see linked_stylesheet_urls). With tinycss2 and cssselect2
    installed, a real cascade is used; otherwise a simple reader of .class/#id/tag rules
    in <style> blocks, which ignores external stylesheets.
    """
    root = parse_html(html)
    css_texts = list(stylesheets or ())
    for style in root.iter("style"):
        css_texts.append(style.text or "")
    for element in root.iter():
        if isinstance(element.tag, str) and element.get("style"):
            css_texts.append(element.get("style"))
    try:
        from .css_cascade import CascadeRules
    except ImportError:
        rules = _StylesheetRules(root)
    else:
        check_css_numbers(css_texts)
        rules = CascadeRules(root, stylesheets or (), is_quirks_mode(html))
    rules.svg_css_mentions = _svg_css_mentions(css_texts)
    return root, rules


def _svg_css_mentions(css_texts):
    """Which groups of _SVG_PLACING_CSS the page's CSS names ("placing", "far")."""
    mentions = set()
    for text in css_texts:
        for match in _SVG_PLACING_CSS.finditer(text):
            mentions.add("placing" if match.group(1) else "far")
    return frozenset(mentions)


def check_css_numbers(texts):
    """Raises PageTooComplex when the page's CSS holds an integer too long for tinycss2, which
    converts each one to a Python int (limited to sys.get_int_max_str_digits() digits)."""
    limit = sys.get_int_max_str_digits()
    if limit == 0:
        return
    for text in texts:
        for digits in _DIGIT_RUN.finditer(text):
            if digits.end() - digits.start() <= limit:
                continue
            raise PageTooComplex(f"CSS holds a number of more than {limit} digits, which this reader cannot read")


def linked_stylesheet_urls(html, base_url):
    """Absolute URLs of the page's <link rel="stylesheet"> files that apply to a screen, in order."""
    from urllib.parse import urljoin

    from .media_queries import media_query_applies

    try:
        root = parse_html(html)
    except PageTooComplex:
        return []  # the page is not read statically, so its stylesheets are not needed
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
    starting_background, ancestor_hiding, svg_place = _ancestor_state(element, rules)
    if ancestor_hiding is not None:
        hidden_fragments = []
        hidden_text = _collapse_whitespace(_text_outside_code(element))
        if hidden_text:
            hidden_fragments.append(HiddenFragment.hidden(hidden_text, ancestor_hiding, element))
        return "", hidden_fragments
    visible_parts = []
    hidden_fragments = []
    _visit(element, starting_background, rules, visible_parts, hidden_fragments, svg_place)
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
