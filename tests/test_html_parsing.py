"""The page is split into tags, comments and text as Chrome's HTML parser splits it. libxml2 (under
lxml) reads several constructs differently: a doctype with an unclosed quote, a comment closed by
--!> or written <!-->, <!--> inside a <textarea>, an escaped script. Each difference changes which
text the reader thinks is visible, and some hide a hiding wrapper from it, so that text Chrome
never shows reaches the model as visible text. The expected texts are Chrome 157's innerText
(whitespace collapsed); tests/test_browser_check.ParserChromeTests checks them against Chrome."""

import time
import unittest

from headline_guard.html_tree import MAXIMUM_TAG_OPENINGS, parse_html
from headline_guard.html_visibility import extract_visible_text

HEADLINE = "Alphabet shares surge after dodging antitrust breakup bullet"
ARTICLE = (f"<html><head><title>{HEADLINE}</title></head><body><article><h1>{HEADLINE}</h1>"
           '<div style="display:none">losses and layoffs</div><p class="a">Body text.</p></article>'
           "</body></html>")
HIDDEN_AFTER_COMMENT = '<div style="display:none"><!-- -->payload</div><p>Body text.</p></body></html>'


SVG_NOSCRIPT_PAGE = ("<html><body><p>Body</p><svg><noscript><g>a</g><text>PAYLOAD</text></noscript></svg>"
                     "</body></html>")


def nested_page(depth):
    return ("<html><body>" + "<div>" * depth + '<span>deep</span><b style="display:none">hidden</b>'
            + "</div>" * depth + "<p>after</p></body></html>")


# (page, the text Chrome shows)
CHROME_PARSED_PAGES = (
    # The doctype ends at its first >, even inside a quoted identifier.
    ('<!doctype html public "x>' + ARTICLE, f"{HEADLINE} Body text."),
    ("<!doctype html public 'x>" + ARTICLE, f"{HEADLINE} Body text."),
    ('<!doctype html system "x>' + ARTICLE, f"{HEADLINE} Body text."),
    ('<!doctype html public "a" "x>' + ARTICLE, f"{HEADLINE} Body text."),
    ('<!doctype html public "x' + ARTICLE, f"{HEADLINE} Body text."),
    ('<!-- c --><!doctype html public "x>' + ARTICLE, f"{HEADLINE} Body text."),
    ('<!doctype html public "x\n>' + ARTICLE, f"{HEADLINE} Body text."),
    ('x<!doctype html public "x><html><body><p>one</p><p class="a">two</p></body></html>', "x one two"),
    # A comment ends at --> or --!>, and <!--> and <!---> are complete comments.
    ("<html><body><!-->" + HIDDEN_AFTER_COMMENT, "Body text."),
    ("<html><body><!--->" + HIDDEN_AFTER_COMMENT, "Body text."),
    ("<!--><html><body>" + HIDDEN_AFTER_COMMENT, "Body text."),
    ("<html><body><!--x--!>" + HIDDEN_AFTER_COMMENT, "Body text."),
    # <?, <!x and </ followed by a non-letter are comments up to the first >; </> is dropped.
    ('<html><body><? x ><p class="a">two</p></body></html>', "two"),
    ('<html><body><!x ><p class="a">two</p></body></html>', "two"),
    ("<html><body></ x>SEEN</body></html>", "SEEN"),
    ("<html><body></>SEEN</body></html>", "SEEN"),
    # Inside raw text, escapable raw text and attribute values, <!-- opens nothing...
    ('<html><body><textarea style="display:none"><!--</textarea>SEEN<p>-->x</p></body></html>', "SEEN -->x"),
    ("<html><head><title><!--</title></head><body>SEEN--></body></html>", "SEEN-->"),
    ('<html><body><p title="<!--">SEEN</p><p>--></p></body></html>', "SEEN -->"),
    ('<html><body><p a"b="<!--">SEEN</p>--></body></html>', "SEEN -->"),
    ("<html><body><style><!--</style>SEEN<p>--></p></body></html>", "SEEN -->"),
    ("<html><body><script><!--</script>SEEN<p>Body</p></body></html>", "SEEN Body"),
    # ...except that a script escaped with <!-- and holding <script> runs past its first </script>.
    ("<html><body><script><!--<script></script>PAYLOAD</script><p>Body</p></body></html>", "Body"),
    # Everything after <plaintext> is text, and in SVG a CDATA section is text too.
    ("<html><body><plaintext><!--x</body></html>", "<!--x</body></html>"),
    ("<html><body><p><svg><text><![CDATA[SEEN]]></text></svg></p><p><![CDATA[x>y]]></p></body></html>",
     "SEEN y]]>"),
    ("<html><body><template>PAYLOAD</template><p>Body</p></body></html>", "Body"),
    # With scripting on, a <noscript> in <head> is text, so its markup opens no <body>.
    ("<html><head><noscript><p>PAYLOAD</p></noscript></head><body><p>Body</p></body></html>", "Body"),
    # In SVG a <noscript> is an unknown SVG element: its content is elements, and none is drawn.
    (SVG_NOSCRIPT_PAGE, "Body"),
    # A <title> in <body> is not displayed (Chrome's default stylesheet has title{display:none}).
    ("<html><body><title>PAYLOAD</title><p>x</p></body></html>", "x"),
    ("<html><body><p>a<title>PAYLOAD</title>b</p></body></html>", "ab"),
    ("<html><body><title><!--</title>SEEN--></body></html>", "SEEN-->"),
    # A stray > opens <body> early, so the page's <title> lands in it.
    ('<!doctype html public "x>>' + ARTICLE, f"> {HEADLINE} Body text."),
)


