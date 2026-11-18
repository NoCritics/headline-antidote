"""Text inside <svg> is drawn only inside <text> (through <tspan>, <textPath> and <a>) or inside
<foreignObject>. Text anywhere else in an SVG reaches a scraper that reads the markup but is never
shown, so it must not reach the model as visible text. The expected texts are Chrome 157's
innerText (whitespace collapsed); tests/test_browser_check.ParserChromeTests checks them against
Chrome. Where innerText counts text that is not painted (definitions such as <defs>, checked with
screenshots), the cases are in NotDrawnTests instead."""

import unittest

from headline_guard.html_visibility import extract_visible_text

XHTML = "http://www.w3.org/1999/xhtml"
MATHML = "http://www.w3.org/1998/Math/MathML"


def page(svg_markup):
    return f"<html><body>{svg_markup}<p>x</p></body></html>"


# (page, the text Chrome shows)
SVG_CHROME_PAGES = (
    (page("<svg>PAYLOAD<g>PAYLOAD</g><text>drawn<tspan>span</tspan></text>"
          "<foreignObject><p>fo</p></foreignObject></svg>"), "drawnspan fo x"),
    (page("<svg><![CDATA[PAYLOAD]]></svg>"), "x"),
    # Inside <text>: <tspan>, <a> (not inside another <a>), and <textPath> directly under <text>
    # or its <a>. Nothing else draws, and the text after such a child still does.
    (page("<svg><text>A<g>PAYLOAD</g>B<a>C</a>D</text></svg>"), "ABCD x"),
    (page("<svg><text>A<foreignObject>PAYLOAD</foreignObject><text>PAYLOAD</text>"
          "<unknown>PAYLOAD</unknown><switch><tspan>PAYLOAD</tspan></switch>B</text></svg>"), "AB x"),
    (page("<svg><text><tspan><textPath>PAYLOAD</textPath></tspan>"
          "<textPath>T<tspan>S</tspan><textPath>PAYLOAD</textPath></textPath></text></svg>"), "TS x"),
    (page("<svg><text><a><textPath>T</textPath></a><tspan><a>A<a>PAYLOAD</a></a></tspan></text></svg>"),
     "TA x"),
    (page("<svg><text>A<title>PAYLOAD</title><desc>PAYLOAD</desc>B</text></svg>"), "AB x"),
    # Outside <text>: <svg>, <g>, <a> (not inside another <a>) and <switch> hold drawn children;
    # their own text, and every other element, draws nothing.
    (page("<svg><a><text>A</text>PAYLOAD</a><a><g><text>B</text></g></a>"
          "<a><a><text>PAYLOAD</text></a></a></svg>"), "A B x"),
    (page("<svg><textPath>PAYLOAD</textPath><tspan>PAYLOAD</tspan><rect><text>PAYLOAD</text></rect>"
          "<unknown><text>PAYLOAD</text></unknown><svg><text>N</text></svg></svg>"), "N x"),
    (page(f"<svg><foreignObject>F<svg>PAYLOAD<text>T</text></svg></foreignObject></svg>"), "F T x"),
    (page("<svg><g><text>G1</text><text>G2</text></g></svg>"), "G1 G2 x"),
    # A <switch> draws its first element child whose conditions hold, and nothing else.
    (page("<svg><switch>PAYLOAD<!--c--><g><text>G</text></g><text>PAYLOAD</text></switch></svg>"), "G x"),
    (page("<svg><switch><desc>d</desc><text>PAYLOAD</text></switch></svg>"), "x"),
    (page('<svg><switch><text requiredExtensions="x">PAYLOAD</text><text>S</text></switch></svg>'), "S x"),
    (page(f'<svg><switch><foreignObject requiredExtensions="{XHTML}"><p>FO</p></foreignObject>'
          "<text>PAYLOAD</text></switch></svg>"), "FO x"),
    # requiredExtensions holds only when it lists XHTML or MathML and nothing else.
    (page(f'<svg><text requiredExtensions="x">PAYLOAD</text><text requiredExtensions="">PAYLOAD</text>'
          f'<text requiredExtensions="{XHTML} http://x">PAYLOAD</text>'
          f'<text requiredExtensions="{MATHML}">M</text></svg>'), "M x"),
    # The names are separated by ASCII whitespace only.
    (page(f'<svg><text requiredExtensions=" {XHTML}\t{XHTML} ">T</text>'
          f'<text requiredExtensions="{XHTML} {XHTML}">PAYLOAD</text>'
          f'<text requiredExtensions="{XHTML} {XHTML}">PAYLOAD</text></svg>'), "T x"),
    (page('<svg><text>A<tspan systemLanguage="xx">PAYLOAD</tspan></text>'
          '<g systemLanguage="xx"><text>PAYLOAD</text></g></svg>'), "A x"),
)


def hidden_text(fragments):
    texts = []
    for fragment in fragments:
        texts.append(fragment.text)
    return " ".join(texts)


class SvgTextTests(unittest.TestCase):
    def test_visible_text_is_what_chrome_shows(self):
        for svg_page, chrome_text in SVG_CHROME_PAGES:
            with self.subTest(page=svg_page):
                self.assertEqual(extract_visible_text(svg_page)[0], chrome_text)

    def test_svg_text_that_is_not_drawn_is_reported_hidden(self):
        # A scraper that reads the markup passes this text on, so it is reported.
        for markup in ("<svg>PAYLOAD<text>a</text></svg>", "<svg><g><text>a</text>PAYLOAD</g></svg>",
                       "<svg><rect>PAYLOAD</rect></svg>", "<svg><text><g>PAYLOAD</g></text></svg>"):
            with self.subTest(markup=markup):
                self.assertIn("PAYLOAD", hidden_text(extract_visible_text(page(markup))[1]))

    def test_an_element_read_alone_keeps_its_place_in_the_svg(self):
        drawn = page("<svg><text><tspan>T</tspan></text><g><tspan>PAYLOAD</tspan></g></svg>")
        self.assertEqual(extract_visible_text(drawn, "//text/tspan")[0], "T")
        self.assertEqual(extract_visible_text(drawn, "//g/tspan")[0], "")


class NotDrawnTests(unittest.TestCase):
    """Cases where the reader hides what Chrome's innerText counts."""

    def test_definitions_are_not_drawn(self):
        # Chrome's innerText includes this text, but it is not painted (a screenshot with and
        # without it is identical): definitions are drawn only where something references them,
        # which this reader does not follow, so the text counts as hidden.
        for tag in ("defs", "symbol", "mask", "clipPath", "pattern", "marker"):
            with self.subTest(tag=tag):
                visible_text, fragments = extract_visible_text(page(f"<svg><{tag}><text>PAYLOAD</text></{tag}></svg>"))
                self.assertEqual(visible_text, "x")
                self.assertIn("PAYLOAD", hidden_text(fragments))

    def test_text_that_depends_on_the_browser_language_counts_as_hidden(self):
        # systemLanguage holds when it names the browser's language, which differs between
        # readers; neither the text nor a <switch> choice after it can be decided.
        for markup in ('<svg><text systemLanguage="en">PAYLOAD</text></svg>',
                       '<svg><switch><text systemLanguage="en">PAYLOAD</text><text>PAYLOAD</text></switch></svg>'):
            with self.subTest(markup=markup):
                self.assertEqual(extract_visible_text(page(markup))[0], "x")


if __name__ == "__main__":
    unittest.main()
