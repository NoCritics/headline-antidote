"""A real CSS cascade for the visibility check, using tinycss2 and cssselect2.

Compared with the simple rule reader in html_visibility, this understands any
selector (descendant and child combinators, attributes, :not(), :nth-child()...),
specificity, source order, !important, inline styles, @media rules answered as the
browser check's Chrome answers them (media_queries), and CSS variables (var(--name, fallback)). It reads <style> blocks
and any external stylesheets the caller supplies (it never fetches anything).

At-rules and nesting, as Chrome applies them:
* cascade layers (@layer, revert-layer) in Chrome's order; nested style rules (&);
* @document is never applied (Chrome does not support it);
* @supports, @container and @scope depend on what Chrome supports, on layout, or on how close
  the scope root is, which this reader cannot answer. Chrome may apply any subset of those
  blocks, so text that any subset hides counts as hidden (CascadeRules.declaration_alternatives
  and without_undecided_blocks). This errs towards hiding: text Chrome shows can be removed.

Speed, since real pages ship hundreds of kilobytes of CSS:
* compiled stylesheets are cached, so every later page from a site reuses them. A site's
  external stylesheets and the pages' own <style> blocks have separate caches, so the many
  one-off page blocks never push a site's CSS out;
* only the properties that can hide text are kept;
* matching runs in two steps: an element is matched against the few rules whose values
  could hide text when the visibility check first asks about it, and the full cascade
  (which can show the text again) is computed only for the elements those rules touch;
* whether a rule could hide text is decided once, when its stylesheet is compiled, unless
  its values use var(), whose site-wide values can differ between pages;
* cssselect2's element wrappers are built once per page and reused by every selector test.

It also reports ::before/::after boxes that may cover text or add words, CSS variables
defined on narrow selectors, and fonts embedded in the CSS (data: URIs), whose glyphs a
page could remap. It does not do layout, so it cannot see overlap between unrelated
parts of the page, or hiding applied by JavaScript.
"""

import functools
import hashlib
import re
from collections import ChainMap, OrderedDict, namedtuple

import cssselect2
import tinycss2
from tinycss2.serializer import BAD_PAIRS, serialize_identifier

from .css_hiding import (
    CLIPPED_BOX_MAXIMUM_PIXELS, MINIMUM_VISIBLE_OPACITY, declared_background_color, filter_hiding,
    any_offset_is_off_screen, font_shorthand_is_unreadable, font_size_is_unreadable, is_covering_overlay,
    letters_collapsed, line_height_collapsed, opacity_is_invisible, relative_luminance,
    scale_is_zero, translation_is_off_screen, z_index_is_negative,
)
from .css_validity import INVALID, QUIRKS_ONLY, UNKNOWN, VALID, custom_property_validity, declaration_validity
from .html_tree import PageTooComplex
from .css_values import length_in_pixels, parse_color, quoted_strings, with_math_evaluated
from .media_queries import media_query_applies

# var() resolves to any depth, as in Chrome, which follows chains thousands long. A value longer
# than this once resolved (one variable repeating another can double it at every step) counts as
# one the reader cannot check, which hides the element. Real pages' resolved values are far shorter.
MAXIMUM_RESOLVED_CHARACTERS = 100_000
# And all a page's resolved values together (real pages: at most 20,529 in 540 readings), so many
# values just under the limit cannot take minutes either.
MAXIMUM_PAGE_RESOLVED_CHARACTERS = 1_000_000
# Deciding which rules could hide text, each var() takes every value any rule gives the variable;
# past this many expansions of one value the rule is assumed able to hide.
MAXIMUM_VARIABLE_FORMS = 64
# Cache budgets, in characters of CSS source. Compiled CSS takes about 13 times its source
# size in memory (7 to 26 times on the fresh page set), so 24 million characters is about
# 300 MB: room for every site of a pipeline (the 47 sites of the fresh set have 19.5 million).
# Compiling a big site's CSS takes 0.5 to 3 s, which only its first article then pays.
EXTERNAL_CSS_CACHE_CHARACTERS = 24_000_000
# Pages' own <style> blocks. Sites repeat template blocks on every page (3.9 million characters
# over the fresh set's 47 sites) among one-off CSS (6 million; one Il Sole 24 Ore page alone has
# 834,000). 8 million characters, about 100 MB, is a few hundred pages of new blocks, so a
# site's templates are still cached when its next article arrives.
PAGE_CSS_CACHE_CHARACTERS = 8_000_000
# The _RuleSet of one page's blocks together, reused only when the same page is read again.
PAGE_RULE_SET_CACHE_CHARACTERS = 2_000_000
# Text colors at least this light can disappear on the usual white page, so they are worth matching.
LIGHT_TEXT_LUMINANCE = 0.6

HIDING_PROPERTIES = {
    "display", "visibility", "opacity", "font-size", "color", "background", "background-color",
    "clip", "clip-path", "transform", "overflow", "width", "height", "max-width", "max-height",
    "position", "left", "top", "right", "bottom", "margin-left", "margin-top", "text-indent",
    # the remaining hiding tricks
    "-webkit-text-fill-color", "filter", "content-visibility", "font", "line-height", "letter-spacing",
    "overflow-x", "overflow-y", "translate", "scale", "min-height",
    # what can still show transparent text: a background clipped to the text, or a shadow
    "background-clip", "-webkit-background-clip", "background-image", "text-shadow",
    # overlays and stacking order
    "z-index", "inset", "content", "isolation", "mix-blend-mode", "mask", "perspective",
    # reordered text and embedded fonts
    "unicode-bidi", "direction", "font-family",
    # how SVG text is painted
    "fill", "fill-opacity", "stroke", "stroke-opacity", "stroke-width", "stop-color", "stop-opacity",
}

# Rules on these selectors define site-wide CSS variables, substituted before deciding which rules matter.
SITE_WIDE_SELECTORS = {":root", "html", "body", ":root,html", "html,:root", "html,body", ":root,body"}
# A zero length or percentage in any unit.
_ZERO_SIZE = re.compile(r"[+-]?(?:0+(?:\.0*)?|\.0+)(?:e[+-]?\d+)?(?:[a-z]+|%)?")
_VARIABLE_REFERENCE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)")


class _SizeBoundedCache(OrderedDict):
    """A least-recently-used cache whose entries' sizes add up to at most budget; the newest
    entry is always kept, even when it alone is larger."""

    def __init__(self, budget):
        super().__init__()
        self.budget = budget
        self.total_size = 0

    def lookup(self, key):
        entry = self.get(key)
        if entry is None:
            return None
        self.move_to_end(key)
        return entry[0]

    def store(self, key, value, size):
        self[key] = (value, size)
        self.total_size += size
        while self.total_size > self.budget and len(self) > 1:
            _, (_, dropped_size) = self.popitem(last=False)
            self.total_size -= dropped_size

    def clear(self):
        super().clear()
        self.total_size = 0


# Compiled stylesheets, by content, and the _RuleSets built from groups of them.
_external_stylesheets = _SizeBoundedCache(EXTERNAL_CSS_CACHE_CHARACTERS)
_external_rule_sets = _SizeBoundedCache(EXTERNAL_CSS_CACHE_CHARACTERS)
_page_stylesheets = _SizeBoundedCache(PAGE_CSS_CACHE_CHARACTERS)
_page_rule_sets = _SizeBoundedCache(PAGE_RULE_SET_CACHE_CHARACTERS)


_BLOCK_BRACKETS = {"() block": ("(", ")"), "[] block": ("[", "]"), "{} block": ("{", "}")}


def _function_is_closed(function, closed_by_function):
    """Whether tinycss2 writes the closing ")" of a function: not when its last argument, or the last
    argument of the function that ends it, and so on, is a string cut off by the end of the input.
    The answer is shared along that chain, so it is stored for every function on it."""
    chain = []
    current = function
    closed = True
    while current.type == "function" and current.arguments:
        if id(current) in closed_by_function:
            closed = closed_by_function[id(current)]
            break
        chain.append(current)
        last = current.arguments[-1]
        if last.type == "error" and last.kind == "eof-in-string":
            closed = False
            break
        current = last
    for link in chain:
        closed_by_function[id(link)] = closed
    return closed


def _serialized(nodes):
    """tinycss2.serialize(nodes), written with an explicit stack: tinycss2 recurses once per nested
    function or block, so CSS nested a few thousand levels deep would exhaust Python's call stack.
    One difference: var() is always written in lowercase (function names are case-insensitive,
    VAR(--x) is var(--x)), so the variable reader only looks for "var(", while variable names and
    strings keep their case."""
    chunks = []
    closed_by_function = {}
    # Each frame: [the rest of a node list, the previous node's serialization type, closing text].
    pending = [[iter(nodes), None, ""]]
    while pending:
        frame = pending[-1]
        node = next(frame[0], None)
        if node is None:
            chunks.append(frame[2])
            pending.pop()
            continue
        serialization_type = node.type if node.type != "literal" else node.value
        previous_type = frame[1]
        if (previous_type, serialization_type) in BAD_PAIRS:
            chunks.append("/**/")
        elif previous_type == "\\" and not (serialization_type == "whitespace" and node.value.startswith("\n")):
            chunks.append("\n")
        frame[1] = serialization_type
        if node.type == "function":
            if node.lower_name in ("var", "env"):
                chunks.append(node.lower_name + "(")
            else:
                chunks.append(serialize_identifier(node.name) + "(")
            closing = ")" if _function_is_closed(node, closed_by_function) else ""
            pending.append([iter(node.arguments), None, closing])
        elif node.type in _BLOCK_BRACKETS:
            opening, closing = _BLOCK_BRACKETS[node.type]
            chunks.append(opening)
            pending.append([iter(node.content), None, closing])
        else:
            node._serialize_to(chunks.append)
    return "".join(chunks)


def _declarations(tokens):
    """[(name, value, important, validity)] for hiding properties and custom properties (--name)."""
    return _hiding_declarations(tinycss2.parse_blocks_contents(tokens, skip_comments=True, skip_whitespace=True))


def _hiding_declarations(items):
    """The (name, value, important, validity) of the hiding and custom properties among parsed
    block contents (nested rules among them are left out). Chrome drops an invalid declaration,
    so an earlier one still applies: those are left out too. validity is VALID, QUIRKS_ONLY
    (applies on quirks-mode pages only) or UNKNOWN (may apply: see _entry_is_undecided)."""
    found = []
    for declaration in items:
        if declaration.type != "declaration":
            continue
        name = declaration.name if declaration.name.startswith("--") else declaration.lower_name
        if name.startswith("--"):
            # UNKNOWN only past 1,000 nested substitution functions; such a value is kept.
            if custom_property_validity(declaration.value) == INVALID:
                continue
            found.append((name, _serialized(declaration.value).strip(), declaration.important, VALID))
        elif name in HIDING_PROPERTIES:
            validity = declaration_validity(name, declaration.value)
            if validity == INVALID:
                continue
            value = _serialized(declaration.value).strip()
            # Variable and env() names are case-sensitive, so a value using one is lowercased (and
            # its math evaluated) once resolved.
            if "var(" not in value and "env(" not in value:
                value = with_math_evaluated(value.lower())
            found.append((name, value, declaration.important, validity))
    return found


