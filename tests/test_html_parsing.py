"""The page is split into tags, comments and text as Chrome's HTML parser splits it. libxml2 (under
lxml) reads several constructs differently: a doctype with an unclosed quote, a comment closed by
--!> or written <!-->, <!--> inside a <textarea>, an escaped script. Each difference changes which
text the reader thinks is visible, and some hide a hiding wrapper from it, so that text Chrome
never shows reaches the model as visible text. The expected texts are Chrome 157's innerText
(whitespace collapsed); tests/test_browser_check.ParserChromeTests checks them against Chrome."""

import unittest

from headline_guard.html_visibility import extract_visible_text

HEADLINE = "Alphabet shares surge after dodging antitrust breakup bullet"
ARTICLE = (f"<html><head><title>{HEADLINE}</title></head><body><article><h1>{HEADLINE}</h1>"
           '<div style="display:none">losses and layoffs</div><p class="a">Body text.</p></article>'
           "</body></html>")
HIDDEN_AFTER_COMMENT = '<div style="display:none"><!-- -->payload</div><p>Body text.</p></body></html>'

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
)


class ParsedLikeChromeTests(unittest.TestCase):
    def test_visible_text_is_what_chrome_shows(self):
        for page, chrome_text in CHROME_PARSED_PAGES:
            with self.subTest(page=page):
                self.assertEqual(extract_visible_text(page)[0], chrome_text)

    def test_every_doctype_is_read_without_error(self):
        from tests.test_browser_check import doctype_cases

        for start in doctype_cases():
            with self.subTest(start=start):
                extract_visible_text(start + "<html><body><p>x</p></body></html>")


if __name__ == "__main__":
    unittest.main()