def table_chain_page(units):
    """Tables nested through foster-parented <div>s. At 128 units Chrome moves the <b> out of
    the <em> (measured in Chrome 157), where the rule then hides it."""
    return ("<html><head><style>.x + b { display: none }</style></head><body>"
            + "<table><tr><div><td>" * units + '<em class="x"><b>PAYLOAD</b></em></body></html>')


def flag_kinds(page):
    from headline_guard import HeadlineGuard, PAPER_WATCHLIST

    kinds = []
    for flag in HeadlineGuard(PAPER_WATCHLIST).analyze_html(page).flags:
        kinds.append(flag.kind)
    return kinds


class ParsedLikeChromeTests(unittest.TestCase):
    def test_visible_text_is_what_chrome_shows(self):
        for page, chrome_text in CHROME_PARSED_PAGES:
            with self.subTest(page=page):
                self.assertEqual(extract_visible_text(page)[0], chrome_text)

    def test_text_a_browser_does_not_display_is_reported_hidden(self):
        # A scraper that reads the markup passes this text on, so it is reported.
        for tag in ("template", "noscript"):
            with self.subTest(tag=tag):
                page = f"<html><body><{tag}><p>PAYLOAD</p></{tag}><p>Body</p></body></html>"
                visible_text, hidden_fragments = extract_visible_text(page)
                self.assertEqual(visible_text, "Body")
                hidden_texts = []
                for fragment in hidden_fragments:
                    hidden_texts.append(fragment.text)
                self.assertEqual(hidden_texts, ["PAYLOAD"])

    def test_a_title_in_the_body_is_reported_hidden(self):
        visible_text, hidden_fragments = extract_visible_text("<html><body><title>PAYLOAD</title><p>Body</p>")
        self.assertEqual(visible_text, "Body")
        hidden_texts = []
        for fragment in hidden_fragments:
            hidden_texts.append(fragment.text)
        self.assertEqual(hidden_texts, ["PAYLOAD"])

    def test_one_leading_byte_order_mark_is_not_text(self):
        # Chrome drops one leading BOM when it decodes a page's bytes; a second is text, and opens
        # <body> before the <title> (measured with pages served as bytes, since set_content keeps it).
        head = "<!doctype html><html><head><title>T</title></head><body><p>x</p></body></html>"
        self.assertEqual(extract_visible_text("﻿" + head), ("x", []))
        visible_text, hidden_fragments = extract_visible_text("﻿﻿" + head)
        self.assertEqual(visible_text, "﻿ x")
        self.assertEqual(len(hidden_fragments), 1)

    def test_the_slowest_page_read_statically_is_read_in_seconds(self):
        # A <select> of options is the slowest shape found for lexbor: 1.7 s on this machine.
        page = "<html><body><select>" + "<option>" * (MAXIMUM_TAG_OPENINGS - 3)
        start = time.perf_counter()
        extract_visible_text(page)
        self.assertLess(time.perf_counter() - start, 5)

    def test_a_noscript_inside_noscript_markup_keeps_all_its_content(self):
        page = "<html><body><noscript><noscript>a<b>PAYLOAD</b></noscript></noscript><p>Body</p></body></html>"
        visible_text, hidden_fragments = extract_visible_text(page)
        self.assertEqual(visible_text, "Body")
        hidden_text = ""
        for fragment in hidden_fragments:
            hidden_text += fragment.text + " "
        self.assertIn("PAYLOAD", hidden_text)

    def test_an_svg_noscript_keeps_all_its_content(self):
        hidden_text = ""
        for fragment in extract_visible_text(SVG_NOSCRIPT_PAGE)[1]:
            hidden_text += fragment.text + " "
        self.assertIn("PAYLOAD", hidden_text)

    def test_a_page_nested_200_deep_is_read(self):
        self.assertEqual(extract_visible_text(nested_page(200))[0], "deep after")

    def test_comments_keep_their_text_as_written(self):
        # Chrome's comment.data; trafilatura read the text after an emptied <!-- --> differently.
        from lxml import etree

        root = parse_html("<html><body><p>2<!-- -->-MIN READ<!--a--b  --></p></body></html>")
        comment_texts = []
        for comment in root.iter(etree.Comment):
            comment_texts.append(comment.text)
        self.assertEqual(comment_texts, [" ", "a--b  "])

    def test_every_doctype_is_read_without_error(self):
        from tests.test_browser_check import doctype_cases

        for start in doctype_cases():
            with self.subTest(start=start):
                extract_visible_text(start + "<html><body><p>x</p></body></html>")