def _substituted_validity(name, text):
    """The validity of a name declaration whose var() were substituted into text. Short texts
    (nearly all) are cached, so the cache stays within a few megabytes."""
    if len(text) > 1000:
        return declaration_validity(name, tinycss2.parse_component_value_list(text))
    return _cached_substituted_validity(name, text)


@functools.lru_cache(maxsize=4096)
def _cached_substituted_validity(name, text):
    return declaration_validity(name, tinycss2.parse_component_value_list(text))


def _entry_is_undecided(rule_undecided, validity, quirks_mode):
    """Whether a declaration's cascade entry is undecided (Chrome may or may not apply it), or None
    when it does not apply on this page. One this reader cannot validate may apply."""
    if validity == QUIRKS_ONLY:
        if not quirks_mode:
            return None
        return rule_undecided
    return rule_undecided or validity == UNKNOWN


# What a value resolves to when it cannot be used: invalid (a var() with neither a value nor a
# fallback, or a variable in a cycle; Chrome then treats the declaration as unset), or too long
# to check (see MAXIMUM_RESOLVED_CHARACTERS).
_INVALID = object()
_OVER_BUDGET = object()
_VARIABLE_NAME = re.compile(r"\s*(--[\w-]+)\s*")


def _variable_references(value):
    """The names of the variables value refers to, fallbacks included, each once (a var() written
    inside a quoted string is text, not a reference)."""
    names = []
    if "var(" not in value:
        return names
    _, variable_starts = _parentheses(value)
    for start in sorted(variable_starts):
        match = _VARIABLE_NAME.match(value, start + 4)
        if match is not None and match.group(1) not in names:
            names.append(match.group(1))
    return names


def _parentheses(text, function_name="var"):
    """(where each "(" closes, where function_name( functions start), outside quoted strings. An
    unclosed parenthesis closes at the end of the text."""
    closing = {}
    variable_starts = set()
    open_positions = []
    quote = None
    name_length = len(function_name)
    index = 0
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\":
                index += 1
            elif character == quote:
                quote = None
        elif character in "\"'":
            quote = character
        elif character == "(":
            open_positions.append(index)
            start = index - name_length
            if start >= 0 and text.startswith(function_name, start) and (
                    start == 0 or not (text[start - 1].isalnum() or text[start - 1] in "-_")):
                variable_starts.add(start)
        elif character == ")" and open_positions:
            closing[open_positions.pop()] = index
        index += 1
    for position in open_positions:
        closing[position] = len(text)
    return closing, variable_starts


def _substituted(value, value_of):
    """value with every var() replaced by value_of(name) (a resolved text, None when undefined,
    _INVALID or _OVER_BUDGET), or by its fallback when the variable has no usable value. Returns
    _INVALID when a var() has neither, _OVER_BUDGET past MAXIMUM_RESOLVED_CHARACTERS. Fallbacks
    nested any depth are followed with an explicit stack."""
    if "var(" not in value:
        return value
    closing, variable_starts = _parentheses(value)
    pieces = []
    length = 0
    position = 0
    end = len(value)
    resume = []  # where to carry on after each fallback being written
    while True:
        if position >= end:
            if not resume:
                break
            position, end = resume.pop()
            continue
        start = value.find("var(", position, end)
        while start != -1 and start not in variable_starts:
            start = value.find("var(", start + 4, end)
        piece_end = end if start == -1 else start
        if piece_end > position:
            pieces.append(value[position:piece_end])
            length += piece_end - position
            if length > MAXIMUM_RESOLVED_CHARACTERS:
                return _OVER_BUDGET
        if start == -1:
            position = end
            continue
        close = closing[start + 3]
        name_match = _VARIABLE_NAME.match(value, start + 4, close)
        if name_match is None:
            return _INVALID
        after_name = name_match.end()
        has_fallback = after_name < close and value[after_name] == ","
        if not has_fallback and value[after_name:close].strip():
            return _INVALID
        variable_value = value_of(name_match.group(1))
        if variable_value is _OVER_BUDGET:
            return _OVER_BUDGET
        if isinstance(variable_value, str):
            replacement = variable_value.strip()
            pieces.append(replacement)
            length += len(replacement)
            if length > MAXIMUM_RESOLVED_CHARACTERS:
                return _OVER_BUDGET
            position = close + 1
        elif has_fallback:
            resume.append((close + 1, end))
            position = after_name + 1
            end = close
            while position < end and value[position].isspace():
                position += 1
            while end > position and value[end - 1].isspace():
                end -= 1
        else:
            return _INVALID
    return "".join(pieces)


# env() at the browser check's desktop viewport, measured in Chrome 157: the safe-area and
# keyboard insets are 0px and preferred-text-scale is 1. Every other name (titlebar-area-*,
# viewport-segment-*, a name with an index, one in another case) has no value there, so the
# fallback applies, and without one the declaration is unset.
_ENVIRONMENT_VALUES = {
    "safe-area-inset-top": "0px", "safe-area-inset-right": "0px",
    "safe-area-inset-bottom": "0px", "safe-area-inset-left": "0px",
    "safe-area-max-inset-top": "0px", "safe-area-max-inset-right": "0px",
    "safe-area-max-inset-bottom": "0px", "safe-area-max-inset-left": "0px",
    "keyboard-inset-top": "0px", "keyboard-inset-right": "0px", "keyboard-inset-bottom": "0px",
    "keyboard-inset-left": "0px", "keyboard-inset-width": "0px", "keyboard-inset-height": "0px",
    "preferred-text-scale": "1",
}
# A value with more env() than this counts as one too long to check (real values have one or two).
MAXIMUM_ENVIRONMENT_REFERENCES = 100
# Functions Chrome evaluates and this reader cannot: a hiding value using one, as written or once
# var() and env() are substituted, counts as unreadable, which hides the element (attr() in
# content only gives text). Chrome 158 leaves an inherit() that came from a custom property as
# written, so that one is a false alarm.
_UNEVALUATED_FUNCTION = re.compile(r"(?<![\w-])(?:if|attr|inherit|--[\w-]+)\(", re.IGNORECASE)


def _uses_unevaluated_function(name, value):
    return name != "content" and "(" in value and _UNEVALUATED_FUNCTION.search(value) is not None


def _first_top_level_comma(text):
    """Where the first comma outside brackets and quoted strings is in text, -1 when none."""
    depth = 0
    quote = None
    index = 0
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\":
                index += 1
            elif character == quote:
                quote = None
        elif character in "\"'":
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == "," and depth == 0:
            return index
        index += 1
    return -1


def _environment_substituted(text):
    """text with each env() replaced as Chrome gives it (see _ENVIRONMENT_VALUES); _INVALID when
    one has neither a value nor a fallback, _OVER_BUDGET past MAXIMUM_ENVIRONMENT_REFERENCES."""
    replaced = 0
    while True:
        closing, starts = _parentheses(text, "env")
        if not starts:
            return text
        replaced += 1
        if replaced > MAXIMUM_ENVIRONMENT_REFERENCES:
            return _OVER_BUDGET
        # The last one holds no other in its fallback.
        start = max(starts)
        close = closing[start + 3]
        body = text[start + 4:close]
        comma = _first_top_level_comma(body)
        name = (body if comma == -1 else body[:comma]).strip()
        if name in _ENVIRONMENT_VALUES:
            replacement = _ENVIRONMENT_VALUES[name]
        elif comma != -1:
            replacement = body[comma + 1:].strip()
        else:
            return _INVALID
        text = text[:start] + replacement + text[close + 1:]


def _variable_forms(value, variable_values):
    """Every text value can take when each var() in it becomes any value some rule gives that
    variable, or its fallback (or nothing, when it is undefined or invalid); None past
    MAXIMUM_VARIABLE_FORMS expansions, or for a var() this pattern cannot take apart."""
    if "var(" not in value:
        return [value]
    pending = [value]
    seen = {value}
    finished = []
    steps = 0
    while pending:
        partial = pending.pop()
        steps += 1
        if steps > MAXIMUM_VARIABLE_FORMS:
            return None
        match = _VARIABLE_REFERENCE.search(partial)
        if match is None:
            if "var(" in partial:
                return None
            finished.append(partial)
            continue
        replacements = list(variable_values.get(match.group(1), ()))
        replacements.append(match.group(2) or "")
        for replacement in replacements:
            expanded = partial[:match.start()] + replacement.strip() + partial[match.end():]
            if expanded not in seen:
                seen.add(expanded)
                pending.append(expanded)
    return finished


def _could_hide(name, value):
    """Whether one declaration could, alone or with others, hide text. Used to pick elements to examine."""
    if name.startswith("--"):
        return False  # custom properties are looked up on demand when a var() is resolved
    # Read once env() is substituted, or unreadable (see _UNEVALUATED_FUNCTION).
    if "env(" in value or _uses_unevaluated_function(name, value):
        return True
    if name == "display":
        return value == "none"
    if name == "visibility":
        return value in ("hidden", "collapse")
    if name == "content-visibility":
        return value == "hidden"
    if name == "opacity":
        return opacity_is_invisible(value)
    if name == "filter":
        return filter_hiding(value) is not None
    if name == "font-size":
        return font_size_is_unreadable(value)
    if name == "font":
        return font_shorthand_is_unreadable(value)
    if name == "letter-spacing":
        return letters_collapsed(value)
    if name == "line-height":
        return line_height_collapsed(value)
    if name in ("color", "-webkit-text-fill-color"):
        color = parse_color(value)
        return color is not None and (color[3] < MINIMUM_VISIBLE_OPACITY
                                      or relative_luminance(color) >= LIGHT_TEXT_LUMINANCE)
    if name in ("fill", "stop-color"):
        # Any paint but a dark color can leave SVG text unpainted (none, url(), currentcolor, light).
        color = parse_color(value)
        return color is None or color[3] < MINIMUM_VISIBLE_OPACITY or relative_luminance(color) >= LIGHT_TEXT_LUMINANCE
    if name in ("fill-opacity", "stop-opacity"):
        return opacity_is_invisible(value)
    if name in ("background", "background-color"):
        return False  # looked up on demand by background_for(), only for light text
    if name in ("clip", "clip-path", "transform"):
        return value not in ("auto", "none")
    if name == "translate":
        return translation_is_off_screen("", value)
    if name == "scale":
        return scale_is_zero(value)
    if name in ("width", "height", "max-width", "max-height"):
        if _ZERO_SIZE.fullmatch(value):
            return True  # a zero-size <svg> paints nothing, whatever the unit
        pixels = length_in_pixels(value)
        return pixels is not None and pixels <= CLIPPED_BOX_MAXIMUM_PIXELS
    if name in ("left", "top", "right", "bottom", "margin-left", "margin-top", "text-indent", "inset"):
        return any_offset_is_off_screen(value)
    if name == "z-index":
        return z_index_is_negative(value)
    if name == "unicode-bidi":
        return value in ("bidi-override", "isolate-override")
    return False


