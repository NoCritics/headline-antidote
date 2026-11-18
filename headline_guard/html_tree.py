"""Parses HTML the way Chrome does and returns it as an lxml tree, which the rest of the reader uses.

libxml2, the parser under lxml, splits some markup differently from the HTML standard: a doctype
with an unclosed quote runs on to the next quote, an escaped <script> ends at its first </script>,
<!-- opens a comment inside <textarea>, and elements nested deeper than 255 are dropped. Each
difference changes which text looks visible, so a page could hide text from Chrome's reader while
showing it to this one. lexbor (through selectolax) follows the standard's parsing algorithm
(https://html.spec.whatwg.org/multipage/parsing.html); its tree is copied into lxml elements."""

import re

import lxml.html
from lxml import etree
from selectolax.lexbor import LexborHTMLParser

# Characters an lxml tree cannot hold. A form feed is whitespace in HTML, so it becomes a space;
# the others (C0 controls, U+FFFE, U+FFFF) are dropped, as libxml2 dropped them.
_NOT_IN_XML = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")
# A name for elements whose tag lxml cannot hold, such as <p<x>: Chrome renders them as unknown
# inline elements, which this name also is.
UNNAMED_TAG = "x-unnamed"
# lexbor's tree building takes time quadratic in nesting depth (each block start tag and each
# unmatched end tag walks the open elements): 40,000 "<" took 9 s, 20,000 at most 1.7 s on
# this machine. Every tag starts with "<", so their count bounds the work. The saved real pages
# have at most 9,230.
MAXIMUM_TAG_OPENINGS = 20_000
# Chrome attaches an element to its parent's parent once its open elements are more than this
# deep (Blink's kMaximumHTMLParserDOMTreeDepth), which this copy does not reproduce. Open
# elements are as deep as the tree, plus at most 3 per table (the table, its section and row
# stay open under content placed before the table), so a page that could reach the limit is not
# read. The saved real pages reach at most 39.
CHROME_DEPTH_LIMIT = 512
OPEN_ELEMENTS_PER_TABLE = 3


class PageTooComplex(Exception):
    """The page is too large to parse quickly, or may nest past Chrome's depth limit, so it is
    not read statically."""


def parse_html(html):
    """The lxml tree of a page, rooted at <html>. Any markup is parsed as a whole document, as
    Chrome parses it, with scripting on, so <noscript> content is not part of the page.
    Raises PageTooComplex for a page this reader cannot parse as Chrome would."""
    tag_openings = html.count("<")
    if tag_openings > MAXIMUM_TAG_OPENINGS:
        raise PageTooComplex(f'{tag_openings} "<" in the page, more than the {MAXIMUM_TAG_OPENINGS} read statically')
    deepest_parent = CHROME_DEPTH_LIMIT - OPEN_ELEMENTS_PER_TABLE * html.lower().count("<table")
    lexbor_root = LexborHTMLParser(html, scripting=True).root
    root = lxml.html.document_fromstring("<html></html>")
    _set_attributes(root, _xml_attributes(lexbor_root))
    _copy_children(lexbor_root.child, root, deepest_parent)
    return root


def _content_start(node, in_noscript_markup):
    """(first node to copy under an element, whether it is inside a <noscript>'s markup).
    Content that is not part of the page is copied too, so that the reader can report it as
    hidden: a <template>'s content, and the markup in a <noscript> (raw text with scripting on).
    That markup is parsed with scripting off, as a scraper reads it, so a <noscript> inside it
    is already elements and nothing is parsed twice."""
    if node.tag == "template":
        fragments = node.template_fragments()
        return (fragments[0].child if fragments else None), in_noscript_markup
    if node.tag == "noscript" and not in_noscript_markup and node.child is not None:
        return LexborHTMLParser(node.child.text_content or "", is_fragment=True).root, True
    return node.child, in_noscript_markup


def _xml_text(text):
    if _NOT_IN_XML.search(text):
        return _NOT_IN_XML.sub("", text.replace("\x0c", " "))
    return text


def _xml_attributes(node):
    attributes = {}
    for name, value in node.attributes.items():
        attributes[name.lower()] = _xml_text(value) if value is not None else ""
    return attributes


def _new_element(parent, node):
    tag = node.tag.lower()
    attributes = _xml_attributes(node)
    try:
        return etree.SubElement(parent, tag, attributes)
    except ValueError:  # a tag or attribute name lxml cannot hold
        pass
    try:
        element = etree.SubElement(parent, tag)
    except ValueError:
        element = etree.SubElement(parent, UNNAMED_TAG)
    _set_attributes(element, attributes)
    return element


def _set_attributes(element, attributes):
    for name, value in attributes.items():
        try:
            element.set(name, value)
        except ValueError:  # an attribute name lxml cannot hold, such as a"b: left out
            pass


def _append_text(parent, text):
    if len(parent):
        last_child = parent[-1]
        last_child.tail = (last_child.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _copy_children(first_node, root, deepest_parent):
    """Copies first_node and its following siblings, with their descendants, under root (at
    depth 1). An explicit stack, so that depth costs no recursion. Raises PageTooComplex for an
    element whose parent is deeper than deepest_parent, outside a <noscript>'s markup."""
    pending = [(first_node, root, 1, False)]
    while pending:
        node, parent, parent_depth, in_noscript_markup = pending.pop()
        while node is not None:
            if node.is_element_node:
                if parent_depth > deepest_parent and not in_noscript_markup:  # Chrome builds no tree there
                    raise PageTooComplex(
                        f"nested {parent_depth + 1} deep: Chrome may move elements past"
                        f" {CHROME_DEPTH_LIMIT} open elements, which this reader does not reproduce")
                element = _new_element(parent, node)
                pending.append((node.next, parent, parent_depth, in_noscript_markup))
                content_start, content_in_noscript_markup = _content_start(node, in_noscript_markup)
                pending.append((content_start, element, parent_depth + 1, content_in_noscript_markup))
                break
            if node.is_text_node:
                text = _xml_text(node.text_content or "")
                if text:
                    _append_text(parent, text)
            elif node.is_comment_node:
                comment = etree.Comment(" ")
                # comment_content strips whitespace; the markup (<!--...-->) keeps it exactly.
                comment.text = _xml_text(node.html[4:-3])  # the setter, unlike Comment(), allows "--"
                parent.append(comment)
            node = node.next
