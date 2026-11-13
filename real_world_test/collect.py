"""Collects real finance headlines and article pages for the false-alarm and timing test.

Reads public RSS feeds, keeps every item title (for the text-mode test), and saves a
few article pages per feed (for the HTML and browser tests). It honours robots.txt,
identifies itself honestly, and stores pages as data under real_world_test/<data>/.

Run from the project root:
    .venv\\Scripts\\python -X utf8 -m real_world_test.collect [--data DIRECTORY] [--per-feed N] [--feeds fresh]

--data names the directory under real_world_test/ to write into (default: data). When it is
not the baseline directory, pages whose URL is already in real_world_test/data/pages.json are
skipped, so a fresh set never repeats the baseline. --feeds fresh uses FRESH_FEEDS.
"""

import argparse
import json
import os
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests
from lxml import etree

TEST_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
BASELINE_DATA_DIRECTORY = os.path.join(TEST_DIRECTORY, "data")
USER_AGENT = "headline-guard-research/0.1 (false-alarm testing of a text-visibility checker)"
ARTICLES_PER_FEED = 4
REQUEST_TIMEOUT_SECONDS = 20
# A feed whose pages keep failing (robots.txt, 401, 403) is given up after this many failed
# attempts per page wanted.
FAILED_ATTEMPTS_PER_WANTED_PAGE = 2