def _rule_could_cover(forms_by_name):
    """A rule that draws an opaque overlay over its box, in any combination of its values' forms
    (checked on the whole rule, not one value)."""
    combinations = [{}]
    for name, forms in forms_by_name:
        extended = []
        for combination in combinations:
            for form in forms:
                choice = dict(combination)
                choice[name] = form
                extended.append(choice)
        combinations = extended
        if len(combinations) > MAXIMUM_VARIABLE_FORMS:
            return True
    for combination in combinations:
        if is_covering_overlay(combination):
            return True
    return False


def _rule_could_hide(declarations, variable_values):
    """Whether a rule must be matched in step 1: one of its values could hide text, or it draws an
    overlay, whatever value its variables take (variable_values: every value rules give each one)."""
    forms_by_name = []
    for name, value, _, _ in declarations:
        if name.startswith("--"):
            continue
        forms = _variable_forms(value, variable_values)
        if forms is None:
            return True
        lowered = []
        for form in forms:
            form = with_math_evaluated(form.lower())
            if _could_hide(name, form):
                return True
            lowered.append(form)
        forms_by_name.append((name, lowered))
    return _rule_could_cover(forms_by_name)


def _is_pseudo_candidate(declarations):
    """::before/::after rules worth evaluating: positioned (a possible overlay) or adding words."""
    for name, value, _, _ in declarations:
        if name == "position" and value.lower() == "absolute":
            return True
        if name == "content":
            if "var(" in value:
                return True
            for string in quoted_strings(value):
                letters = 0
                for character in string:
                    if character.isalpha():
                        letters += 1
                if letters >= 2:
                    return True
    return False


def _font_face_with_data_uri(rule):
    """The family name of an @font-face whose font file is embedded in the CSS, or None."""
    family = None
    embedded = False
    for declaration in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
        if declaration.type != "declaration":
            continue
        value = _serialized(declaration.value).strip()
        if declaration.lower_name == "font-family":
            family = value.strip("'\" ").lower()
        elif declaration.lower_name == "src" and "data:" in value.lower():
            embedded = True
    if embedded and family:
        return family
    return None


# Where a rule sits in its stylesheet:
# * layer: the cascade layer's name path, () when unlayered;
# * undecided: inside a block whose condition this reader cannot answer the way Chrome does
#   (@supports, @container, @scope), so the rule may or may not apply;
# * parent_selector: in a nested style rule, the selector that & stands for;
# * scope_root: inside @scope, the selector of the scope root;
# * depth: how many style rules and layers enclose it;
# * parent_depth: how deeply functions nest in parent_selector, or in scope_root.
_Context = namedtuple("_Context", "layer undecided parent_selector scope_root depth parent_depth")
_TOP_LEVEL = _Context((), False, None, None, 0, 0)
# Real stylesheets nest style rules and layers a few levels deep. Past this depth the rules count
# as undecided and are matched without their enclosing selectors and layers (so they may apply more
# widely than in Chrome), since following thousands of levels would take minutes.
MAXIMUM_NESTING_DEPTH = 32
# A nested rule repeats its parent's whole selector list, so selector lists nested in selector
# lists grow exponentially; past this length the same fallback applies.
MAXIMUM_PARENT_SELECTOR_CHARACTERS = 4000
# The selector library recurses once per nested function, as in :is(:is(.x)), and a few hundred
# levels exhaust Python's call stack. Real selectors nest at most 6 deep (in 3,102 stylesheets), so a
# rule whose selector, counted with the selectors it is nested in, nests deeper than this is read as
# * in an undecided block: it may hide any element, or add text before or after it.
MAXIMUM_SELECTOR_DEPTH = 32
_ANY_ELEMENT_OR_GENERATED_BOX = "*, *::before, *::after"


def _token_depth(tokens, limit):
    """How deeply functions and blocks nest in tokens, counting up to limit + 1 at most."""
    deepest = 0
    pending = [(tokens, 1)]
    while pending and deepest <= limit:
        items, level = pending.pop()
        for token in items:
            if token.type == "function":
                children = token.arguments
            elif token.type in _BLOCK_BRACKETS:
                children = token.content
            else:
                continue
            if level > deepest:
                deepest = level
            pending.append((children, level + 1))
    return min(deepest, limit + 1)


def _stand_in_depth(context):
    """How deeply the text standing in for & (or for :scope) nests: :is(parent) or :where(root):is(...)."""
    if context.parent_selector is not None:
        return 1 + context.parent_depth
    if context.scope_root is not None:
        return max(1 + context.parent_depth, 2)
    return 0

# One compiled style rule. selector_text is the selector without whitespace, lowercased (to spot
# rules on :root and html); could_hide is None when only the site's variables can decide it.
_CompiledRule = namedtuple(
    "_CompiledRule",
    "selectors declarations selector_text font_family could_hide pseudo_candidate layer undecided scoped",
)


class _CompiledStylesheet:
    """A stylesheet's style rules in source order, the font families it embeds as data: URIs, and
    where cascade layers are first named: (index of the next rule, layer path, undecided)."""

    def __init__(self):
        self.rules = []
        self.data_font_families = set()
        self.layer_names = []


# Always matches, and adds the specificity of one pseudo-class, as :scope does in Chrome.
_SCOPE_SPECIFICITY = ":is(:root, :not(:root))"


def _selector_text_with_stand_in(tokens, stand_in, scope):
    """(text, replaced) for one selector: & (and in @scope, :scope) written as stand_in."""
    pieces = []
    replaced = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "literal" and token.value == "&":
            pieces.append(stand_in)
            replaced = True
        elif (scope and token.type == "literal" and token.value == ":" and index + 1 < len(tokens)
              and tokens[index + 1].type == "ident" and tokens[index + 1].lower_value == "scope"):
            pieces.append(stand_in + _SCOPE_SPECIFICITY)
            replaced = True
            index += 1
        elif token.type == "function":
            inner_text, inner_replaced = _selector_text_with_stand_in(token.arguments, stand_in, scope)
            pieces.append(serialize_identifier(token.name) + "(" + inner_text + ")")
            if inner_replaced:
                replaced = True
        else:
            pieces.append(_serialized([token]))
        index += 1
    return "".join(pieces), replaced


def _relative_selector_texts(prelude, stand_in, scope):
    """The selectors of a nested or scoped rule, each written relative to stand_in: & (and :scope)
    replaced by it, and a selector without either matched below it. In @scope a selector also
    matches the scope root itself, so that form is added (as a separate selector, since it is
    invalid after a pseudo-element)."""
    selector_tokens = [[]]
    for token in prelude:
        if token.type == "literal" and token.value == ",":
            selector_tokens.append([])
        else:
            selector_tokens[-1].append(token)
    relative_texts = []
    root_texts = []
    for tokens in selector_tokens:
        text, replaced = _selector_text_with_stand_in(tokens, stand_in, scope)
        text = text.strip()
        if replaced:
            relative_texts.append(text)
        else:
            relative_texts.append(f"{stand_in} {text}")
            if scope:
                root_texts.append(f"{text}{stand_in}")
    return relative_texts, root_texts


def _compiled_selector_list(selector_input):
    """cssselect2.compile_selector_list, with Chrome's rule that :has() may not hold a :has(): such a
    selector is invalid, and only dropped from a forgiving :is() or :where() (measured in Chrome 158).
    cssselect2 allows it, and nesting one in another makes matching exponential in the depth. The
    selector is filtered as tokens, so cssselect2 computes specificity from what is left, and reads
    the selectors in :nth-child(An+B of S) filtered too."""
    if isinstance(selector_input, str):
        selector_input = tinycss2.parse_component_value_list(selector_input)
    tokens = _without_nested_has(list(selector_input), False)
    if tokens is None:
        raise cssselect2.SelectorError(None, ":has() inside :has()")
    return cssselect2.compile_selector_list(tokens)


def _without_nested_has(tokens, inside_has):
    """The selector tokens with each :is() and :where() keeping only the selectors valid under the
    nested :has() rule, or None when the rule makes them invalid. Recursion is bounded by
    MAXIMUM_SELECTOR_DEPTH, checked before a selector is compiled."""
    kept = []
    for index, token in enumerate(tokens):
        if token.type != "function":
            kept.append(token)
            continue
        is_pseudo_class = index > 0 and tokens[index - 1] == ":" and not (index > 1 and tokens[index - 2] == ":")
        if is_pseudo_class and token.lower_name == "has":
            if inside_has:
                return None
            arguments = _without_nested_has(token.arguments, True)
        elif is_pseudo_class and token.lower_name in ("is", "where"):
            arguments = _forgiving_selectors(token.arguments, inside_has)
        else:
            arguments = _without_nested_has(token.arguments, inside_has)
        if arguments is None:
            return None
        kept.append(tinycss2.ast.FunctionBlock(token.source_line, token.source_column, token.name, arguments))
    return kept


def _forgiving_selectors(tokens, inside_has):
    """The comma-separated selectors of a forgiving list, without those the nested :has() rule makes invalid."""
    selectors = [[]]
    for token in tokens:
        if token == ",":
            selectors.append([])
        else:
            selectors[-1].append(token)
    kept = []
    for selector in selectors:
        filtered = _without_nested_has(selector, inside_has)
        if filtered is None:
            continue
        if kept:
            kept.append(tinycss2.ast.LiteralToken(None, None, ","))
        kept.extend(filtered)
    return kept


