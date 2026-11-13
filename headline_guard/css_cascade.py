"""A real CSS cascade for the visibility check, using tinycss2 and cssselect2.

Compared with the simple rule reader in html_visibility, this understands any
selector (descendant and child combinators, attributes, :not(), :nth-child()...),
specificity, source order, !important, inline styles, @media rules evaluated for a
desktop screen, and CSS variables (var(--name, fallback)). It reads <style> blocks
and any external stylesheets the caller supplies (it never fetches anything).

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

import hashlib
import re
from collections import OrderedDict

import cssselect2
import tinycss2

from .css_values import (
    PIXELS_PER_EM, VIEWPORT_HEIGHT_PIXELS, VIEWPORT_WIDTH_PIXELS, length_in_pixels, parse_color, plain_number,
    quoted_strings,
)
# html_visibility imports this module only inside functions, so importing it here is safe.
from .html_visibility import (
    CLIPPED_BOX_MAXIMUM_PIXELS, MINIMUM_VISIBLE_OPACITY, _background_color, _filter_hiding_reason,
    _font_shorthand_size, _font_size_is_unreadable, _is_covering_overlay, _is_off_screen_offset, _leading_number,
    _letters_collapsed, _relative_luminance, _translation_is_off_screen,
)

MAXIMUM_VARIABLE_DEPTH = 10
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
}

# Rules on these selectors define site-wide CSS variables, substituted before deciding which rules matter.
SITE_WIDE_SELECTORS = {":root", "html", "body", ":root,html", "html,:root", "html,body", ":root,body"}
UNRESOLVED_VARIABLE_PROPERTIES = {"display", "visibility", "opacity", "font-size"}
_VARIABLE_REFERENCE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)")

_MEDIA_FEATURE = re.compile(r"\(\s*([a-z-]+)\s*(?::\s*([^)]+))?\)")


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


def _length_in_pixels(value):
    match = re.match(r"^\s*(-?\d*\.?\d+)\s*(px|em|rem)?\s*$", value)
    if match is None:
        return None
    number = float(match.group(1))
    if match.group(2) in ("em", "rem"):
        return number * PIXELS_PER_EM
    return number


def media_query_applies(media_text):
    """True when a media query list matches a desktop screen in light mode, as a reader sees it.

    Features it cannot evaluate make that query not apply, so unknown rules never hide text.
    """
    media_text = (media_text or "").strip().lower()
    if not media_text:
        return True
    for query in media_text.split(","):
        query = query.strip()
        if query.startswith("not ") or "print" in query or "speech" in query:
            continue
        query_applies = True
        for feature, feature_value in _MEDIA_FEATURE.findall(query):
            feature_value = (feature_value or "").strip()
            if feature in ("min-width", "max-width", "min-height", "max-height"):
                pixels = _length_in_pixels(feature_value)
                size = VIEWPORT_WIDTH_PIXELS if "width" in feature else VIEWPORT_HEIGHT_PIXELS
                if pixels is None:
                    query_applies = False
                elif feature.startswith("min") and size < pixels:
                    query_applies = False
                elif feature.startswith("max") and size > pixels:
                    query_applies = False
            elif feature == "orientation":
                query_applies = query_applies and feature_value == "landscape"
            elif feature == "prefers-color-scheme":
                query_applies = query_applies and feature_value == "light"
            elif feature in ("hover", "any-hover"):
                query_applies = query_applies and feature_value in ("", "hover")
            elif feature in ("pointer", "any-pointer"):
                query_applies = query_applies and feature_value in ("", "fine")
            else:
                query_applies = False
        if query_applies:
            return True
    return False


def _declarations(tokens):
    """[(name, value, important)] for hiding properties and custom properties (--name)."""
    found = []
    for declaration in tinycss2.parse_declaration_list(tokens, skip_comments=True, skip_whitespace=True):
        if declaration.type != "declaration":
            continue
        name = declaration.name if declaration.name.startswith("--") else declaration.lower_name
        if name in HIDING_PROPERTIES or name.startswith("--"):
            value = tinycss2.serialize(declaration.value).strip()
            if not name.startswith("--"):
                value = value.lower()
            found.append((name, value, declaration.important))
    return found


def _substitute_site_variables(value, site_variables, depth=0):
    if "var(" not in value or depth > MAXIMUM_VARIABLE_DEPTH:
        return value
    match = _VARIABLE_REFERENCE.search(value)
    if match is None:
        return value
    replacement = site_variables.get(match.group(1))
    if replacement is None:
        if match.group(2) is None:
            return value  # defined somewhere more specific: leave unresolved
        replacement = match.group(2)
    substituted = value[:match.start()] + replacement.strip() + value[match.end():]
    return _substitute_site_variables(substituted, site_variables, depth + 1)


def _could_hide(name, value):
    """Whether one declaration could, alone or with others, hide text. Used to pick elements to examine."""
    if name.startswith("--"):
        return False  # custom properties are looked up on demand when a var() is resolved
    if "var(" in value:
        # Still unresolved after substituting the site-wide :root variables: examine only the
        # strongest hiding properties, since modern CSS writes almost every value as a var().
        return name in UNRESOLVED_VARIABLE_PROPERTIES
    if name == "display":
        return value == "none"
    if name == "visibility":
        return value in ("hidden", "collapse")
    if name == "content-visibility":
        return value == "hidden"
    if name == "opacity":
        number = plain_number(value)
        return number is not None and number < MINIMUM_VISIBLE_OPACITY
    if name == "filter":
        return _filter_hiding_reason(value) is not None
    if name == "font-size":
        return _font_size_is_unreadable(value)
    if name == "font":
        shorthand_size = _font_shorthand_size(value)
        return shorthand_size is not None and _font_size_is_unreadable(shorthand_size)
    if name == "letter-spacing":
        return _letters_collapsed(value)
    if name == "line-height":
        pixels = length_in_pixels(value)
        return (pixels is not None and pixels <= CLIPPED_BOX_MAXIMUM_PIXELS) or plain_number(value) == 0
    if name in ("color", "-webkit-text-fill-color"):
        color = parse_color(value)
        return color is not None and (color[3] < MINIMUM_VISIBLE_OPACITY
                                      or _relative_luminance(color) >= LIGHT_TEXT_LUMINANCE)
    if name in ("background", "background-color"):
        return False  # looked up on demand by background_for(), only for light text
    if name in ("clip", "clip-path", "transform"):
        return value not in ("auto", "none")
    if name == "translate":
        return _translation_is_off_screen("", value)
    if name == "scale":
        return re.fullmatch(r"0(\.0*)?(\s+0(\.0*)?)?", value.strip()) is not None
    if name in ("width", "height", "max-width", "max-height"):
        pixels = length_in_pixels(value)
        return pixels is not None and pixels <= CLIPPED_BOX_MAXIMUM_PIXELS
    if name in ("left", "top", "right", "bottom", "margin-left", "margin-top", "text-indent", "inset"):
        first_value = value.split()[0] if value.split() else ""
        return bool(first_value) and _is_off_screen_offset(first_value)
    if name == "z-index":
        number = _leading_number(value)
        return number is not None and number < 0
    if name == "unicode-bidi":
        return value in ("bidi-override", "isolate-override")
    return False


def _rule_could_cover(declarations, site_variables):
    """A rule that draws an opaque overlay over its box (checked on the whole rule, not one value)."""
    values = {}
    for name, value, _ in declarations:
        if not name.startswith("--"):
            values[name] = _substitute_site_variables(value, site_variables).lower()
    return _is_covering_overlay(values)


def _rule_could_hide(declarations, site_variables):
    """Whether a rule must be matched in step 1: one of its values could hide text, or it draws an overlay."""
    for name, value, _ in declarations:
        if _could_hide(name, _substitute_site_variables(value, site_variables).lower()):
            return True
    return _rule_could_cover(declarations, site_variables)


def _is_pseudo_candidate(declarations):
    """::before/::after rules worth evaluating: positioned (a possible overlay) or adding words."""
    for name, value, _ in declarations:
        if name == "position" and value.lower() == "absolute":
            return True
        if name == "content":
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
        value = tinycss2.serialize(declaration.value).strip()
        if declaration.lower_name == "font-family":
            family = value.strip("'\" ").lower()
        elif declaration.lower_name == "src" and "data:" in value.lower():
            embedded = True
    if embedded and family:
        return family
    return None


def _compile_rules(rules, compiled_rules, data_font_families):
    for rule in rules:
        if rule.type == "qualified-rule":
            declarations = _declarations(rule.content)
            if not declarations:
                continue
            try:
                selectors = cssselect2.compile_selector_list(rule.prelude)
            except cssselect2.SelectorError:
                continue
            # Properties needed only rarely are kept only where they matter, so the full cascade
            # stays small: content on ::before/::after, direction next to unicode-bidi, and
            # font-family apart (looked up only for a headline when the page embeds a font).
            has_pseudo_element = False
            for selector in selectors:
                if selector.pseudo_element in ("before", "after"):
                    has_pseudo_element = True
            has_bidi_override = False
            for name, _, _ in declarations:
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
                continue
            prelude_text = "".join(tinycss2.serialize(rule.prelude).split()).lower()
            # Without var() the site's variables cannot change the answer, so it is decided once
            # here instead of in every _RuleSet built from this stylesheet (None: decide there).
            uses_variables = False
            for _, value, _ in kept_declarations:
                if "var(" in value:
                    uses_variables = True
                    break
            could_hide = None if uses_variables else _rule_could_hide(kept_declarations, {})
            compiled_rules.append((selectors, kept_declarations, prelude_text, font_family, could_hide,
                                   _is_pseudo_candidate(kept_declarations)))
        elif rule.type == "at-rule" and rule.content is not None:
            keyword = rule.lower_at_keyword
            if keyword == "font-face":
                family = _font_face_with_data_uri(rule)
                if family is not None:
                    data_font_families.add(family)
                continue
            if keyword == "media" and not media_query_applies(tinycss2.serialize(rule.prelude)):
                continue
            if keyword in ("media", "supports", "layer", "container", "document"):
                _compile_rules(
                    tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True),
                    compiled_rules, data_font_families,
                )


def _stylesheet_key(css_text):
    return hashlib.sha256(css_text.encode("utf-8", errors="replace")).hexdigest()


def _compiled_stylesheet(css_text, key, cache):
    """([(selectors, declarations, selector text, font family, could_hide, pseudo_candidate)],
    {embedded font families}) for one stylesheet, cached by content."""
    cached = cache.lookup(key)
    if cached is not None:
        return cached
    compiled_rules = []
    data_font_families = set()
    _compile_rules(
        tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True),
        compiled_rules, data_font_families,
    )
    compiled = (compiled_rules, data_font_families)
    cache.store(key, compiled, len(css_text))
    return compiled


class _RuleSet:
    """Matchers for a group of stylesheets: the rules that could hide text, and all rules."""

    def __init__(self, stylesheet_texts, stylesheet_keys, stylesheet_cache, inherited_variables, first_order):
        compiled_stylesheets = []
        self.site_variables = dict(inherited_variables)
        # Custom properties defined on narrower selectors, looked up through the full cascade.
        self.scoped_variable_names = set()
        self.data_font_families = set()
        for stylesheet_text, key in zip(stylesheet_texts, stylesheet_keys):
            compiled_rules, data_font_families = _compiled_stylesheet(stylesheet_text, key, stylesheet_cache)
            compiled_stylesheets.append(compiled_rules)
            for family in data_font_families:
                self.data_font_families.add(family)
            for _, declarations, prelude_text, _, _, _ in compiled_rules:
                site_wide = prelude_text in SITE_WIDE_SELECTORS
                for name, value, _ in declarations:
                    if name.startswith("--"):
                        if site_wide:
                            self.site_variables[name] = value
                        else:
                            self.scoped_variable_names.add(name)
        self.hiding_matcher = cssselect2.Matcher()
        self.full_matcher = cssselect2.Matcher()
        self.pseudo_matcher = cssselect2.Matcher()
        # Only the rules that define custom properties on narrow selectors, for var() lookups.
        self.variable_matcher = cssselect2.Matcher()
        self.has_hiding_rules = False
        self.has_pseudo_rules = False
        self.has_variable_rules = False
        self.has_rules = False
        # Rules setting font-family, matched only on demand (see CascadeRules.font_family_for).
        self.font_rules = []
        self._font_matcher = None
        order = first_order
        for compiled_rules in compiled_stylesheets:
            for selectors, declarations, prelude_text, font_family, could_hide, pseudo_candidate in compiled_rules:
                order += 1
                if font_family is not None:
                    self.font_rules.append((selectors, order, font_family))
                if not declarations:
                    continue
                variable_declarations = []
                if prelude_text not in SITE_WIDE_SELECTORS:
                    for declaration in declarations:
                        if declaration[0].startswith("--"):
                            variable_declarations.append(declaration)
                if could_hide is None:
                    could_hide = _rule_could_hide(declarations, self.site_variables)
                for selector in selectors:
                    self.full_matcher.add_selector(selector, (order, declarations))
                    self.has_rules = True
                    if could_hide:
                        self.hiding_matcher.add_selector(selector, (order, declarations))
                        self.has_hiding_rules = True
                    if pseudo_candidate and selector.pseudo_element in ("before", "after"):
                        self.pseudo_matcher.add_selector(selector, (order, declarations))
                        self.has_pseudo_rules = True
                    if variable_declarations and selector.pseudo_element is None:
                        self.variable_matcher.add_selector(selector, (order, variable_declarations))
                        self.has_variable_rules = True
        self.last_order = order

    def font_matcher(self):
        if self._font_matcher is None:
            self._font_matcher = cssselect2.Matcher()
            for selectors, order, font_family in self.font_rules:
                for selector in selectors:
                    if selector.pseudo_element is None:
                        self._font_matcher.add_selector(selector, (order, font_family))
        return self._font_matcher


def _rule_set(stylesheet_texts, inherited_variables, first_order, stylesheet_cache, rule_set_cache):
    """A cached _RuleSet: a site's external stylesheets are shared by all its pages."""
    stylesheet_keys = []
    source_size = 0
    for stylesheet_text in stylesheet_texts:
        stylesheet_keys.append(_stylesheet_key(stylesheet_text))
        source_size += len(stylesheet_text)
    cache_key = (tuple(stylesheet_keys), first_order, tuple(sorted(inherited_variables.items())))
    cached = rule_set_cache.lookup(cache_key)
    if cached is not None:
        return cached
    rule_set = _RuleSet(stylesheet_texts, stylesheet_keys, stylesheet_cache, inherited_variables, first_order)
    rule_set_cache.store(cache_key, rule_set, source_size)
    return rule_set


