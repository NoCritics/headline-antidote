"""The gaps left after the CSS engine: scoped CSS variables, more hiding properties,
overlays and stacking order, reordered text, embedded fonts, and text hidden by JavaScript
(caught by comparing the heading with the feed and metadata titles)."""

import importlib.util
import unittest

from headline_guard import HeadlineGuard, PAPER_WATCHLIST

GUARD = HeadlineGuard(PAPER_WATCHLIST)
HEADLINE = "Alphabet shares surge after dodging antitrust breakup bullet"
PAYLOAD = " losses and layoffs"
CASCADE_AVAILABLE = (
    importlib.util.find_spec("tinycss2") is not None and importlib.util.find_spec("cssselect2") is not None
)
TRAFILATURA_AVAILABLE = importlib.util.find_spec("trafilatura") is not None
ARTICLE_BODY = (
    "<p>Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order "
    "a breakup of the company, a ruling analysts said removes a major overhang.</p>"
    "<p>The decision lifted other large technology stocks as investors bet that regulators "
    "would struggle to force structural remedies on the sector.</p>"
)


def headline_page(headline_inner_html, css="", h1_attributes=""):
    return (
        f"<html><head><style>{css}</style></head><body><article>"
        f"<h1 {h1_attributes}>{headline_inner_html}</h1></article></body></html>"
    )


def span_page(span_attributes, css="", span_inner=PAYLOAD, h1_attributes=""):
    return headline_page(f"{HEADLINE}<span {span_attributes}>{span_inner}</span>", css, h1_attributes)


def article_page(headline_inner_html, title=HEADLINE, head_extra="", body_extra=""):
    return (
        f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{title}</title>{head_extra}</head>"
        f"<body><article><h1>{headline_inner_html}</h1>{ARTICLE_BODY}</article>{body_extra}</body></html>"
    )


class HiddenTestCase(unittest.TestCase):
    def assert_hidden(self, html):
        result = GUARD.analyze_html(html, "//h1")
        self.assertEqual(result.clean_text, HEADLINE)
        self.assertEqual(result.verdict, "quarantine", result.flags)

    def assert_visible(self, html, expected=HEADLINE + PAYLOAD):
        result = GUARD.analyze_html(html, "//h1")
        self.assertEqual(result.clean_text, expected)
        self.assertEqual(result.verdict, "pass", result.flags)


class MoreHidingPropertiesTests(HiddenTestCase):
    def test_text_fill_color_overrides_a_visible_color(self):
        self.assert_hidden(span_page('style="color:#000;-webkit-text-fill-color:transparent"'))

    def test_filter_opacity(self):
        self.assert_hidden(span_page('style="filter: opacity(0)"'))

    def test_filter_blur(self):
        self.assert_hidden(span_page('style="filter: blur(12px)"'))

    def test_content_visibility_hidden(self):
        self.assert_hidden(span_page('style="content-visibility:hidden"'))

    def test_font_shorthand_with_zero_size(self):
        self.assert_hidden(span_page('style="font: 0/0 a"'))

    def test_font_size_as_calc_expression(self):
        self.assert_hidden(span_page('style="font-size: calc(10px - 10px)"'))

    def test_font_size_as_clamp_expression(self):
        self.assert_hidden(span_page('style="font-size: clamp(0px, 0vw, 0px)"'))

    def test_line_height_zero_with_clipped_overflow(self):
        self.assert_hidden(span_page('style="display:inline-block;line-height:0;overflow:hidden"'))

    def test_letters_drawn_on_top_of_each_other(self):
        self.assert_hidden(span_page('style="letter-spacing:-1em"'))

    def test_modern_rgb_syntax_with_zero_alpha(self):
        self.assert_hidden(span_page('style="color: rgb(0 0 0 / 0)"'))

    def test_hsl_white_on_white(self):
        self.assert_hidden(span_page('style="color: hsl(0 0% 99%)"', h1_attributes='style="background:#fff"'))

    def test_less_common_named_white(self):
        self.assert_hidden(span_page('style="color: mintcream"', h1_attributes='style="background:white"'))

    def test_moved_off_screen_by_transform(self):
        self.assert_hidden(span_page('style="display:inline-block;transform:translateX(-9999px)"'))

    def test_old_font_color_attribute(self):
        self.assert_hidden(headline_page(f'{HEADLINE}<font color="#ffffff">{PAYLOAD}</font>',
                                         h1_attributes='style="background:#fff"'))

    def test_closed_details(self):
        self.assert_hidden(headline_page(f"{HEADLINE}<details><summary></summary>{PAYLOAD}</details>"))

    def test_svg_tooltip_text(self):
        self.assert_hidden(headline_page(f"{HEADLINE}<svg><title>{PAYLOAD}</title></svg>"))

    def test_gradient_text_is_visible(self):
        self.assert_visible(span_page(
            'style="color:transparent;background:linear-gradient(90deg,#f00,#00f);'
            '-webkit-background-clip:text;background-clip:text"'
        ))

    def test_transparent_text_with_a_shadow_is_visible(self):
        self.assert_visible(span_page('style="color:transparent;text-shadow:0 0 0 #000"'))

    def test_open_details_is_visible(self):
        result = GUARD.analyze_html(headline_page(f"{HEADLINE}<details open><summary></summary>{PAYLOAD}</details>"),
                                    "//h1")
        self.assertEqual(result.verdict, "pass", result.flags)
        self.assertIn("layoffs", result.clean_text)

    def test_small_negative_letter_spacing_is_visible(self):
        self.assert_visible(span_page('style="letter-spacing:-0.02em"'))