def _rule_selectors(prelude, context):
    """(compiled selectors, selector text, how deeply it nests, the context the rule is read in) of a
    style rule; the text is None when Chrome would drop the rule. A selector nesting deeper than
    MAXIMUM_SELECTOR_DEPTH is read as * in an undecided context."""
    depth = _token_depth(prelude, MAXIMUM_SELECTOR_DEPTH) + _stand_in_depth(context)
    if depth > MAXIMUM_SELECTOR_DEPTH:
        # The text is plain * so that rules nested in this one can be written relative to it.
        undecided_context = context._replace(undecided=True, parent_selector=None, scope_root=None, parent_depth=0)
        return _compiled_selector_list(_ANY_ELEMENT_OR_GENERATED_BOX), "*", 0, undecided_context
    root_texts = []
    if context.parent_selector is not None:
        relative_texts, _ = _relative_selector_texts(prelude, f":is({context.parent_selector})", False)
        selector_text = ", ".join(relative_texts)
    elif context.scope_root is not None:
        relative_texts, root_texts = _relative_selector_texts(prelude, f":where({context.scope_root})", True)
        selector_text = ", ".join(relative_texts)
    else:
        selector_text = _serialized(prelude)
    try:
        selectors = _compiled_selector_list(
            prelude if context.parent_selector is None and context.scope_root is None else selector_text
        )
    except cssselect2.SelectorError:
        return [], None, depth, context
    for root_text in root_texts:
        try:
            selectors += _compiled_selector_list(root_text)
        except cssselect2.SelectorError:
            pass  # reason=a scoped selector ending in a pseudo-element has no form matching the root itself
    return selectors, selector_text, depth, context


def _add_style_rule(selectors, selector_text, declarations, context, compiled):
    # Properties needed only rarely are kept only where they matter, so the full cascade
    # stays small: content on ::before/::after, direction next to unicode-bidi, and
    # font-family apart (looked up only for a headline when the page embeds a font).
    has_pseudo_element = False
    for selector in selectors:
        if selector.pseudo_element in ("before", "after"):
            has_pseudo_element = True
    has_bidi_override = False
    for name, _, _, _ in declarations:
        if name == "unicode-bidi":
            has_bidi_override = True
    font_family = None
    kept_declarations = []
    for declaration in declarations:
        name = declaration[0]
        if name == "font-family":
            font_family = declaration[1]
            continue
        if name == "content" and not has_pseudo_element:
            continue
        if name == "direction" and not has_bidi_override:
            continue
        kept_declarations.append(declaration)
    if not kept_declarations and font_family is None:
        return
    # Without var() the site's variables cannot change the answer, so it is decided once
    # here instead of in every _RuleSet built from this stylesheet (None: decide there).
    uses_variables = False
    for _, value, _, _ in kept_declarations:
        if "var(" in value:
            uses_variables = True
            break
    could_hide = None if uses_variables else _rule_could_hide(kept_declarations, {})
    compiled.rules.append(_CompiledRule(
        selectors, kept_declarations, "".join(selector_text.split()).lower(), font_family, could_hide,
        _is_pseudo_candidate(kept_declarations), context.layer, context.undecided, context.scope_root is not None,
    ))


def _layer_name_paths(prelude):
    """The layer names of an @layer prelude, each split at its dots: "a.b, c" -> [("a", "b"), ("c",)]."""
    paths = []
    for name in _serialized(prelude).split(","):
        name = name.strip()
        if name:
            parts = []
            for part in name.split("."):
                parts.append(part.strip())
            paths.append(tuple(parts))
    return paths


def _scope_root(prelude):
    """(root selector, how deeply it nests) of an @scope prelude: "(.a) to (.b)" -> (".a", 0).
    A block without a root (scoped to the <style> element's parent) gets "*"."""
    for token in prelude:
        if token.type == "() block":
            return _serialized(token.content).strip(), _token_depth(token.content, MAXIMUM_SELECTOR_DEPTH)
    return "*", 0


def _compile_rules(rules, compiled):
    """Compiles style rules into compiled (a _CompiledStylesheet), in source order. Blocks are
    followed with an explicit stack, so deeply nested CSS cannot exhaust Python's call stack."""
    pending = [(iter(rules), _TOP_LEVEL)]
    while pending:
        items, context = pending[-1]
        rule = next(items, None)
        if rule is None:
            pending.pop()
            continue
        if rule.type == "qualified-rule":
            contents = tinycss2.parse_blocks_contents(rule.content, skip_comments=True, skip_whitespace=True)
            declarations = _hiding_declarations(contents)
            nested_rules = []
            for item in contents:
                if item.type in ("qualified-rule", "at-rule"):
                    nested_rules.append(item)
            if not declarations and not nested_rules:
                continue
            selectors, selector_text, selector_depth, rule_context = _rule_selectors(rule.prelude, context)
            if selector_text is None:
                continue
            if declarations:
                _add_style_rule(selectors, selector_text, declarations, rule_context, compiled)
            if nested_rules:
                if context.depth < MAXIMUM_NESTING_DEPTH and len(selector_text) <= MAXIMUM_PARENT_SELECTOR_CHARACTERS:
                    inner_context = rule_context._replace(parent_selector=selector_text, scope_root=None,
                                                          depth=context.depth + 1, parent_depth=selector_depth)
                else:
                    inner_context = rule_context._replace(parent_selector="*", scope_root=None, undecided=True,
                                                          parent_depth=0)
                pending.append((iter(nested_rules), inner_context))
            continue
        if rule.type != "at-rule":
            continue
        keyword = rule.lower_at_keyword
        if keyword == "layer" and rule.content is None:
            for path in _layer_name_paths(rule.prelude):
                if len(context.layer) + len(path) <= MAXIMUM_NESTING_DEPTH:
                    compiled.layer_names.append((len(compiled.rules), context.layer + path, context.undecided))
            continue
        if rule.content is None:
            continue
        if keyword == "font-face":
            family = _font_face_with_data_uri(rule)
            if family is not None:
                compiled.data_font_families.add(family)
            continue
        if keyword == "media":
            if not media_query_applies(_serialized(rule.prelude)):
                continue
            inner_context = context
        elif keyword in ("supports", "container"):
            inner_context = context._replace(undecided=True)
        elif keyword == "layer":
            paths = _layer_name_paths(rule.prelude)
            if len(paths) > 1:
                continue  # Chrome drops a layer block that names several layers
            # An unnamed layer is a new layer of its own.
            layer = context.layer + (paths[0] if paths else (object(),))
            if context.depth >= MAXIMUM_NESTING_DEPTH or len(layer) > MAXIMUM_NESTING_DEPTH:
                inner_context = context._replace(undecided=True)
            else:
                compiled.layer_names.append((len(compiled.rules), layer, context.undecided))
                inner_context = context._replace(layer=layer, depth=context.depth + 1)
        elif keyword == "scope":
            # Chrome ranks scoped rules by how close the scope root is, which this reader does
            # not model, so every @scope block is undecided.
            root, root_depth = _scope_root(rule.prelude)
            inner_context = context._replace(
                undecided=True, parent_selector=None, scope_root=root, parent_depth=root_depth,
            )
        else:
            continue  # @document (Chrome never applies it), @keyframes, @page, @starting-style...
        if context.parent_selector is not None or keyword == "scope":
            # Inside a style rule or @scope, a block holds declarations as well as rules.
            contents = tinycss2.parse_blocks_contents(rule.content, skip_comments=True, skip_whitespace=True)
            declarations = _hiding_declarations(contents)
            if declarations and context.parent_selector is not None:
                selectors, selector_text, _, rule_context = _rule_selectors(
                    tinycss2.parse_component_value_list("&"), inner_context,
                )
                if selector_text is not None:
                    _add_style_rule(selectors, selector_text, declarations, rule_context, compiled)
            nested_rules = []
            for item in contents:
                if item.type in ("qualified-rule", "at-rule"):
                    nested_rules.append(item)
            pending.append((iter(nested_rules), inner_context))
        else:
            pending.append((
                iter(tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)),
                inner_context,
            ))


def _stylesheet_key(css_text):
    return hashlib.sha256(css_text.encode("utf-8", errors="replace")).hexdigest()


def _compiled_stylesheet(css_text, key, cache):
    """The _CompiledStylesheet of one stylesheet, cached by content."""
    cached = cache.lookup(key)
    if cached is not None:
        return cached
    compiled = _CompiledStylesheet()
    _compile_rules(tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True), compiled)
    cache.store(key, compiled, len(css_text))
    return compiled


_UNLAYERED = float("inf")
_SCOPED_ORDER_OFFSET = 10 ** 12


class _LayerOrder:
    """Cascade layers in the order their names first appear, over all of a page's stylesheets.

    A rule's rank is the positions of its layer path, then _UNLAYERED for the rules directly in
    that layer, so a later layer outranks an earlier one, a layer's own rules outrank its sublayers,
    and unlayered rules, ranked (_UNLAYERED,), outrank every layer. !important reverses the order:
    its rank is the negated one.
    Layers first named inside an undecided block (see _Context) are tentative: their place depends
    on whether that block applies, so their rules are undecided too. A tentative layer takes the
    place of its first naming outside such blocks, the later of its two possible places."""

    def __init__(self, inherited=None):
        self.positions = {}
        self.tentative = set()
        self.named_outside_undecided_blocks = set()
        self.next_position = 0
        if inherited is not None:
            self.positions.update(inherited.positions)
            self.tentative.update(inherited.tentative)
            self.named_outside_undecided_blocks.update(inherited.named_outside_undecided_blocks)
            self.next_position = inherited.next_position

    def name(self, path, undecided):
        for length in range(1, len(path) + 1):
            prefix = path[:length]
            if prefix not in self.positions:
                self.positions[prefix] = self.next_position
                self.next_position += 1
                if undecided:
                    self.tentative.add(prefix)
            elif not undecided and prefix in self.tentative and prefix not in self.named_outside_undecided_blocks:
                self.positions[prefix] = self.next_position
                self.next_position += 1
            if not undecided:
                self.named_outside_undecided_blocks.add(prefix)

    def rank(self, path):
        rank = []
        for length in range(1, len(path) + 1):
            rank.append(self.positions[path[:length]])
        rank.append(_UNLAYERED)
        return tuple(rank)

    def is_tentative(self, path):
        for length in range(1, len(path) + 1):
            if path[:length] in self.tentative:
                return True
        return False


def _negated(rank):
    negated = []
    for position in rank:
        negated.append(-position)
    return tuple(negated)