def external_rule_set(stylesheets):
    """The _RuleSet of a page's external stylesheets, compiled once and cached for the site's
    other pages (see EXTERNAL_CSS_CACHE_CHARACTERS)."""
    return _rule_set(list(stylesheets or ()), {}, 0, _external_stylesheets, _external_rule_sets)


class _SharedElementWrapper(cssselect2.ElementWrapper):
    """An ElementWrapper whose child wrappers are built once and then reused. cssselect2 builds new
    ones on every iteration, so each sibling, :has() or :nth-last-child() test re-wrapped the
    siblings and recomputed their names and classes (203,196 wrappers for 1,468 elements on one
    Euronews page). The shared children point back at their parent: CascadeRules breaks those
    cycles when it is freed."""

    def iter_children(self):
        children = self.__dict__.get("shared_children")
        if children is None:
            children = list(super().iter_children())
            self.shared_children = children
        return iter(children)


class CascadeRules:
    """Drop-in replacement for the simple rule reader: declarations_for(element, tag) -> {property: value}."""

    def __init__(self, root, stylesheets=()):
        page_stylesheet_texts = []
        for style_element in root.iter("style"):
            if media_query_applies(style_element.get("media")):
                page_stylesheet_texts.append(style_element.text or "")
        # External stylesheets come first in the cascade, then the page's own <style> blocks.
        external_rules = external_rule_set(stylesheets)
        page_rules = _rule_set(page_stylesheet_texts, external_rules.site_variables, external_rules.last_order,
                               _page_stylesheets, _page_rule_sets)
        self._site_variables = page_rules.site_variables
        self._rule_sets = []
        self._scoped_variable_names = set()
        self.data_uri_font_families = set()
        for rule_set in (external_rules, page_rules):
            if rule_set.has_rules or rule_set.font_rules:
                self._rule_sets.append(rule_set)
            for name in rule_set.scoped_variable_names:
                self._scoped_variable_names.add(name)
            for family in rule_set.data_font_families:
                self.data_uri_font_families.add(family)
        self._all_wrappers = {}
        for element_wrapper in _SharedElementWrapper.from_html_root(root).iter_subtree():
            self._all_wrappers[element_wrapper.etree_element] = element_wrapper
        # Step 1 (does any rule that could hide text, or a ::before/::after worth reading, touch
        # the element?) is decided when an element is first asked about: about half of a page's
        # elements never are (inside <head>, <script>, hidden subtrees).
        self._examined = {}
        self._pseudo_candidates = {}
        self._cascaded = {}
        self._resolved = {}
        self._pseudo = {}
        self._scoped_variables_cache = {}
        self._inherited_variables = {}

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
        for element_wrapper in getattr(self, "_all_wrappers", {}).values():
            element_wrapper.__dict__.pop("shared_children", None)

    def font_family_for(self, element):
        """The font-family that applies to an element (inherited from the nearest ancestor that
        sets one), or None. Only used for headlines on pages that embed a font in their CSS."""
        node = element
        while node is not None and isinstance(node.tag, str):
            inline_style = node.get("style")
            if inline_style and "font" in inline_style:
                for name, value, _ in _declarations(inline_style):
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
                        order, font_family = payload
                        if best is None or (specificity, order) > best[0]:
                            best = ((specificity, order), font_family)
                if best is not None:
                    return self._resolve_variables(node, best[1])
            node = node.getparent()
        return None

    def _scoped_variables(self, element):
        """Custom properties set on this element by narrow rules or its inline style."""
        cached = self._scoped_variables_cache.get(element)
        if cached is not None:
            return cached
        entries = []
        element_wrapper = self._all_wrappers.get(element)
        if element_wrapper is not None:
            for rule_set in self._rule_sets:
                if not rule_set.has_variable_rules:
                    continue
                for specificity, _, pseudo_type, payload in rule_set.variable_matcher.match(element_wrapper):
                    if pseudo_type is not None:
                        continue
                    order, declarations = payload
                    for name, value, important in declarations:
                        entries.append((important, 0, specificity, order, name, value))
        inline_style = element.get("style")
        if inline_style and "--" in inline_style:
            for name, value, important in _declarations(inline_style):
                if name.startswith("--"):
                    entries.append((important, 1, (0, 0, 0), 0, name, value))
        entries.sort(key=lambda entry: entry[:4])
        variables = {}
        for entry in entries:
            variables[entry[4]] = entry[5]
        self._scoped_variables_cache[element] = variables
        return variables

    def _cascaded_declarations(self, element, full=False):
        """Winning declarations for one element, before resolving var().

        Only elements touched by a rule that could hide text get the full cascade, unless
        full is set (for background lookups); others get their inline style only.
        """
        full = full or self._is_examined(element)
        cached = self._cascaded.get((element, full))
        if cached is not None:
            return cached
        entries = []
        element_wrapper = self._all_wrappers.get(element) if full else None
        if element_wrapper is not None:
            # Step 2: the full cascade, so a later or more specific rule can show the text again.
            for rule_set in self._rule_sets:
                for specificity, _, pseudo_type, payload in rule_set.full_matcher.match(element_wrapper):
                    if pseudo_type is not None:
                        continue
                    order, declarations = payload
                    for name, value, important in declarations:
                        entries.append((important, 0, specificity, order, name, value))
        inline_style = element.get("style")
        if inline_style:
            for name, value, important in _declarations(inline_style):
                entries.append((important, 1, (0, 0, 0), 0, name, value))
        entries.sort(key=lambda entry: entry[:4])
        cascaded = {}
        for entry in entries:
            cascaded[entry[4]] = entry[5]
        self._cascaded[(element, full)] = cascaded
        return cascaded

    def _custom_property(self, element, name):
        """Custom properties inherit: the element, then its ancestors, then the site-wide :root values.

        A variable some narrower rule defines (.article { --d: none }) is looked up in each
        ancestor's variable-defining rules; others only in inline styles, which is cheaper.
        """
        key = (element, name)
        if key in self._inherited_variables:
            return self._inherited_variables[key]
        if name in self._scoped_variable_names:
            value = self._scoped_variables(element).get(name)
        else:
            value = self._cascaded_declarations(element).get(name)
        if value is None:
            parent = element.getparent()
            if parent is not None and isinstance(parent.tag, str):
                value = self._custom_property(parent, name)
            else:
                value = self._site_variables.get(name)
        self._inherited_variables[key] = value
        return value

    def _resolve_variables(self, element, value, depth=0):
        if "var(" not in value or depth > MAXIMUM_VARIABLE_DEPTH:
            return value
        match = _VARIABLE_REFERENCE.search(value)
        if match is None:
            return value
        replacement = self._custom_property(element, match.group(1))
        if replacement is None:
            replacement = match.group(2) or ""
        resolved = value[:match.start()] + replacement.strip() + value[match.end():]
        return self._resolve_variables(element, resolved, depth + 1)

    def _resolved_declarations(self, element, full=False):
        full = full or self._is_examined(element)
        cached = self._resolved.get((element, full))
        if cached is not None:
            return cached
        resolved = {}
        for name, value in self._cascaded_declarations(element, full).items():
            if name.startswith("--"):
                continue
            resolved[name] = self._resolve_variables(element, value).lower()
        self._resolved[(element, full)] = resolved
        return resolved

    def declarations_for(self, element, tag):
        return self._resolved_declarations(element)

    def full_declarations(self, element):
        """Every winning declaration from all rules, also for elements no hiding rule touches."""
        return self._resolved_declarations(element, full=True)

    def pseudo_declarations(self, element):
        """{"before": {...}, "after": {...}} for elements with a positioned or wordy ::before/::after."""
        if not self._has_pseudo_element_rule(element):
            return {}
        cached = self._pseudo.get(element)
        if cached is not None:
            return cached
        entries_by_pseudo = {"before": [], "after": []}
        element_wrapper = self._all_wrappers.get(element)
        if element_wrapper is not None:
            for rule_set in self._rule_sets:
                for specificity, _, pseudo_type, payload in rule_set.full_matcher.match(element_wrapper):
                    if pseudo_type not in entries_by_pseudo:
                        continue
                    order, declarations = payload
                    for name, value, important in declarations:
                        entries_by_pseudo[pseudo_type].append((important, specificity, order, name, value))
        result = {}
        for pseudo_type, entries in entries_by_pseudo.items():
            if not entries:
                continue
            entries.sort(key=lambda entry: entry[:3])
            cascaded = {}
            for entry in entries:
                cascaded[entry[3]] = entry[4]
            resolved = {}
            for name, value in cascaded.items():
                if name.startswith("--"):
                    continue
                if name == "content":
                    resolved[name] = self._resolve_variables(element, value)
                else:
                    resolved[name] = self._resolve_variables(element, value).lower()
            result[pseudo_type] = resolved
        self._pseudo[element] = result
        return result

    def background_for(self, element):
        """The nearest declared background color of the element or its ancestors, from all rules."""
        node = element
        while node is not None:
            if isinstance(node.tag, str):
                background = _background_color(self._resolved_declarations(node, full=True))
                if background is None and node.get("bgcolor"):
                    background = _background_color({"background-color": node.get("bgcolor").strip().lower()})
                if background is not None:
                    return background
            node = node.getparent()
        return None