class OverlayTests(HiddenTestCase):
    def test_opaque_child_overlay_covers_its_parent(self):
        self.assert_hidden(span_page(
            'style="position:relative"',
            span_inner=PAYLOAD + '<span style="position:absolute;inset:0;background:#fff"></span>',
        ))

    def test_overlay_with_top_left_and_full_size(self):
        self.assert_hidden(span_page(
            'style="position:relative"',
            span_inner=PAYLOAD + '<i style="position:absolute;top:0;left:0;width:100%;height:100%;'
                                 'background-color:rgb(255,255,255)"></i>',
        ))

    def test_drawn_behind_an_enclosing_background(self):
        self.assert_hidden(span_page('style="position:relative;z-index:-1"', h1_attributes='style="background:#fff"'))

    def test_negative_z_index_inside_its_own_stacking_context_is_visible(self):
        self.assert_visible(span_page(
            'style="position:relative;z-index:-1"',
            h1_attributes='style="position:relative;z-index:0;background:#fff"',
        ))

    def test_translucent_overlay_does_not_cover(self):
        self.assert_visible(span_page(
            'style="position:relative"',
            span_inner=PAYLOAD + '<span style="position:absolute;inset:0;background:rgba(0,0,0,0.3)"></span>',
            ), HEADLINE + PAYLOAD)

    def test_page_level_overlay_is_not_counted(self):
        # A paywall or cookie banner sized by the whole page, not a box around a few words.
        html = (f"<html><body><article><h1>{HEADLINE}{PAYLOAD}</h1>"
                '<div style="position:absolute;inset:0;background:#fff"></div></article></body></html>')
        result = GUARD.analyze_html(html, "//h1")
        self.assertEqual(result.clean_text, HEADLINE + PAYLOAD)


@unittest.skipUnless(CASCADE_AVAILABLE, "tinycss2 and cssselect2 not installed")
class CascadeOnlyTests(HiddenTestCase):
    def test_scoped_css_variable(self):
        self.assert_hidden(span_page('class="x"', css="article { --gone: none } .x { display: var(--gone) }"))

    def test_scoped_css_variable_overridden_closer_to_the_text(self):
        self.assert_visible(span_page(
            'class="x"', css="article { --gone: none } h1 { --gone: inline } .x { display: var(--gone) }"
        ))

    def test_pseudo_element_overlay(self):
        self.assert_hidden(span_page(
            'class="x"',
            css='.x { position: relative } .x::after { content: ""; position: absolute; inset: 0; background: #fff }',
        ))

    def test_overlay_from_a_stylesheet_rule(self):
        self.assert_hidden(span_page(
            'class="x"', css=".x { position: relative } .cover { position: absolute; inset: 0; background: #fff }",
            span_inner=PAYLOAD + '<span class="cover"></span>',
        ))

    def test_stretched_transparent_link_overlay_is_visible(self):
        # The common "stretched link" pattern: a transparent ::after over a card.
        self.assert_visible(span_page(
            'class="x"',
            css='.x { position: relative } .x::after { content: ""; position: absolute; inset: 0; z-index: 1 }',
        ))

    def test_text_fill_color_from_a_stylesheet(self):
        self.assert_hidden(span_page('class="x"', css="h1 .x { -webkit-text-fill-color: transparent }"))