class _RuleSet:
    """Matchers for a group of stylesheets: the rules that could hide text, and all rules.

    Matcher payloads are (order, layer rank, layer rank for !important, undecided, declarations)."""

    def __init__(self, stylesheet_texts, stylesheet_keys, stylesheet_cache, inherited_rules, cache_key):
        """inherited_rules: the _RuleSet of the stylesheets before these in the cascade, or None."""
        self.cache_key = cache_key
        compiled_stylesheets = []
        if inherited_rules is None:
            self.site_variables = {}
            self.site_variable_specificity = {}
            inherited_layers = None
            first_order = 0
        else:
            self.site_variables = dict(inherited_rules.site_variables)
            self.site_variable_specificity = dict(inherited_rules.site_variable_specificity)
            inherited_layers = inherited_rules.layer_order
            first_order = inherited_rules.last_order
        # Every value some rule gives each custom property, these stylesheets' and the earlier ones'.
        # Only the variables these stylesheets define are stored here (with the earlier values
        # too); the rest are read from the earlier rule set, which a site's pages all share.
        self.own_variable_values = {}
        inherited_values = inherited_rules.variable_values if inherited_rules is not None else {}
        self.variable_values = ChainMap(self.own_variable_values, inherited_values)
        # Custom properties defined on narrower selectors (or in undecided blocks), looked up
        # through the full cascade.
        self.scoped_variable_names = set()
        self.data_font_families = set()
        # Only @layer namings set the layer order (rules never do), so it is known before any rule is read.
        self.layer_order = _LayerOrder(inherited_layers)
        for stylesheet_text, key in zip(stylesheet_texts, stylesheet_keys):
            compiled = _compiled_stylesheet(stylesheet_text, key, stylesheet_cache)
            compiled_stylesheets.append(compiled)
            for family in compiled.data_font_families:
                self.data_font_families.add(family)
            for _, path, undecided in compiled.layer_names:
                self.layer_order.name(path, undecided)
        # Variables some undecided block defines: their value depends on which blocks apply.
        self.undecided_variable_names = set()
        for compiled in compiled_stylesheets:
            for rule in compiled.rules:
                undecided = rule.undecided or self.layer_order.is_tentative(rule.layer)
                # A site-wide definition in a layer or an undecided block competes in the
                # cascade (unlayered definitions win), so it is looked up there instead.
                site_wide = rule.selector_text in SITE_WIDE_SELECTORS and not undecided and not rule.layer
                selector_parts = rule.selector_text.split(",")
                # The root element's own values (:root outranks html); body is another element,
                # so its definitions are looked up in the cascade like narrower ones.
                root_level = site_wide and "body" not in selector_parts
                specificity = 1 if ":root" in selector_parts else 0
                for name, value, _, _ in rule.declarations:
                    if name.startswith("--"):
                        values = self.own_variable_values.get(name)
                        if values is None:
                            values = list(inherited_values.get(name, ()))
                            self.own_variable_values[name] = values
                        if value not in values:
                            values.append(value)
                        if root_level:
                            if specificity >= self.site_variable_specificity.get(name, 0):
                                self.site_variables[name] = value
                                self.site_variable_specificity[name] = specificity
                        else:
                            self.scoped_variable_names.add(name)
                        if undecided:
                            self.undecided_variable_names.add(name)
        # Which variables refer to each variable, in any value some rule gives them (see variable_users_of).
        self._inherited_rules = inherited_rules
        self._own_variable_users = {}
        for name, values in self.own_variable_values.items():
            for value in values:
                for reference in _variable_references(value):
                    users = self._own_variable_users.setdefault(reference, set())
                    users.add(name)
        # Rules judged unable to hide with the variable values these stylesheets give, which a
        # page may change (its own CSS, inline styles): (selectors, declarations), and their
        # positions by the variables they use (see _late_hiding_matcher).
        self.variable_dependent_rules = []
        self.rules_using_variable = {}
        self.hiding_matcher = cssselect2.Matcher()
        self.full_matcher = cssselect2.Matcher()
        self.pseudo_matcher = cssselect2.Matcher()
        # Only the rules that define custom properties on narrow selectors, for var() lookups.
        self.variable_matcher = cssselect2.Matcher()
        # Every rule in an undecided block, to tell which elements those blocks can change.
        self.undecided_matcher = cssselect2.Matcher()
        self.has_hiding_rules = False
        self.has_pseudo_rules = False
        self.has_variable_rules = False
        self.has_rules = False
        self.has_undecided_rules = False
        # Rules setting font-family, matched only on demand (see CascadeRules.font_family_for).
        self.font_rules = []
        self._font_matcher = None
        order = first_order
        for compiled in compiled_stylesheets:
            for rule in compiled.rules:
                order += 1
                rank = self.layer_order.rank(rule.layer) if rule.layer else (_UNLAYERED,)
                # Chrome ranks a scoped rule above unscoped ones of equal specificity (scope
                # proximity comes before order), so its order is placed after all of them.
                rule_order = order + _SCOPED_ORDER_OFFSET if rule.scoped else order
                undecided = rule.undecided or self.layer_order.is_tentative(rule.layer)
                if rule.font_family is not None:
                    self.font_rules.append((rule.selectors, order, rank, rule.font_family))
                declarations = rule.declarations
                if not declarations:
                    continue
                # A value this reader cannot validate may or may not apply, like an undecided block.
                has_uncertain_value = False
                for declaration in declarations:
                    if declaration[3] == UNKNOWN:
                        has_uncertain_value = True
                if undecided or has_uncertain_value:
                    self.has_undecided_rules = True
                payload = (rule_order, rank, _negated(rank), undecided, declarations)
                variable_declarations = []
                # Every definition of a variable some narrower, layered or undecided rule also
                # defines, so they compete in one cascade (site-wide ones included).
                for declaration in declarations:
                    if declaration[0] in self.scoped_variable_names:
                        variable_declarations.append(declaration)
                could_hide = rule.could_hide
                if could_hide is None:
                    could_hide = _rule_could_hide(declarations, self.variable_values)
                    if not could_hide and not undecided:
                        position = len(self.variable_dependent_rules)
                        self.variable_dependent_rules.append((rule.selectors, declarations))
                        for name, value, _, _ in declarations:
                            if name.startswith("--"):
                                continue
                            for reference in _variable_references(value):
                                self.rules_using_variable.setdefault(reference, []).append(position)
                if undecided:
                    # Its declarations may combine with others into hiding (an overlay split
                    # between blocks), so the elements it matches always get the full cascade.
                    could_hide = True
                for selector in rule.selectors:
                    self.full_matcher.add_selector(selector, payload)
                    self.has_rules = True
                    if undecided or has_uncertain_value:
                        self.undecided_matcher.add_selector(selector, None)
                    if could_hide:
                        self.hiding_matcher.add_selector(selector, payload)
                        self.has_hiding_rules = True
                    if rule.pseudo_candidate and selector.pseudo_element in ("before", "after"):
                        self.pseudo_matcher.add_selector(selector, payload)
                        self.has_pseudo_rules = True
                    if variable_declarations and selector.pseudo_element is None:
                        self.variable_matcher.add_selector(
                            selector, (rule_order, rank, _negated(rank), undecided, variable_declarations),
                        )
                        self.has_variable_rules = True
        self.last_order = order

    def variable_users_of(self, name):
        """The variables some value of which refers to name, in these stylesheets or earlier ones."""
        users = set(self._own_variable_users.get(name, ()))
        if self._inherited_rules is not None:
            for user in self._inherited_rules.variable_users_of(name):
                users.add(user)
        return users

    def font_matcher(self):
        if self._font_matcher is None:
            self._font_matcher = cssselect2.Matcher()
            for selectors, order, rank, font_family in self.font_rules:
                for selector in selectors:
                    if selector.pseudo_element is None:
                        self._font_matcher.add_selector(selector, (order, rank, font_family))
        return self._font_matcher


def _rule_set(stylesheet_texts, inherited_rules, stylesheet_cache, rule_set_cache):
    """A cached _RuleSet: a site's external stylesheets are shared by all its pages. Its stylesheets
    and the earlier ones it inherits from (inherited_rules) decide it, so they are its cache key."""
    stylesheet_keys = []
    source_size = 0
    for stylesheet_text in stylesheet_texts:
        stylesheet_keys.append(_stylesheet_key(stylesheet_text))
        source_size += len(stylesheet_text)
    cache_key = (tuple(stylesheet_keys), inherited_rules.cache_key if inherited_rules is not None else None)
    cached = rule_set_cache.lookup(cache_key)
    if cached is not None:
        return cached
    rule_set = _RuleSet(stylesheet_texts, stylesheet_keys, stylesheet_cache, inherited_rules, cache_key)
    rule_set_cache.store(cache_key, rule_set, source_size)
    return rule_set


def _late_hiding_matcher(root, external_rules, page_rules):
    """A matcher of the rules a cached rule set judged unable to hide only because a variable they
    use, directly or through other variables, gets more values on this page than that rule set
    can see: from the page's own CSS (for the external stylesheets) or an inline style. None when
    there are none."""
    inline_values = {}
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        style = element.get("style")
        if style and "--" in style:
            for name, value, _, _ in _declarations(style):
                if name.startswith("--"):
                    values = inline_values.setdefault(name, [])
                    if value not in values:
                        values.append(value)
    page_only_names = []
    for name, values in page_rules.own_variable_values.items():
        if len(values) > len(external_rules.variable_values.get(name, ())):
            page_only_names.append(name)
    if not inline_values and not page_only_names:
        return None
    all_values = page_rules.variable_values
    if inline_values:
        combined_values = {}
        for name, values in inline_values.items():
            combined = list(page_rules.variable_values.get(name, ()))
            for value in values:
                if value not in combined:
                    combined.append(value)
            combined_values[name] = combined
        all_values = ChainMap(combined_values, page_rules.variable_values)
    matcher = None
    for rule_set, unseen_names in ((external_rules, page_only_names + list(inline_values)),
                                   (page_rules, list(inline_values))):
        if not rule_set.variable_dependent_rules or not unseen_names:
            continue
        affected = set(unseen_names)
        pending = list(unseen_names)
        while pending:
            name = pending.pop()
            for user in page_rules.variable_users_of(name):
                if user not in affected:
                    affected.add(user)
                    pending.append(user)
        positions = set()
        for name in affected:
            for position in rule_set.rules_using_variable.get(name, ()):
                positions.add(position)
        for position in sorted(positions):
            selectors, declarations = rule_set.variable_dependent_rules[position]
            if _rule_could_hide(declarations, all_values):
                if matcher is None:
                    matcher = cssselect2.Matcher()
                for selector in selectors:
                    matcher.add_selector(selector, None)
    return matcher


def external_rule_set(stylesheets):
    """The _RuleSet of a page's external stylesheets, compiled once and cached for the site's
    other pages (see EXTERNAL_CSS_CACHE_CHARACTERS)."""
    return _rule_set(list(stylesheets or ()), None, _external_stylesheets, _external_rule_sets)