FEEDS = [
    ("CNBC", "en", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
    ("MarketWatch", "en", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Yahoo Finance", "en", "https://finance.yahoo.com/news/rssindex"),
    ("BBC Business", "en", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("Guardian Business", "en", "https://www.theguardian.com/business/rss"),
    ("NPR Business", "en", "https://feeds.npr.org/1006/rss.xml"),
    ("Investing.com", "en", "https://www.investing.com/rss/news.rss"),
    ("Fortune", "en", "https://fortune.com/feed/"),
    ("Business Insider", "en", "https://feeds.businessinsider.com/custom/all"),
    ("Seeking Alpha", "en", "https://seekingalpha.com/market_currents.xml"),
    ("Al Jazeera", "en", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Nikkei Asia", "en", "https://asia.nikkei.com/rss/feed/nar"),
    ("Economic Times", "en", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Moneycontrol", "en", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("RBC", "ru", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("Kommersant", "ru", "https://www.kommersant.ru/RSS/news.xml"),
    ("Interfax", "ru", "https://www.interfax.ru/rss.asp"),
    ("Ekonomichna Pravda", "uk", "https://www.epravda.com.ua/rss/"),
    ("Globes", "he", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=585"),
    ("Handelsblatt", "de", "https://www.handelsblatt.com/contentexport/feed/finanzen"),
    ("Les Echos", "fr", "https://syndication.lesechos.fr/rss/rss_finance-marches.xml"),
    ("Kathimerini", "el", "https://www.kathimerini.gr/economy/feed/"),
    ("Yahoo Japan Business", "ja", "https://news.yahoo.co.jp/rss/categories/business.xml"),
    ("Caixin Global", "en", "https://www.caixinglobal.com/rss/finance.xml"),
    ("Korea Herald Business", "en", "https://www.koreaherald.com/common/rss_xml.php?ct=103"),
]

# The fresh set: press-release wires first (fake releases are the paper's core threat), then
# many different sites and languages, since false alarms come from site templates. Feeds that
# were dead or blocked in the baseline are left out.
FRESH_FEEDS = [
    ("PR Newswire", "en", "https://www.prnewswire.com/rss/news-releases-list.rss"),
    ("GlobeNewswire", "en", "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies"),
    ("Business Wire", "en", "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtRWA=="),
    ("Federal Reserve", "en", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("CNBC Markets", "en", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("Fox Business", "en", "https://moxie.foxbusiness.com/google-publisher/latest.xml"),
    ("Forbes Business", "en", "https://www.forbes.com/business/feed/"),
    ("The Economist", "en", "https://www.economist.com/finance-and-economics/rss.xml"),
    ("Axios", "en", "https://api.axios.com/feed/"),
    ("TechCrunch", "en", "https://techcrunch.com/feed/"),
    ("Benzinga", "en", "https://www.benzinga.com/feed"),
    ("Motley Fool", "en", "https://www.fool.com/feeds/index.aspx"),
    ("Quartz", "en", "https://qz.com/rss"),
    ("CoinDesk", "en", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "en", "https://cointelegraph.com/rss"),
    ("Decrypt", "en", "https://decrypt.co/feed"),
    ("OilPrice", "en", "https://oilprice.com/rss/main"),
    ("Mining.com", "en", "https://www.mining.com/feed/"),
    ("Sky News Business", "en", "https://feeds.skynews.com/feeds/rss/business.xml"),
    ("The Independent Business", "en", "https://www.independent.co.uk/news/business/rss"),
    ("The Telegraph Business", "en", "https://www.telegraph.co.uk/business/rss.xml"),
    ("CBC Business", "en", "https://www.cbc.ca/webfeed/rss/rss-business"),
    ("Financial Post", "en", "https://financialpost.com/feed"),
    ("ABC Australia Business", "en", "https://www.abc.net.au/news/feed/51892/rss.xml"),
    ("Sydney Morning Herald Business", "en", "https://www.smh.com.au/rss/business.xml"),
    ("Deutsche Welle Business", "en", "https://rss.dw.com/rdf/rss-en-bus"),
    ("France 24 Business", "en", "https://www.france24.com/en/business/rss"),
    ("Euronews Business", "en", "https://www.euronews.com/rss?level=vertical&name=business"),
    ("Times of India Business", "en", "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms"),
    ("Livemint Markets", "en", "https://www.livemint.com/rss/markets"),
    ("Business Standard Markets", "en", "https://www.business-standard.com/rss/markets-106.rss"),
    ("Hindu BusinessLine", "en", "https://www.thehindubusinessline.com/markets/feeder/default.rss"),
    ("South China Morning Post Business", "en", "https://www.scmp.com/rss/92/feed"),
    ("Straits Times Business", "en", "https://www.straitstimes.com/news/business/rss.xml"),
    ("Japan Times", "en", "https://www.japantimes.co.jp/feed/"),
    ("Yonhap Economy", "en", "https://en.yna.co.kr/RSS/economy.xml"),
    ("Gulf News Business", "en", "https://gulfnews.com/rss/business"),
    ("Spiegel Wirtschaft", "de", "https://www.spiegel.de/wirtschaft/index.rss"),
    ("FAZ Wirtschaft", "de", "https://www.faz.net/rss/aktuell/wirtschaft/"),
    ("Tagesschau Wirtschaft", "de", "https://www.tagesschau.de/wirtschaft/index~rss2.xml"),
    ("Le Monde Economie", "fr", "https://www.lemonde.fr/economie/rss_full.xml"),
    ("Le Figaro Economie", "fr", "https://www.lefigaro.fr/rss/figaro_economie.xml"),
    ("El Pais Economia", "es", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada"),
    ("ANSA Economia", "it", "https://www.ansa.it/sito/notizie/economia/economia_rss.xml"),
    ("Il Sole 24 Ore Finanza", "it", "https://www.ilsole24ore.com/rss/finanza.xml"),
    ("Folha Mercado", "pt", "https://feeds.folha.uol.com.br/mercado/rss091.xml"),
    ("InfoMoney", "pt", "https://www.infomoney.com.br/feed/"),
    ("Vedomosti", "ru", "https://www.vedomosti.ru/rss/news"),
    ("Lenta", "ru", "https://lenta.ru/rss/news"),
    ("TASS", "ru", "https://tass.ru/rss/v2.xml"),
    ("Interfax", "ru", "https://www.interfax.ru/rss.asp"),
    ("Globes", "he", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=585"),
    ("Handelsblatt", "de", "https://www.handelsblatt.com/contentexport/feed/finanzen"),
    ("Yahoo Japan Business", "ja", "https://news.yahoo.co.jp/rss/categories/business.xml"),
    ("Xinhua Business", "en", "http://www.xinhuanet.com/english/rss/businessrss.xml"),
    ("Guardian Business", "en", "https://www.theguardian.com/business/rss"),
    ("BBC Business", "en", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("NPR Business", "en", "https://feeds.npr.org/1006/rss.xml"),
    ("Fortune", "en", "https://fortune.com/feed/"),
    ("Business Insider", "en", "https://feeds.businessinsider.com/custom/all"),
    ("Al Jazeera", "en", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Nikkei Asia", "en", "https://asia.nikkei.com/rss/feed/nar"),
    ("Economic Times", "en", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Seeking Alpha", "en", "https://seekingalpha.com/market_currents.xml"),
    ("CNBC", "en", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
]

_robot_parsers = {}


def allowed_by_robots(url):
    parsed = urlparse(url)
    site = f"{parsed.scheme}://{parsed.netloc}"
    parser = _robot_parsers.get(site)
    if parser is None:
        parser = urllib.robotparser.RobotFileParser()
        try:
            response = requests.get(site + "/robots.txt", headers={"User-Agent": USER_AGENT},
                                    timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code >= 400:
                parser.parse([])
            else:
                parser.parse(response.text.splitlines())
        except requests.RequestException:
            parser.parse([])
        _robot_parsers[site] = parser
    return parser.can_fetch(USER_AGENT, url)


def read_feed(feed_url):
    """Returns [(title, link, body)] from an RSS or Atom feed. body is the item's full text
    (content:encoded or Atom content) when the feed carries one, else None."""
    response = requests.get(feed_url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(response.content, parser=parser)
    items = []
    if root is None:
        return items
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        local_name = etree.QName(element).localname
        if local_name not in ("item", "entry"):
            continue
        title = ""
        link = ""
        body = None
        for child in element:
            if not isinstance(child.tag, str):
                continue
            child_name = etree.QName(child).localname
            if child_name == "title":
                title = (child.text or "").strip()
            elif child_name == "link":
                if not link:
                    link = (child.text or child.get("href") or "").strip()
            elif child_name in ("encoded", "content"):
                body = (child.text or "").strip() or None
        if title:
            items.append((title, link, body))
    return items


def baseline_urls():
    urls = set()
    baseline_pages_path = os.path.join(BASELINE_DATA_DIRECTORY, "pages.json")
    if os.path.exists(baseline_pages_path):
        with open(baseline_pages_path, encoding="utf-8") as file:
            for page_entry in json.load(file):
                urls.add(page_entry["url"])
    return urls


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--data", default="data")
    argument_parser.add_argument("--per-feed", type=int, default=ARTICLES_PER_FEED)
    argument_parser.add_argument("--feeds", choices=["baseline", "fresh"], default="baseline")
    arguments = argument_parser.parse_args()
    data_directory = os.path.join(TEST_DIRECTORY, arguments.data)
    pages_directory = os.path.join(data_directory, "pages")
    os.makedirs(pages_directory, exist_ok=True)
    feeds = FEEDS
    if arguments.feeds == "fresh":
        feeds = FRESH_FEEDS
    already_saved = set()
    if os.path.abspath(data_directory) != os.path.abspath(BASELINE_DATA_DIRECTORY):
        already_saved = baseline_urls()
    feed_titles = []
    pages = []
    feed_report = []
    page_number = 0
    for source, language, feed_url in feeds:
        try:
            items = read_feed(feed_url)
        except Exception as error:
            feed_report.append({"source": source, "feed_status": f"failed: {error}"[:200]})
            print(f"{source}: feed failed ({error})"[:160])
            continue
        for title, link, _ in items:
            feed_titles.append({"source": source, "language": language, "title": title})
        saved_for_feed = 0
        failed_attempts = 0
        statuses = []
        for title, link, feed_body in items:
            if saved_for_feed >= arguments.per_feed:
                break
            if failed_attempts >= FAILED_ATTEMPTS_PER_WANTED_PAGE * arguments.per_feed:
                statuses.append("gave up")
                break
            if not link.startswith("http") or link in already_saved:
                continue
            if not allowed_by_robots(link):
                statuses.append("robots.txt disallows")
                failed_attempts += 1
                continue
            started = time.perf_counter()
            try:
                response = requests.get(link, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
            except requests.RequestException as error:
                statuses.append(f"error {type(error).__name__}")
                failed_attempts += 1
                continue
            fetch_milliseconds = (time.perf_counter() - started) * 1000
            if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
                statuses.append(f"HTTP {response.status_code}")
                failed_attempts += 1
                time.sleep(1)
                continue
            page_number += 1
            file_name = f"page_{page_number:03d}.html"
            with open(os.path.join(pages_directory, file_name), "wb") as file:
                file.write(response.content)
            pages.append({
                "file": file_name, "source": source, "language": language, "url": response.url,
                "feed_title": title, "fetch_milliseconds": round(fetch_milliseconds, 1),
                "bytes": len(response.content), "encoding": response.encoding,
                "content_type": response.headers.get("content-type", ""), "feed_body": feed_body,
            })
            saved_for_feed += 1
            statuses.append("saved")
            time.sleep(1)  # be polite to each site
        feed_report.append({"source": source, "items": len(items), "article_statuses": statuses})
        print(f"{source}: {len(items)} items, saved {saved_for_feed}, statuses {statuses}")
    with open(os.path.join(data_directory, "feed_titles.json"), "w", encoding="utf-8") as file:
        json.dump(feed_titles, file, ensure_ascii=False, indent=1)
    with open(os.path.join(data_directory, "pages.json"), "w", encoding="utf-8") as file:
        json.dump(pages, file, ensure_ascii=False, indent=1)
    with open(os.path.join(data_directory, "feed_report.json"), "w", encoding="utf-8") as file:
        json.dump(feed_report, file, ensure_ascii=False, indent=1)
    print(f"\n{len(feed_titles)} feed titles, {len(pages)} pages saved")


if __name__ == "__main__":
    main()