class ReorderedTextTests(unittest.TestCase):
    def test_bdo_right_to_left(self):
        result = GUARD.analyze_html(headline_page(f'{HEADLINE} <bdo dir="rtl">sessol</bdo>'), "//h1")
        kinds = [flag.kind for flag in result.flags]
        self.assertIn("reordered_text", kinds)
        self.assertEqual(result.verdict, "quarantine")

    def test_unicode_bidi_override(self):
        result = GUARD.analyze_html(span_page('style="unicode-bidi:bidi-override;direction:rtl"'), "//h1")
        self.assertIn("reordered_text", [flag.kind for flag in result.flags])

    def test_hebrew_in_a_right_to_left_override_is_not_reordered(self):
        html = headline_page('<span style="unicode-bidi:bidi-override;direction:rtl">שלום עולם</span>')
        result = GUARD.analyze_html(html, "//h1")
        self.assertNotIn("reordered_text", [flag.kind for flag in result.flags])


@unittest.skipUnless(TRAFILATURA_AVAILABLE, "trafilatura not installed")
class HeadlineAgainstTitlesTests(unittest.TestCase):
    def test_javascript_hidden_words_are_caught_by_the_title(self):
        html = article_page(
            f'{HEADLINE}<span id="p">{PAYLOAD}</span>',
            body_extra="<script>document.getElementById('p').style.display='none';</script>",
        )
        article = GUARD.extract_article(html)
        self.assertEqual(article.verdict, "review")
        self.assertEqual(article.headline, HEADLINE)
        self.assertIn("headline_adds_words", [flag.kind for flag in article.flags])
        self.assertTrue(article.needs_browser_check)

    def test_one_hidden_negation_changes_the_meaning(self):
        html = article_page("Alphabet shares will <span>not</span> surge after the ruling",
                            title="Alphabet shares will surge after the ruling")
        article = GUARD.extract_article(html)
        self.assertEqual(article.verdict, "review")
        self.assertEqual(article.headline, "Alphabet shares will surge after the ruling")

    def test_one_ordinary_added_word_is_low_but_checked_in_a_browser(self):
        html = article_page("Berkshire profit fell sharply as buybacks paused",
                            title="Berkshire profit fell as buybacks paused")
        article = GUARD.extract_article(html)
        self.assertEqual(article.verdict, "pass", article.flags)
        self.assertEqual(article.headline, "Berkshire profit fell sharply as buybacks paused")
        self.assertTrue(article.needs_browser_check)

    def test_differently_worded_title_is_not_compared(self):
        html = article_page("AI stocks climb after trillions wiped from market values",
                            title="AI stocks bounce back after trillions wiped from market values")
        article = GUARD.extract_article(html)
        self.assertNotIn("headline_adds_words", [flag.kind for flag in article.flags])

    def test_feed_title_with_the_same_words_clears_it(self):
        html = article_page("Alphabet shares surge after dodging antitrust breakup bullet today in New York")
        article = GUARD.extract_article(
            html, feed_title="Alphabet shares surge after dodging antitrust breakup bullet today in New York"
        )
        self.assertEqual(article.verdict, "pass", article.flags)

    def test_site_name_suffix_is_ignored(self):
        html = article_page(HEADLINE, title=HEADLINE + " | Example News")
        article = GUARD.extract_article(html)
        self.assertEqual(article.verdict, "pass", article.flags)

    def test_inline_script_naming_a_headline_element_asks_for_a_browser(self):
        html = article_page(
            f'{HEADLINE}<span class="kicker-note"></span>',
            body_extra="<script>document.querySelector('.kicker-note').style.opacity = 0;</script>",
        )
        article = GUARD.extract_article(html)
        self.assertTrue(article.needs_browser_check)
        self.assertEqual(article.verdict, "pass")

    def test_body_text_missing_from_the_json_ld_copy_asks_for_a_browser(self):
        json_ld = (
            '<script type="application/ld+json">{"@type": "NewsArticle", "headline": "' + HEADLINE + '", '
            '"articleBody": "Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order '
            'a breakup of the company, a ruling analysts said removes a major overhang. The decision lifted other '
            'large technology stocks as investors bet that regulators would struggle to force structural remedies '
            'on the sector."}</script>'
        )
        injected = ("<p>Insiders say the company is quietly preparing for mass layoffs and a profit warning "
                    "that will shock investors next week.</p>")
        html = (
            f"<!doctype html><html><head><title>{HEADLINE}</title>{json_ld}</head><body><article>"
            f"<h1>{HEADLINE}</h1>{ARTICLE_BODY}{injected}</article></body></html>"
        )
        article = GUARD.extract_article(html)
        self.assertIn("body_text_not_in_page_copy", [flag.kind for flag in article.flags])
        self.assertTrue(article.needs_browser_check)
        self.assertEqual(article.verdict, "pass")