class _SharedElementWrapper(cssselect2.ElementWrapper):
    """An ElementWrapper whose child wrappers are built once and then reused. cssselect2 builds new
    ones on every iteration, so each sibling, :has() or :nth-last-child() test re-wrapped the
    siblings and recomputed their names and classes (203,196 wrappers for 1,468 elements on one
    Euronews page). The shared children point back at their parent: CascadeRules breaks those
    cycles when it is freed.

    Every walk over ancestors, siblings or children is charged to the page's budget of
    MAXIMUM_MATCH_STEPS (match_steps, shared by the page's wrappers). cssselect2 retries every
    combination of ancestors for a descendant chain that fails, so a short selector Chrome accepts
    could otherwise run for hours; past the budget the page raises PageTooComplex."""

    match_steps = None

    def iter_children(self):
        children = self.__dict__.get("shared_children")
        if children is None:
            children = list(super().iter_children())
            for child in children:
                child.match_steps = self.match_steps
            self.shared_children = children
        self._charge(len(children))
        return iter(children)

    @property
    def ancestors(self):
        """As cssselect2 computes them (root first), but in a loop: its recursion, one call per
        element, overflowed the stack on deep pages. Each tuple filled on the way is charged."""
        if self._ancestors is None:
            pending = []
            node = self.parent
            while node is not None and node._ancestors is None:
                pending.append(node)
                node = node.parent
            chain = () if node is None else (*node._ancestors, node)
            for node in reversed(pending):
                self._charge(len(chain))
                node._ancestors = chain
                chain = (*chain, node)
            self._ancestors = chain
        self._charge(len(self._ancestors))
        return self._ancestors

    @property
    def previous_siblings(self):
        """A slice of the parent's shared children, not cached: cssselect2 kept a tuple of all
        earlier siblings on every element (9,000 siblings: 343 MB), built by a recursion that
        overflowed the stack past about 980."""
        if self.parent is None:
            return ()
        self._charge(self.index)
        return tuple(self.parent.shared_children[:self.index])  # filled when CascadeRules wraps the page

    @property
    def etree_siblings(self):
        """The *-of-type, :nth-of-type() and :last-child tests scan this list directly."""
        siblings = self.__dict__["shared_etree_siblings"]
        self._charge(len(siblings))
        return siblings

    @etree_siblings.setter
    def etree_siblings(self, siblings):  # set by cssselect2.ElementWrapper.__init__
        self.__dict__["shared_etree_siblings"] = siblings

    def _charge(self, steps):
        self.match_steps[0] -= steps
        if self.match_steps[0] < 0:
            raise PageTooComplex(f"its CSS selectors take more than {MAXIMUM_MATCH_STEPS:,} steps to match")


# The 284 saved news pages, read with their sites' stylesheets, take 55,056 steps (median) and
# 3,538,381 at most. cssselect2 runs about 2.5 million steps a second.
MAXIMUM_MATCH_STEPS = 10_000_000


# Cascade entries: (important, inline, layer rank, specificity, order, name, value, undecided),
# sorted on their first five fields, so the last entry for a name wins.
_INLINE_LAYER_RANK = (0,)
# How many combinations of an element's undecided declarations are checked; past this the
# element counts as hidden.
MAXIMUM_UNDECIDED_COMBINATIONS = 64
# Steps of var() expansion allowed for one value while finding those combinations.
MAXIMUM_EXPANSION_STEPS = 16 * MAXIMUM_UNDECIDED_COMBINATIONS


class _TooManyCombinations(Exception):
    """An element's undecided rules or variables give more than MAXIMUM_UNDECIDED_COMBINATIONS readings."""


_TOO_MANY = object()


def _matched_entries(matcher, element_wrapper, entries, quirks_mode):
    """Adds the entries of the rules in matcher that match the element (not its pseudo-elements)."""
    for specificity, _, pseudo_type, payload in matcher.match(element_wrapper):
        if pseudo_type is not None:
            continue
        order, rank, important_rank, rule_undecided, declarations = payload
        for position, (name, value, important, validity) in enumerate(declarations):
            undecided = _entry_is_undecided(rule_undecided, validity, quirks_mode)
            if undecided is not None:
                entries.append((important, 0, important_rank if important else rank, specificity, order,
                                name, value, undecided, _alternative_group(order, position, validity)))


def _inline_entries(inline_style, entries, quirks_mode, custom_only=False):
    for position, (name, value, important, validity) in enumerate(_declarations(inline_style)):
        if custom_only and not name.startswith("--"):
            continue
        undecided = _entry_is_undecided(False, validity, quirks_mode)
        if undecided is not None:
            entries.append((important, 1, _INLINE_LAYER_RANK, (0, 0, 0), 0, name, value, undecided,
                            _alternative_group(0, position, validity)))


def _alternative_group(order, position, validity):
    """Which undecided entries apply together in declaration_alternatives: those of one undecided
    rule, while each value this reader cannot validate applies or not on its own (two in one
    rule may be one valid and one not)."""
    if validity == UNKNOWN:
        return (order, position)
    return (order, -1)


def _winning_values(entries):
    """{name: value} from cascade entries. revert-layer takes the value from the layers below."""
    entries.sort(key=lambda entry: entry[:5])
    values = {}
    history = {}
    for entry in entries:
        name = entry[5]
        value = entry[6]
        earlier = history.setdefault(name, [])
        if value == "revert-layer":
            value = None
            for earlier_rank, earlier_value in reversed(earlier):
                if earlier_rank < entry[2]:
                    value = earlier_value
                    break
        earlier.append((entry[2], value))
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value
    return values


def _decided_entries(entries):
    decided = []
    for entry in entries:
        if not entry[7]:
            decided.append(entry)
    return decided


def _has_undecided_entry(entries):
    for entry in entries:
        if entry[7]:
            return True
    return False