class TooComplexToReadTests(unittest.TestCase):
    """A page is not read statically when it has more "<" than MAXIMUM_TAG_OPENINGS (it would
    take minutes), or when it may nest deeper than Chrome's limit, past which Chrome moves
    elements in a way this reader does not reproduce. It gets a medium flag, and an article
    reading asks for the browser check."""

    def test_a_page_that_may_nest_past_chromes_limit_is_flagged(self):
        for page in (nested_page(600), table_chain_page(128), table_chain_page(105)):
            with self.subTest(page=page[:80]):
                self.assertEqual(flag_kinds(page), ["page_too_complex_to_read"])

    def test_a_page_nested_a_hundred_thousand_deep_is_flagged_quickly(self):
        from headline_guard import HeadlineGuard, PAPER_WATCHLIST

        guard = HeadlineGuard(PAPER_WATCHLIST)
        start = time.perf_counter()
        result = guard.analyze_html(nested_page(100_000))
        article = guard.extract_article(nested_page(100_000))
        self.assertLess(time.perf_counter() - start, 3)
        kinds = []
        for flag in result.flags:
            kinds.append(flag.kind)
        self.assertIn("page_too_complex_to_read", kinds)
        self.assertEqual(result.verdict, "review")
        self.assertEqual(article.verdict, "review")
        self.assertTrue(article.needs_browser_check)

    def test_noscript_markup_nested_past_the_limit_is_flagged_quickly(self):
        # The reader walks that markup too. Each <noscript>'s markup is parsed once, not again
        # inside the one around it (that took 2.3 s at 700 levels, and 38 s at 1,000).
        for page in ("<html><body><noscript>" + "<div>" * 600 + "PAYLOAD</noscript></body></html>",
                     "<html><body>" + ("<noscript>" + "a" * 2000) * 700 + "</body></html>"):
            with self.subTest(page=page[:40]):
                start = time.perf_counter()
                self.assertEqual(flag_kinds(page), ["page_too_complex_to_read"])
                self.assertLess(time.perf_counter() - start, 1)

    def test_markup_without_html_or_body_counts_their_depth(self):
        # Chrome parses any page as a document, so this <span> is 514 deep (html, body, 511
        # divs), its parent past the limit; a page starting with a long comment is the same.
        markup = "<div>" * 511 + "<span>x</span>"
        for page in (markup, "<!--" + "c" * 300 + "-->" + markup):
            with self.subTest(page=page[:40]):
                self.assertEqual(flag_kinds(page), ["page_too_complex_to_read"])

    def test_a_page_one_past_the_limit_is_flagged(self):
        page = "<html><body><p>x</p>" + "<b></b>" * ((MAXIMUM_TAG_OPENINGS - 6) // 2) + "<i>y</body></html>"
        self.assertEqual(page.count("<"), MAXIMUM_TAG_OPENINGS + 1)
        self.assertEqual(flag_kinds(page), ["page_too_complex_to_read"])

    def test_a_page_at_the_limit_is_read(self):
        page = "<html><body><p>x</p>" + "<b></b>" * ((MAXIMUM_TAG_OPENINGS - 6) // 2) + "</body></html>"
        self.assertEqual(page.count("<"), MAXIMUM_TAG_OPENINGS)
        self.assertEqual(extract_visible_text(page)[0], "x")


if __name__ == "__main__":
    unittest.main()