INJECTED_PARAGRAPH_TEXT = ("Regulators have opened a fraud probe into the company's accounting and may "
                           "suspend trading in its shares, people familiar with the matter said.")


def body_page(injected_html, body_extra="", head_extra=""):
    return (
        f"<!doctype html><html><head><title>{HEADLINE}</title>{head_extra}</head><body><article>"
        f"<h1>{HEADLINE}</h1>{ARTICLE_BODY}{injected_html}</article>{body_extra}</body></html>"
    )


@unittest.skipUnless(TRAFILATURA_AVAILABLE, "trafilatura not installed")
class BodyBrowserTriageTests(unittest.TestCase):
    """Found by splicing attacks into real pages (real_world_test/evaluate_injections.py)."""

    def test_script_removing_a_body_paragraph_by_id_asks_for_a_browser(self):
        html = body_page(f'<p id="update-7">{INJECTED_PARAGRAPH_TEXT}</p>',
                         body_extra="<script>document.getElementById('update-7').remove();</script>")
        article = GUARD.extract_article(html)
        self.assertTrue(article.needs_browser_check)
        self.assertEqual(article.verdict, "pass")

    def test_script_hiding_a_body_paragraph_by_selector_asks_for_a_browser(self):
        html = body_page(f'<p class="update-note">{INJECTED_PARAGRAPH_TEXT}</p>',
                         body_extra="<script>$('.update-note').hide();</script>")
        self.assertTrue(GUARD.extract_article(html).needs_browser_check)

    def test_script_changing_a_short_element_is_not_checked(self):
        html = body_page('<button id="share-button">Share this</button>',
                         body_extra="<script>document.getElementById('share-button').classList.add('ready');</script>")
        self.assertFalse(GUARD.extract_article(html).needs_browser_check)

    def test_script_changing_a_common_class_is_not_checked(self):
        paragraphs = ""
        for _ in range(3):
            paragraphs += f'<p class="para">{INJECTED_PARAGRAPH_TEXT}</p>'
        html = body_page(paragraphs, body_extra="<script>$('.para').css('margin', '0');</script>")
        self.assertFalse(GUARD.extract_article(html).needs_browser_check)

    def test_hidden_paragraph_in_a_page_wrapped_in_a_form_is_flagged(self):
        # ASP.NET sites (Globes) put the whole page in one <form>; that is not interface text.
        hidden = f'<p style="position:absolute;left:-10000px">{INJECTED_PARAGRAPH_TEXT}</p>'
        html = (f"<!doctype html><html><head><title>{HEADLINE}</title></head><body><form id=\"aspnetForm\">"
                f"<article><h1>{HEADLINE}</h1>{ARTICLE_BODY}{hidden}</article>"
                '<div><label style="position:absolute;left:-10000px">Search the site for news</label>'
                '<input name="q"></div></form></body></html>')
        article = GUARD.extract_article(html)
        self.assertNotIn("fraud probe", article.body)
        hidden_flags = []
        for flag in article.flags:
            if flag.kind == "hidden_text_in_article":
                hidden_flags.append(flag.original)
        self.assertEqual(len(hidden_flags), 1, article.flags)  # the search label is still not flagged
        self.assertIn("fraud probe", hidden_flags[0])

    @unittest.skipUnless(CASCADE_AVAILABLE, "the CSS libraries are not installed")
    def test_white_text_on_an_undeclared_background_is_kept_and_sent_to_a_browser(self):
        article = GUARD.extract_article(body_page(f'<p style="color:#fff">{INJECTED_PARAGRAPH_TEXT}</p>'))
        self.assertIn("fraud probe", article.body)
        self.assertIn("possibly_hidden_text", [flag.kind for flag in article.flags])
        self.assertTrue(article.needs_browser_check)
        self.assertEqual(article.verdict, "pass")

    @unittest.skipUnless(CASCADE_AVAILABLE, "the CSS libraries are not installed")
    def test_white_text_on_a_declared_white_background_is_removed(self):
        article = GUARD.extract_article(body_page(f'<p style="color:#fff">{INJECTED_PARAGRAPH_TEXT}</p>',
                                                  head_extra="<style>body { background: #fff }</style>"))
        self.assertNotIn("fraud probe", article.body)
        self.assertIn("hidden_text_in_article", [flag.kind for flag in article.flags])
        self.assertEqual(article.verdict, "pass")

    @unittest.skipUnless(CASCADE_AVAILABLE, "the CSS libraries are not installed")
    def test_white_text_on_a_dark_box_is_visible(self):
        html = body_page(f'<div style="background:#123"><p style="color:#fff">{INJECTED_PARAGRAPH_TEXT}</p></div>')
        article = GUARD.extract_article(html)
        self.assertIn("fraud probe", article.body)
        self.assertFalse(article.needs_browser_check)
        self.assertEqual(article.verdict, "pass")