class CascadeRules:
    """Drop-in replacement for the simple rule reader: declarations_for(element, tag) -> {property: value}.

    Rules in undecided blocks (see _Context) are applied here; without_undecided_blocks is the
    same page with none of them applied (None when the page has none), and
    declaration_alternatives() gives an element's declarations for each other subset of them."""

    def __init__(self, root, stylesheets=(), quirks_mode=False):
        """quirks_mode: whether the page renders in quirks mode (see document_mode)."""
        self._quirks_mode = quirks_mode
        page_stylesheet_texts = []
        for style_element in root.iter("style"):
            if media_query_applies(style_element.get("media")):
                page_stylesheet_texts.append(style_element.text or "")
        # External stylesheets come first in the cascade, then the page's own <style> blocks.
        external_rules = external_rule_set(stylesheets)
        page_rules = _rule_set(page_stylesheet_texts, external_rules, _page_stylesheets, _page_rule_sets)
        self._site_variables = page_rules.site_variables
        self._root = root
        self._late_hiding_matcher = _late_hiding_matcher(root, external_rules, page_rules)
        self._rule_sets = []
        self._scoped_variable_names = set()
        self._undecided_variable_names = set()
        self.data_uri_font_families = set()
        has_undecided_rules = False
        for rule_set in (external_rules, page_rules):
            if rule_set.has_rules or rule_set.font_rules:
                self._rule_sets.append(rule_set)
            if rule_set.has_undecided_rules:
                has_undecided_rules = True
            for name in rule_set.scoped_variable_names:
                self._scoped_variable_names.add(name)
            for name in rule_set.undecided_variable_names:
                self._undecided_variable_names.add(name)
            for family in rule_set.data_font_families:
                self.data_uri_font_families.add(family)
        self._all_wrappers = {}
        root_wrapper = _SharedElementWrapper.from_html_root(root)
        root_wrapper.match_steps = [MAXIMUM_MATCH_STEPS]
        for element_wrapper in root_wrapper.iter_subtree():
            self._all_wrappers[element_wrapper.etree_element] = element_wrapper
        # Step 1 (does any rule that could hide text, or a ::before/::after worth reading, touch
        # the element?) is decided when an element is first asked about: about half of a page's
        # elements never are (inside <head>, <script>, hidden subtrees).
        self._examined = {}
        self._pseudo_candidates = {}
        self._touched_by_undecided = {}
        self._undecided_on_path = {}
        self._matched = {}
        self._applies_undecided = True
        self._owns_wrappers = True
        self._reset_resolved_caches()
        self.without_undecided_blocks = None
        if has_undecided_rules:
            view = object.__new__(CascadeRules)
            view.__dict__.update(self.__dict__)
            view._applies_undecided = False
            view._owns_wrappers = False
            view._reset_resolved_caches()
            self.without_undecided_blocks = view

    def _reset_resolved_caches(self):
        self._alternatives = {}
        self._resolved_forms_cache = {}
        self._variable_candidates_cache = {}
        self._pseudo_entries_cache = {}
        self._cascaded = {}
        self._resolved = {}
        self._pseudo = {}
        self._scoped_variables_cache = {}
        # var() resolution: where each variable an element sees is declared, its resolved value
        # there, and the elements with a value too long to resolve (see _OVER_BUDGET).
        self._variable_sources = {}
        self._variable_values = {}
        self._unresolvable = set()
        self._resolved_characters = 0

    def _is_examined(self, element):
        """Whether a rule whose values could hide text matches the element (step 1)."""
        examined = self._examined.get(element)
        if examined is None:
            examined = False
            element_wrapper = self._all_wrappers.get(element)
            if element_wrapper is not None:
                for rule_set in self._rule_sets:
                    if rule_set.has_hiding_rules and rule_set.hiding_matcher.match(element_wrapper):
                        examined = True
                        break
                if not examined and self._late_hiding_matcher is not None:
                    examined = bool(self._late_hiding_matcher.match(element_wrapper))
            self._examined[element] = examined
        return examined

    def _has_pseudo_element_rule(self, element):
        """Whether a positioned or wordy ::before/::after rule matches the element (step 1)."""
        candidate = self._pseudo_candidates.get(element)
        if candidate is None:
            candidate = False
            element_wrapper = self._all_wrappers.get(element)
            if element_wrapper is not None:
                for rule_set in self._rule_sets:
                    if rule_set.has_pseudo_rules and rule_set.pseudo_matcher.match(element_wrapper):
                        candidate = True
                        break
            self._pseudo_candidates[element] = candidate
        return candidate

    def __del__(self):
        # Frees the page's wrappers right away, not at the next full garbage collection (which
        # takes up to a second with a site's compiled CSS in memory).
        if getattr(self, "_owns_wrappers", False):
            for element_wrapper in getattr(self, "_all_wrappers", {}).values():
                element_wrapper.__dict__.pop("shared_children", None)

    def _is_touched_by_undecided(self, element):
        touched = self._touched_by_undecided.get(element)
        if touched is None:
            touched = False
            element_wrapper = self._all_wrappers.get(element)
            if element_wrapper is not None:
                for rule_set in self._rule_sets:
                    if rule_set.has_undecided_rules and rule_set.undecided_matcher.match(element_wrapper):
                        touched = True
                        break
            self._touched_by_undecided[element] = touched
        return touched

    def _undecided_rule_on_path(self, element):
        """Whether an undecided rule matches the element or one of its ancestors."""
        unanswered = []
        node = element
        on_path = False
        while node is not None and isinstance(node.tag, str):
            known = self._undecided_on_path.get(node)
            if known is not None:
                on_path = known
                break
            unanswered.append(node)
            node = node.getparent()
        for node in reversed(unanswered):
            on_path = on_path or self._is_touched_by_undecided(node)
            self._undecided_on_path[node] = on_path
        return on_path

    def undecided_rules_may_matter(self, element):
        """Whether undecided rules can change how the element is drawn: they match it, an ancestor
        (backgrounds, stacking, positioned containers, inherited variables) or a child (overlays)."""
        if self.without_undecided_blocks is None and self._applies_undecided:
            return False
        if self._undecided_rule_on_path(element):
            return True
        for child in element:
            if isinstance(child.tag, str) and self._is_touched_by_undecided(child):
                return True
        return False

    def _applicable(self, entries):
        if self._applies_undecided:
            return entries
        return _decided_entries(entries)

    def font_family_for(self, element):
        """The font-family that applies to an element (inherited from the nearest ancestor that
        sets one), or None. Only used for headlines on pages that embed a font in their CSS."""
        node = element
        while node is not None and isinstance(node.tag, str):
            inline_style = node.get("style")
            if inline_style and "font" in inline_style:
                for name, value, _, _ in _declarations(inline_style):
                    if name == "font-family":
                        return value
            element_wrapper = self._all_wrappers.get(node)
            if element_wrapper is not None:
                best = None
                for rule_set in self._rule_sets:
                    if not rule_set.font_rules:
                        continue
                    for specificity, _, pseudo_type, payload in rule_set.font_matcher().match(element_wrapper):
                        if pseudo_type is not None:
                            continue
                        order, rank, font_family = payload
                        if best is None or (rank, specificity, order) > best[0]:
                            best = ((rank, specificity, order), font_family)
                if best is not None:
                    font_family = self._resolve_text(node, best[1])
                    if font_family is _OVER_BUDGET:
                        return ", ".join(sorted(self.data_uri_font_families))
                    if font_family is not _INVALID:
                        return font_family
            node = node.getparent()
        return None

    def _variable_entries(self, element):
        """Cascade entries of the custom properties set on this element by narrow rules or its inline style."""
        entries = []
        element_wrapper = self._all_wrappers.get(element)
        if element_wrapper is not None:
            for rule_set in self._rule_sets:
                if rule_set.has_variable_rules:
                    _matched_entries(rule_set.variable_matcher, element_wrapper, entries, self._quirks_mode)
        inline_style = element.get("style")
        if inline_style and "--" in inline_style:
            _inline_entries(inline_style, entries, self._quirks_mode, custom_only=True)
        return entries

    def _scoped_variables(self, element):
        """Custom properties set on this element by narrow rules or its inline style."""
        cached = self._scoped_variables_cache.get(element)
        if cached is not None:
            return cached
        variables = _winning_values(self._applicable(self._variable_entries(element)))
        self._scoped_variables_cache[element] = variables
        return variables

    def _all_entries(self, element, full):
        """Every cascade entry for one element, undecided ones included (shared by both views).

        Only elements touched by a rule that could hide text get the full cascade, unless
        full is set (for background lookups); others get their inline style only."""
        key = (element, full)
        entries = self._matched.get(key)
        if entries is None:
            entries = []
            element_wrapper = self._all_wrappers.get(element) if full else None
            if element_wrapper is not None:
                # Step 2: the full cascade, so a later or more specific rule can show the text again.
                for rule_set in self._rule_sets:
                    _matched_entries(rule_set.full_matcher, element_wrapper, entries, self._quirks_mode)
            inline_style = element.get("style")
            if inline_style:
                _inline_entries(inline_style, entries, self._quirks_mode)
            entries.sort(key=lambda entry: entry[:5])
            self._matched[key] = entries
        return entries

    def _cascaded_declarations(self, element, full=False):
        """Winning declarations for one element, before resolving var()."""
        full = full or self._is_examined(element)
        cached = self._cascaded.get((element, full))
        if cached is not None:
            return cached
        cascaded = _winning_values(list(self._applicable(self._all_entries(element, full))))
        self._cascaded[(element, full)] = cascaded
        return cascaded

    def _declared_variable(self, node, name):
        """The custom property's own (unresolved) value on node, None when node does not set it;
        node None stands for the site-wide :root values. A variable some narrower rule defines
        (.article { --d: none }) is looked up in node's variable-defining rules; others only in
        inline styles, which is cheaper."""
        if node is None:
            return self._site_variables.get(name)
        if name in self._scoped_variable_names:
            return self._scoped_variables(node).get(name)
        return self._cascaded_declarations(node).get(name)

    def _variable_source(self, origin, name):
        """(node, name) for where the variable seen at origin is declared, as custom properties
        inherit: origin, then its ancestors, then the site-wide values (node None); None when
        nothing declares it."""
        if origin is None:
            if name in self._scoped_variable_names:
                # The site-wide values are the root element's: look it up there in the cascade.
                return self._variable_source(self._root, name)
            return (None, name) if name in self._site_variables else None
        walked = []
        node = origin
        source = None
        found = False
        while node is not None and isinstance(node.tag, str):
            key = (node, name)
            if key in self._variable_sources:
                source = self._variable_sources[key]
                found = True
                break
            walked.append(node)
            if self._declared_variable(node, name) is not None:
                source = key
                found = True
                break
            node = node.getparent()
        if not found and name in self._site_variables:
            source = (None, name)
        for node in walked:
            self._variable_sources[(node, name)] = source
        return source

    def _variable_value(self, source):
        """The resolved value of the variable declared at source (from _variable_source): a text,
        None when source is None, _INVALID or _OVER_BUDGET."""
        if source is None:
            return None
        if source not in self._variable_values:
            self._resolve_variable(source)
        return self._variable_values[source]

    def _resolve_variable(self, start):
        """Resolves the variable declared at start, and every one it refers to, as Chrome does: a
        variable's var() resolves where it is declared, and every variable in a cycle (fallbacks
        included) is invalid. The references are followed with an explicit stack."""
        stack = [(start, iter(_variable_references(self._declared_variable(start[0], start[1]))))]
        position_on_stack = {start: 0}
        in_cycle = set()
        while stack:
            source, names = stack[-1]
            name = next(names, None)
            if name is not None:
                target = self._variable_source(source[0], name)
                if target is None or target in self._variable_values:
                    continue
                if target in position_on_stack:
                    for cycle_source, _ in stack[position_on_stack[target]:]:
                        in_cycle.add(cycle_source)
                    continue
                position_on_stack[target] = len(stack)
                stack.append((target, iter(_variable_references(self._declared_variable(target[0], target[1])))))
                continue
            stack.pop()
            del position_on_stack[source]
            if source in in_cycle:
                self._variable_values[source] = _INVALID
            else:
                self._variable_values[source] = self._resolve_text(
                    source[0], self._declared_variable(source[0], source[1]))

    def _resolve_text(self, origin, value):
        """value with its var() resolved for the element origin: a text, _INVALID or _OVER_BUDGET."""
        if "var(" not in value:
            return value

        def value_of(name):
            return self._variable_value(self._variable_source(origin, name))
        resolved = _substituted(value, value_of)
        if isinstance(resolved, str):
            self._resolved_characters += len(resolved)
            if self._resolved_characters > MAXIMUM_PAGE_RESOLVED_CHARACTERS:
                return _OVER_BUDGET
        return resolved

    def _resolve_variables(self, element, name, value):
        """The value of a name declaration with its var() and env() resolved; "" when invalid
        (Chrome then treats it as unset). Raises _TooManyCombinations when it is too long to
        resolve or uses a function this reader cannot evaluate."""
        # Checked before var(): Chrome may never read a var() in a branch or fallback it skips.
        if _uses_unevaluated_function(name, value):
            raise _TooManyCombinations()
        resolved = self._resolve_text(element, value)
        if resolved is _OVER_BUDGET:
            raise _TooManyCombinations()
        if resolved is _INVALID:
            return ""
        return self._substituted_value(name, resolved, "var(" in value)

    def _substituted_value(self, name, resolved, substituted=True):
        """resolved, a name declaration's value once its var() are substituted (substituted: whether
        it had any), with env() replaced as Chrome does; "" when Chrome rejects it then: the
        declaration is unset, not replaced by an earlier one. Raises _TooManyCombinations when it
        uses a function this reader cannot evaluate (see _UNEVALUATED_FUNCTION)."""
        if "env(" in resolved:
            resolved = _environment_substituted(resolved)
            if resolved is _OVER_BUDGET:
                raise _TooManyCombinations()
            if resolved is _INVALID:
                return ""
            substituted = True
        if _uses_unevaluated_function(name, resolved):
            raise _TooManyCombinations()
        if not substituted:
            return resolved
        validity = _substituted_validity(name, resolved)
        if validity == INVALID or (validity == QUIRKS_ONLY and not self._quirks_mode):
            return ""
        # Evaluated only now: Chrome validates the math as written.
        return with_math_evaluated(resolved)

    def _resolved_declarations(self, element, full=False):
        full = full or self._is_examined(element)
        cached = self._resolved.get((element, full))
        if cached is not None:
            return cached
        resolved = {}
        for name, value in self._cascaded_declarations(element, full).items():
            if name.startswith("--"):
                continue
            try:
                resolved[name] = self._resolve_variables(element, name, value).lower()
            except _TooManyCombinations:
                self._unresolvable.add(element)
                resolved[name] = ""
        self._resolved[(element, full)] = resolved
        return resolved

    def declarations_for(self, element, tag):
        return self._resolved_declarations(element)

    def full_declarations(self, element):
        """Every winning declaration from all rules, also for elements no hiding rule touches."""
        return self._resolved_declarations(element, full=True)

    def declaration_alternatives(self, element):
        """The element's declarations for the other subsets of its undecided rules that may apply
        in Chrome: [] when none touch it, None when there are too many combinations to check.

        Each subset of the undecided rules that can outrank a decided value here gives one; var()
        is resolved with and without the undecided blocks, and with every value an undecided block
        gives a variable it uses. Also None when one of the element's values is too long to
        resolve, so that it counts as hidden."""
        self._resolved_declarations(element)
        self.pseudo_declarations(element)
        if element in self._unresolvable:
            return None
        if element in self._alternatives:
            return self._alternatives[element]
        try:
            alternatives = self._declaration_alternatives(element)
        except _TooManyCombinations:
            alternatives = None
        self._alternatives[element] = alternatives
        return alternatives

    def _variable_candidates(self, element, name):
        """Every value the variable could have at element, whichever undecided blocks apply: each
        definition on the element and its ancestors, and the site-wide one."""
        key = (element, name)
        values = self._variable_candidates_cache.get(key)
        if values is not None:
            return values
        values = []
        node = element
        while node is not None and isinstance(node.tag, str):
            for entry in self._variable_entries(node):
                if entry[5] == name and entry[6] not in values:
                    values.append(entry[6])
            for entry in self._all_entries(node, self._is_examined(node)):
                if entry[5] == name and entry[6] not in values:
                    values.append(entry[6])
            node = node.getparent()
        site_value = self._site_variables.get(name)
        if site_value is not None and site_value not in values:
            values.append(site_value)
        self._variable_candidates_cache[key] = values
        return values

    def _resolved_forms(self, element, name, value, lowercase=True):
        """The values a declaration can resolve to, whichever undecided blocks apply: var() is
        resolved with and without those blocks, and every undecided variable it uses, directly or
        through other variables, takes each value it can have (all combinations of them).
        Raises _TooManyCombinations past MAXIMUM_UNDECIDED_COMBINATIONS forms."""
        key = (element, name, value, lowercase)
        cached = self._resolved_forms_cache.get(key)
        if cached is not None:
            if cached is _TOO_MANY:
                raise _TooManyCombinations()
            return cached
        try:
            forms = self._compute_resolved_forms(element, name, value, lowercase)
        except _TooManyCombinations:
            self._resolved_forms_cache[key] = _TOO_MANY
            raise
        self._resolved_forms_cache[key] = forms
        return forms

    def _compute_resolved_forms(self, element, name, value, lowercase):
        def normalized(resolved):
            return resolved.lower() if lowercase else resolved
        forms = [normalized(self._resolve_variables(element, name, value))]
        undecided_view = self.without_undecided_blocks
        if undecided_view is not None:
            form = normalized(undecided_view._resolve_variables(element, name, value))
            if form not in forms:
                forms.append(form)
        if not self._undecided_variable_names or "var(" not in value:
            return forms
        # Expand var() references one at a time; an undecided variable branches into each of
        # its possible values, any other takes its cascaded value (which may hold more var()).
        pending = [value]
        seen = {value}
        finished = []
        steps = 0
        while pending:
            partial = pending.pop()
            # Every expansion counts, so branches that converge cannot multiply the work.
            steps += 1
            if steps > MAXIMUM_EXPANSION_STEPS:
                raise _TooManyCombinations()
            match = _VARIABLE_REFERENCE.search(partial)
            if match is None:
                if partial not in finished:
                    finished.append(partial)
                continue
            variable_name = match.group(1)
            if variable_name in self._undecided_variable_names:
                replacements = list(self._variable_candidates(element, variable_name))
            else:
                # Its own text, so that undecided variables it refers to branch too. These forms
                # only add to the exact resolutions above.
                source = self._variable_source(element, variable_name)
                replacements = [self._declared_variable(source[0], variable_name) if source is not None else None]
            if None in replacements or not replacements:
                # Undefined here: the var() fallback applies.
                defined = []
                for candidate in replacements:
                    if candidate is not None:
                        defined.append(candidate)
                defined.append(match.group(2) or "")
                replacements = defined
            for replacement in replacements:
                expanded = partial[:match.start()] + replacement.strip() + partial[match.end():]
                if expanded not in seen:
                    seen.add(expanded)
                    pending.append(expanded)
            if len(pending) + len(finished) > MAXIMUM_UNDECIDED_COMBINATIONS:
                raise _TooManyCombinations()
        for partial in finished:
            form = normalized(self._substituted_value(name, partial))
            if form not in forms:
                forms.append(form)
        return forms

    def _declaration_alternatives(self, element):
        full = self._is_examined(element)
        entries = self._all_entries(element, full)
        uses_undecided_variables = False
        if self._undecided_variable_names:
            for entry in entries:
                # Any var() may reach an undecided variable through other variables.
                if not entry[5].startswith("--") and "var(" in entry[6]:
                    uses_undecided_variables = True
                    break
        if not uses_undecided_variables and not _has_undecided_entry(entries):
            return []
        # A rule applies as a whole, so the combinations are subsets of the undecided rules that
        # can outrank a decided value here (each unvalidated value on its own: _alternative_group).
        decided_entries = []
        best_decided = {}
        for entry in entries:  # sorted, lowest priority first
            if not entry[7]:
                decided_entries.append(entry)
                best_decided[entry[5]] = entry[:5]
        entries_by_rule = {}
        for entry in entries:
            # Custom properties count through the values that use them (see _resolved_forms).
            if entry[7] and not entry[5].startswith("--") and (
                    entry[5] not in best_decided or entry[:5] > best_decided[entry[5]]):
                entries_by_rule.setdefault(entry[8], [])
        for entry in entries:
            if entry[7] and entry[8] in entries_by_rule:
                entries_by_rule[entry[8]].append(entry)
        rule_entries = list(entries_by_rule.values())
        if 2 ** len(rule_entries) > MAXIMUM_UNDECIDED_COMBINATIONS:
            return None
        alternatives = []
        for subset in range(2 ** len(rule_entries)):
            chosen = list(decided_entries)
            for position, entries_of_rule in enumerate(rule_entries):
                if subset & (1 << position):
                    chosen.extend(entries_of_rule)
            # Each value can also resolve differently, whichever blocks define its variables.
            subset_alternatives = [{}]
            for name, value in _winning_values(chosen).items():
                if name.startswith("--"):
                    continue
                forms = self._resolved_forms(element, name, value)
                extended = []
                for alternative in subset_alternatives:
                    for form in forms:
                        choice = dict(alternative)
                        choice[name] = form
                        extended.append(choice)
                subset_alternatives = extended
                if len(alternatives) + len(subset_alternatives) > MAXIMUM_UNDECIDED_COMBINATIONS:
                    return None
            for alternative in subset_alternatives:
                if alternative not in alternatives:
                    alternatives.append(alternative)
        return alternatives

    def _pseudo_entries(self, element):
        """{"before": [cascade entries], "after": [...]}, undecided ones included, sorted."""
        entries_by_pseudo = self._pseudo_entries_cache.get(element)
        if entries_by_pseudo is not None:
            return entries_by_pseudo
        entries_by_pseudo = {"before": [], "after": []}
        element_wrapper = self._all_wrappers.get(element)
        if element_wrapper is not None:
            for rule_set in self._rule_sets:
                for specificity, _, pseudo_type, payload in rule_set.full_matcher.match(element_wrapper):
                    if pseudo_type not in entries_by_pseudo:
                        continue
                    order, rank, important_rank, rule_undecided, declarations = payload
                    for position, (name, value, important, validity) in enumerate(declarations):
                        undecided = _entry_is_undecided(rule_undecided, validity, self._quirks_mode)
                        if undecided is not None:
                            entries_by_pseudo[pseudo_type].append((
                                important, 0, important_rank if important else rank, specificity, order,
                                name, value, undecided, _alternative_group(order, position, validity),
                            ))
        for entries in entries_by_pseudo.values():
            entries.sort(key=lambda entry: entry[:5])
        self._pseudo_entries_cache[element] = entries_by_pseudo
        return entries_by_pseudo

    def generated_text_candidates(self, element):
        """(content values, unchecked) for the element's ::before/::after that readers may see,
        whichever undecided blocks apply: every value that can win, unless display:none holds in
        every case. unchecked is True when some value has too many combinations to check; its
        values with all and with none of the undecided blocks applied are still given."""
        if not self._has_pseudo_element_rule(element):
            return [], False
        contents = []
        unchecked = False
        for entries in self._pseudo_entries(element).values():
            candidates_by_name = {}
            for entry in entries:  # lowest priority first
                if not entry[7]:
                    candidates_by_name[entry[5]] = [entry[6]]
                else:
                    candidates_by_name.setdefault(entry[5], [None]).append(entry[6])
            may_show = False
            for value in candidates_by_name.get("display", [None]):
                if value is None:
                    may_show = True
                    continue
                try:
                    forms = self._resolved_forms(element, "display", value)
                except _TooManyCombinations:
                    forms = []
                    may_show = True
                    unchecked = True
                for form in forms:
                    if form != "none":
                        may_show = True
            if not may_show:
                continue
            for value in candidates_by_name.get("content", []):
                if value is None:
                    continue
                try:
                    forms = self._resolved_forms(element, "content", value, lowercase=False)
                except _TooManyCombinations:
                    unchecked = True
                    forms = []
                    views = [self]
                    if self.without_undecided_blocks is not None:
                        views.append(self.without_undecided_blocks)
                    for view in views:
                        resolved = view._resolve_text(element, value)
                        if isinstance(resolved, str):
                            forms.append(resolved)
                for form in forms:
                    if form not in contents:
                        contents.append(form)
        return contents, unchecked

    def pseudo_declarations(self, element):
        """{"before": {...}, "after": {...}} for elements with a positioned or wordy ::before/::after."""
        if not self._has_pseudo_element_rule(element):
            return {}
        cached = self._pseudo.get(element)
        if cached is not None:
            return cached
        entries_by_pseudo = {}
        for pseudo_type, entries in self._pseudo_entries(element).items():
            entries_by_pseudo[pseudo_type] = list(entries)
        result = {}
        for pseudo_type, entries in entries_by_pseudo.items():
            if not entries:
                continue
            resolved = {}
            for name, value in _winning_values(self._applicable(entries)).items():
                if name.startswith("--"):
                    continue
                try:
                    resolved_value = self._resolve_variables(element, name, value)
                except _TooManyCombinations:
                    self._unresolvable.add(element)
                    resolved_value = ""
                resolved[name] = resolved_value if name == "content" else resolved_value.lower()
            result[pseudo_type] = resolved
        self._pseudo[element] = result
        return result

    def background_for(self, element):
        """The nearest declared background color of the element or its ancestors, from all rules."""
        node = element
        while node is not None:
            if isinstance(node.tag, str):
                background = declared_background_color(self._resolved_declarations(node, full=True))
                if background is None and node.get("bgcolor"):
                    background = declared_background_color({"background-color": node.get("bgcolor").strip().lower()})
                if background is not None:
                    return background
            node = node.getparent()
        return None
