"""Whether a page renders in quirks mode, which accepts CSS that standards mode drops (unitless
lengths, hex colours without #). The rules are the HTML parser's: the doctype tokenizer states
(https://html.spec.whatwg.org/multipage/parsing.html#doctype-state and the states after it) and
the "initial insertion mode" (#the-initial-insertion-mode). Limited-quirks mode keeps these CSS
rules strict, so it counts as standards here. lxml is no help: it reports every doctype's name
as html and cannot say whether a doctype was malformed."""

_WHITESPACE = " \t\n\r\f"
_QUIRKS_PUBLIC_IDENTIFIERS = frozenset((
    "-//w3o//dtd w3 html strict 3.0//en//",
    "-/w3c/dtd html 4.0 transitional/en",
    "html",
))
_QUIRKS_SYSTEM_IDENTIFIER = "http://www.ibm.com/data/dtd/v11/ibmxhtml1-transitional.dtd"
_QUIRKS_PUBLIC_PREFIXES = (
    "+//silmaril//dtd html pro v0r11 19970101//",
    "-//as//dtd html 3.0 aswedit + extensions//",
    "-//advasoft ltd//dtd html 3.0 aswedit + extensions//",
    "-//ietf//dtd html 2.0 level 1//",
    "-//ietf//dtd html 2.0 level 2//",
    "-//ietf//dtd html 2.0 strict level 1//",
    "-//ietf//dtd html 2.0 strict level 2//",
    "-//ietf//dtd html 2.0 strict//",
    "-//ietf//dtd html 2.0//",
    "-//ietf//dtd html 2.1e//",
    "-//ietf//dtd html 3.0//",
    "-//ietf//dtd html 3.2 final//",
    "-//ietf//dtd html 3.2//",
    "-//ietf//dtd html 3//",
    "-//ietf//dtd html level 0//",
    "-//ietf//dtd html level 1//",
    "-//ietf//dtd html level 2//",
    "-//ietf//dtd html level 3//",
    "-//ietf//dtd html strict level 0//",
    "-//ietf//dtd html strict level 1//",
    "-//ietf//dtd html strict level 2//",
    "-//ietf//dtd html strict level 3//",
    "-//ietf//dtd html strict//",
    "-//ietf//dtd html//",
    "-//metrius//dtd metrius presentational//",
    "-//microsoft//dtd internet explorer 2.0 html strict//",
    "-//microsoft//dtd internet explorer 2.0 html//",
    "-//microsoft//dtd internet explorer 2.0 tables//",
    "-//microsoft//dtd internet explorer 3.0 html strict//",
    "-//microsoft//dtd internet explorer 3.0 html//",
    "-//microsoft//dtd internet explorer 3.0 tables//",
    "-//netscape comm. corp.//dtd html//",
    "-//netscape comm. corp.//dtd strict html//",
    "-//o'reilly and associates//dtd html 2.0//",
    "-//o'reilly and associates//dtd html extended 1.0//",
    "-//o'reilly and associates//dtd html extended relaxed 1.0//",
    "-//sq//dtd html 2.0 hotmetal + extensions//",
    "-//softquad software//dtd hotmetal pro 6.0::19990601::extensions to html 4.0//",
    "-//softquad//dtd hotmetal pro 4.0::19971010::extensions to html 4.0//",
    "-//spyglass//dtd html 2.0 extended//",
    "-//sun microsystems corp.//dtd hotjava html//",
    "-//sun microsystems corp.//dtd hotjava strict html//",
    "-//w3c//dtd html 3 1995-03-24//",
    "-//w3c//dtd html 3.2 draft//",
    "-//w3c//dtd html 3.2 final//",
    "-//w3c//dtd html 3.2//",
    "-//w3c//dtd html 3.2s draft//",
    "-//w3c//dtd html 4.0 frameset//",
    "-//w3c//dtd html 4.0 transitional//",
    "-//w3c//dtd html experimental 19960712//",
    "-//w3c//dtd html experimental 970421//",
    "-//w3c//dtd w3 html//",
    "-//w3o//dtd w3 html 3.0//",
    "-//webtechs//dtd mozilla html 2.0//",
    "-//webtechs//dtd mozilla html//",
)
# Quirks without a system identifier, limited quirks with one.
_HTML_401_LOOSE_PREFIXES = ("-//w3c//dtd html 4.01 frameset//", "-//w3c//dtd html 4.01 transitional//")


class _Doctype:
    """A doctype read from the page text, positions moving forward over it."""

    def __init__(self, html, position):
        self.html = html
        self.position = position

    def skip_whitespace(self):
        while self.position < len(self.html) and self.html[self.position] in _WHITESPACE:
            self.position += 1

    def next_character(self):
        if self.position < len(self.html):
            return self.html[self.position]
        return ""

    def quoted_identifier(self):
        """The quoted identifier starting here, None when it is missing or cut short by > or the
        end of the page (the tokenizer then forces quirks)."""
        quote = self.next_character()
        if quote not in ("'", '"'):
            return None
        end = self.position + 1
        while end < len(self.html) and self.html[end] != quote:
            if self.html[end] == ">":
                return None
            end += 1
        if end >= len(self.html):
            return None
        identifier = self.html[self.position + 1:end]
        self.position = end + 1
        return identifier


def _doctype_start(html):
    """Where the page's leading doctype starts, after comments and whitespace (a BOM is stripped
    when a page's bytes are decoded); None when the page does not start with one."""
    position = 0
    if html.startswith("﻿"):
        position = 1
    while True:
        while position < len(html) and html[position] in _WHITESPACE:
            position += 1
        if not html.startswith("<!--", position):
            break
        end = html.find("-->", position + 4)
        if end == -1:
            return None
        position = end + 3
    if html[position:position + 9].lower() != "<!doctype":
        return None
    return position + 9


def _identifiers(html):
    """(public identifier, system identifier) of a well-formed html doctype, either None when
    absent; None when the page has no doctype, another name, or one the tokenizer forces into quirks."""
    start = _doctype_start(html)
    if start is None:
        return None
    doctype = _Doctype(html, start)
    doctype.skip_whitespace()
    name_start = doctype.position
    while doctype.next_character() not in ("", ">") and doctype.next_character() not in _WHITESPACE:
        doctype.position += 1
    if html[name_start:doctype.position].lower() != "html":
        return None
    doctype.skip_whitespace()
    if doctype.next_character() == ">":
        return (None, None)
    keyword = html[doctype.position:doctype.position + 6].lower()
    if keyword not in ("public", "system"):
        return None
    doctype.position += 6
    doctype.skip_whitespace()
    first = doctype.quoted_identifier()
    if first is None:
        return None
    if keyword == "system":
        return (None, first)
    doctype.skip_whitespace()
    if doctype.next_character() == ">":
        return (first, None)
    system_identifier = doctype.quoted_identifier()
    if system_identifier is None:
        return None
    return (first, system_identifier)


def is_quirks_mode(html):
    """Whether the page html renders in quirks mode: one without a doctype does, as does a fragment."""
    identifiers = _identifiers(html)
    if identifiers is None:
        return True
    public_identifier, system_identifier = identifiers
    if system_identifier is not None and system_identifier.lower() == _QUIRKS_SYSTEM_IDENTIFIER:
        return True
    if public_identifier is None:
        return False
    public_identifier = public_identifier.lower()
    if public_identifier in _QUIRKS_PUBLIC_IDENTIFIERS or public_identifier.startswith(_QUIRKS_PUBLIC_PREFIXES):
        return True
    return system_identifier is None and public_identifier.startswith(_HTML_401_LOOSE_PREFIXES)