class FreshPageSetTests(unittest.TestCase):
    """False alarms and bugs found on the 228-page set of 2026-11-09."""

    def test_lowercase_accented_word_is_not_a_company(self):
        # Italian "metà" means "half"; it was flagged and rewritten to "Meta".
        result = GUARD.analyze("I ricavi sono scesi della metà nel trimestre")
        self.assertIn("metà", result.clean_text)
        self.assertEqual(result.flags, [])

    def test_capitalised_accented_company_name_is_still_caught(self):
        result = GUARD.analyze("Tésla recalls cars")
        self.assertIn("accented_watchlist_name", [flag.kind for flag in result.flags])

    @unittest.skipUnless(TRAFILATURA_AVAILABLE, "trafilatura not installed")
    def test_kicker_in_its_own_element_is_low(self):
        html = article_page(f'<span class="topline">Handel mit Wertpapieren</span> <span>{HEADLINE}</span>')
        article = GUARD.extract_article(html)
        self.assertEqual(article.verdict, "pass", article.flags)
        self.assertEqual(article.headline, HEADLINE)
        self.assertTrue(article.needs_browser_check)

    @unittest.skipUnless(TRAFILATURA_AVAILABLE, "trafilatura not installed")
    def test_words_added_inside_the_headline_text_are_still_medium(self):
        html = article_page(f'{HEADLINE}<span> amid fraud probe</span>')
        self.assertEqual(GUARD.extract_article(html).verdict, "review")

    @unittest.skipUnless(TRAFILATURA_AVAILABLE, "trafilatura not installed")
    def test_kicker_with_a_negation_is_still_medium(self):
        html = article_page(f'<span>Not true:</span> <span>{HEADLINE}</span>')
        self.assertEqual(GUARD.extract_article(html).verdict, "review")

    @unittest.skipUnless(TRAFILATURA_AVAILABLE, "trafilatura not installed")
    def test_standfirst_from_the_description_is_not_sent_to_a_browser(self):
        standfirst = ("A federal judge declined to order a breakup, removing the biggest legal threat "
                      "to the search business in two decades")
        json_ld = (
            '<script type="application/ld+json">{"@type": "NewsArticle", "headline": "' + HEADLINE + '", '
            '"articleBody": "Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order '
            'a breakup of the company, a ruling analysts said removes a major overhang. The decision lifted other '
            'large technology stocks as investors bet that regulators would struggle to force structural remedies '
            'on the sector."}</script>'
        )
        html = (
            f"<!doctype html><html><head><title>{HEADLINE}</title>{json_ld}"
            f'<meta property="og:description" content="{standfirst}."></head><body><article>'
            f"<h1>{HEADLINE}</h1><p>{standfirst}.</p>{ARTICLE_BODY}</article></body></html>"
        )
        article = GUARD.extract_article(html)
        self.assertFalse(article.needs_browser_check, article.browser_check_reasons)

    @unittest.skipUnless(TRAFILATURA_AVAILABLE and CASCADE_AVAILABLE, "trafilatura or the CSS libraries not installed")
    def test_short_hidden_label_is_removed_with_a_low_flag(self):
        article = GUARD.extract_article(body_page('<p style="display:none">Advertisement</p>'))
        self.assertNotIn("Advertisement", article.body)
        self.assertEqual(article.verdict, "pass", article.flags)

    @unittest.skipUnless(TRAFILATURA_AVAILABLE and CASCADE_AVAILABLE, "trafilatura or the CSS libraries not installed")
    def test_article_collapsed_behind_read_more_is_set_aside(self):
        # The hidden rest of the story stays out of the body (readers can't see it without a click,
        # and an attacker's hidden ending looks the same); the pipeline can choose to use it.
        rest = ""
        for number in range(6):
            rest += (f"<p>Paragraph {number} of the rest of the story explains how the ruling affects "
                     "advertising revenue, cloud contracts and the company's hiring plans for next year.</p>")
        html = body_page(f'<div class="readmore"><div id="ControlPara1">{rest}</div></div>',
                         head_extra='<style>.readmore div[id^="ControlPara"] > * { display: none }</style>')
        article = GUARD.extract_article(html)
        self.assertNotIn("Paragraph 5 of the rest", article.body)
        self.assertIn("Shares of Alphabet rose sharply", article.body)
        self.assertIn("Paragraph 0 of the rest", article.hidden_ending)
        self.assertIn("Paragraph 5 of the rest", article.hidden_ending)
        kinds = [flag.kind for flag in article.flags]
        self.assertIn("most_of_article_hidden", kinds)
        self.assertNotIn("hidden_text_in_article", kinds)
        self.assertEqual(article.verdict, "review")

    @unittest.skipUnless(TRAFILATURA_AVAILABLE and CASCADE_AVAILABLE, "trafilatura or the CSS libraries not installed")
    def test_long_hidden_ending_does_not_reach_the_model_as_body_text(self):
        # Review finding 2: hidden text that is most of the article and runs to its end was put
        # back into the body with only a medium flag, so a caller holding back only
        # "quarantine" (the README's example) gave it to the model.
        payload = ""
        for number in range(4):
            payload += f"<p>{INJECTED_PARAGRAPH_TEXT} Update {number}: sell before the open.</p>"
        article = GUARD.extract_article(body_page(f'<div style="display:none">{payload}</div>'))
        reaches_model = "fraud probe" in article.body and article.verdict != "quarantine"
        self.assertFalse(reaches_model, (article.verdict, article.flags))
        self.assertIn("fraud probe", article.hidden_ending)
        self.assertIn("most_of_article_hidden", [flag.kind for flag in article.flags])

    @unittest.skipUnless(TRAFILATURA_AVAILABLE and CASCADE_AVAILABLE, "trafilatura or the CSS libraries not installed")
    def test_hidden_paragraph_in_the_middle_is_still_removed(self):
        html = body_page(f'<p style="display:none">{INJECTED_PARAGRAPH_TEXT}</p>'
                         "<p>Analysts expect the company to update its guidance when it reports results "
                         "later this month, and several raised their price targets.</p>")
        article = GUARD.extract_article(html)
        self.assertNotIn("fraud probe", article.body)
        self.assertNotIn("most_of_article_hidden", [flag.kind for flag in article.flags])


@unittest.skipUnless(TRAFILATURA_AVAILABLE and CASCADE_AVAILABLE, "trafilatura or the CSS libraries not installed")
class HeadlineDrawingTests(unittest.TestCase):
    def test_css_generated_words_in_the_headline(self):
        html = article_page(f'<span class="k"></span>{HEADLINE}',
                            head_extra='<style>.k::before { content: "Exclusive: losses ahead " }</style>')
        article = GUARD.extract_article(html)
        self.assertIn("css_generated_text", [flag.kind for flag in article.flags])
        self.assertEqual(article.verdict, "review")

    def test_icon_glyph_from_css_is_not_text(self):
        html = article_page(f'<span class="k"></span>{HEADLINE}',
                            head_extra='<style>.k::before { content: "\\2022" }</style>')
        article = GUARD.extract_article(html)
        self.assertNotIn("css_generated_text", [flag.kind for flag in article.flags])

    def test_headline_drawn_with_an_embedded_font(self):
        css = ('@font-face { font-family: "Remap"; src: url(data:font/woff2;base64,AAAA) format("woff2") } '
               'h1 { font-family: "Remap", serif }')
        article = GUARD.extract_article(article_page(HEADLINE, head_extra=f"<style>{css}</style>"))
        self.assertIn("embedded_font", [flag.kind for flag in article.flags])
        self.assertEqual(article.verdict, "review")

    def test_body_icon_font_is_not_flagged(self):
        css = ('@font-face { font-family: "Icons"; src: url(data:font/woff2;base64,AAAA) } '
               '.icon { font-family: "Icons" }')
        article = GUARD.extract_article(article_page(HEADLINE, head_extra=f"<style>{css}</style>"))
        self.assertNotIn("embedded_font", [flag.kind for flag in article.flags])


if __name__ == "__main__":
    unittest.main()
