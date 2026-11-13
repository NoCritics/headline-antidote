# Visible-article extractor: test results

## Live pages (56 pages, 14 sites), with the CSS cascade

The last mode runs only on the 0 pages whose feed carries the item's text.

| Mode | Correct headline | Verdicts | Would go to a browser | Time p50 / p95 / max (ms) |
|---|---|---|---|---|
| page <style> only | 55 / 56 | pass: 56 | 5 / 56 | 213.5 / 750.8 / 902.3 |
| with external stylesheets | 55 / 56 | pass: 56 | 5 / 56 | 252.6 / 647.8 / 778.6 |
| external stylesheets and the feed title | 56 / 56 | pass: 56 | 4 / 56 | 258.8 / 603.8 / 1101.1 |

Times are with compiled stylesheets cached, as they are after a site's first page. First pass, while each site's CSS was being compiled: p50 429.4 ms, p95 2250.4 ms. The page fetch itself takes about 1,200 ms (p50).

These pages are presumably clean, so every flag below was reviewed by hand.

### Flags, page <style> only, grouped by site and kind

| Site | Flag | Severity | Flags | Pages | Examples |
|---|---|---|---|---|---|
| Business Insider | `body_text_not_in_page_copy` | low | 2 | 2 | page_023.html Business Insider [body] `body_text_not_in_page_copy` (low): 'from award winning fish tacos to tiki drinks ventura has a great food and drink scene': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… <br> page_024.html Business Insider [body] `body_text_not_in_page_copy` (low): 'we ve held to our no screen values with a few exceptions / there s never a dull moment an…': 2 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… |
| Economic Times | `body_text_not_in_page_copy` | low | 2 | 2 | page_037.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… <br> page_039.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… |
| BBC Business | `headline_from_metadata` | low | 1 | 1 | page_006.html BBC Business [headline] `headline_from_metadata` (low): 'Could the US midterms put a pin in the AI bubble?': no visible heading matches the page's titles; using the json-ld headline, which is not checked for visibility |
| Economic Times | `invisible_character` | low | 2 | 1 | page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the og:title: U+200B ZERO WIDTH SPACE <br> page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the <title>: U+200B ZERO WIDTH SPACE |
| Globes | `headline_adds_words` | low | 1 | 1 | page_048.html Globes [headline] `headline_adds_words` (low): 'ברבעון': the page's heading adds 'ברבעון' to the json-ld headline, and no other title has these words; they may be hidden from readers by a script or an overl… |
| Seeking Alpha | `hidden_text_in_article` | low | 1 | 1 | page_027.html Seeking Alpha [body] `hidden_text_in_article` (low): 'Search fieldEntering text into the input field will update the search result below': hidden from readers (hidden attribute); a standard extractor would pass it to the model; removed from the body |

### Flags, with external stylesheets, grouped by site and kind

| Site | Flag | Severity | Flags | Pages | Examples |
|---|---|---|---|---|---|
| Business Insider | `body_text_not_in_page_copy` | low | 2 | 2 | page_023.html Business Insider [body] `body_text_not_in_page_copy` (low): 'from award winning fish tacos to tiki drinks ventura has a great food and drink scene': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… <br> page_024.html Business Insider [body] `body_text_not_in_page_copy` (low): 'we ve held to our no screen values with a few exceptions / there s never a dull moment an…': 2 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… |
| Economic Times | `body_text_not_in_page_copy` | low | 2 | 2 | page_037.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… <br> page_039.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… |
| BBC Business | `headline_from_metadata` | low | 1 | 1 | page_006.html BBC Business [headline] `headline_from_metadata` (low): 'Could the US midterms put a pin in the AI bubble?': no visible heading matches the page's titles; using the json-ld headline, which is not checked for visibility |
| Economic Times | `invisible_character` | low | 2 | 1 | page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the og:title: U+200B ZERO WIDTH SPACE <br> page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the <title>: U+200B ZERO WIDTH SPACE |
| Globes | `headline_adds_words` | low | 1 | 1 | page_048.html Globes [headline] `headline_adds_words` (low): 'ברבעון': the page's heading adds 'ברבעון' to the json-ld headline, and no other title has these words; they may be hidden from readers by a script or an overl… |
| Seeking Alpha | `hidden_text_in_article` | low | 1 | 1 | page_027.html Seeking Alpha [body] `hidden_text_in_article` (low): 'Search fieldEntering text into the input field will update the search result below': hidden from readers (hidden attribute); a standard extractor would pass it to the model; removed from the body |

### Flags, external stylesheets and the feed title, grouped by site and kind

| Site | Flag | Severity | Flags | Pages | Examples |
|---|---|---|---|---|---|
| Business Insider | `body_text_not_in_page_copy` | low | 2 | 2 | page_023.html Business Insider [body] `body_text_not_in_page_copy` (low): 'from award winning fish tacos to tiki drinks ventura has a great food and drink scene': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… <br> page_024.html Business Insider [body] `body_text_not_in_page_copy` (low): 'we ve held to our no screen values with a few exceptions / there s never a dull moment an…': 2 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… |
| Economic Times | `body_text_not_in_page_copy` | low | 2 | 2 | page_037.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… <br> page_039.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the… |
| Economic Times | `invisible_character` | low | 2 | 1 | page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the og:title: U+200B ZERO WIDTH SPACE <br> page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the <title>: U+200B ZERO WIDTH SPACE |
| Seeking Alpha | `hidden_text_in_article` | low | 1 | 1 | page_027.html Seeking Alpha [body] `hidden_text_in_article` (low): 'Search fieldEntering text into the input field will update the search result below': hidden from readers (hidden attribute); a standard extractor would pass it to the model; removed from the body |

### Flags, external stylesheets, feed title and feed text, grouped by site and kind

- none
| Site | Flag | Severity | Flags | Pages | Examples |
|---|---|---|---|---|---|

### Every flag, page <style> only

- page_006.html BBC Business [headline] `headline_from_metadata` (low): 'Could the US midterms put a pin in the AI bubble?': no visible heading matches the page's titles; using the json-ld headline, which is not checked for visibility
- page_023.html Business Insider [body] `body_text_not_in_page_copy` (low): 'from award winning fish tacos to tiki drinks ventura has a great food and drink scene': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_024.html Business Insider [body] `body_text_not_in_page_copy` (low): 'we ve held to our no screen values with a few exceptions / there s never a dull moment an…': 2 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_027.html Seeking Alpha [body] `hidden_text_in_article` (low): 'Search fieldEntering text into the input field will update the search result below': hidden from readers (hidden attribute); a standard extractor would pass it to the model; removed from the body
- page_037.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_039.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the og:title: U+200B ZERO WIDTH SPACE
- page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the <title>: U+200B ZERO WIDTH SPACE
- page_048.html Globes [headline] `headline_adds_words` (low): 'ברבעון': the page's heading adds 'ברבעון' to the json-ld headline, and no other title has these words; they may be hidden from readers by a script or an overl…

### Every flag, with external stylesheets

- page_006.html BBC Business [headline] `headline_from_metadata` (low): 'Could the US midterms put a pin in the AI bubble?': no visible heading matches the page's titles; using the json-ld headline, which is not checked for visibility
- page_023.html Business Insider [body] `body_text_not_in_page_copy` (low): 'from award winning fish tacos to tiki drinks ventura has a great food and drink scene': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_024.html Business Insider [body] `body_text_not_in_page_copy` (low): 'we ve held to our no screen values with a few exceptions / there s never a dull moment an…': 2 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_027.html Seeking Alpha [body] `hidden_text_in_article` (low): 'Search fieldEntering text into the input field will update the search result below': hidden from readers (hidden attribute); a standard extractor would pass it to the model; removed from the body
- page_037.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_039.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the og:title: U+200B ZERO WIDTH SPACE
- page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the <title>: U+200B ZERO WIDTH SPACE
- page_048.html Globes [headline] `headline_adds_words` (low): 'ברבעון': the page's heading adds 'ברבעון' to the json-ld headline, and no other title has these words; they may be hidden from readers by a script or an overl…

### Every flag, external stylesheets and the feed title

- page_023.html Business Insider [body] `body_text_not_in_page_copy` (low): 'from award winning fish tacos to tiki drinks ventura has a great food and drink scene': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_024.html Business Insider [body] `body_text_not_in_page_copy` (low): 'we ve held to our no screen values with a few exceptions / there s never a dull moment an…': 2 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_027.html Seeking Alpha [body] `hidden_text_in_article` (low): 'Search fieldEntering text into the input field will update the search result below': hidden from readers (hidden attribute); a standard extractor would pass it to the model; removed from the body
- page_037.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_039.html Economic Times [body] `body_text_not_in_page_copy` (low): 'what s moving sensex and nifty track latest market news stock tips budget 2025 share mark…': 1 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions, but text hidden by a script would look the…
- page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the og:title: U+200B ZERO WIDTH SPACE
- page_040.html Economic Times [metadata] `invisible_character` (low): '\u200b': in the <title>: U+200B ZERO WIDTH SPACE

### Every flag, external stylesheets, feed title and feed text

- none

### Every page with external stylesheets: headline and the start and end of the body

| Page | Headline | Body chars (style only → external) | Body start | Body end |
|---|---|---|---|---|
| page_001.html CNBC | Cosm rides premium moviegoing wave with more immersive scre… | 7977 → 7977 | The next big thing in premium large format theatrical viewing takes inspiration from the … |  at cinema marketing firm PaperAirplane Media. "That is something they can't get at home." |
| page_002.html CNBC | Where's the growth? Legacy automakers face a tougher 2027 a… | 6207 → 6207 | DETROIT — There's a growing concern that the global automotive industry may be stuck in n… |  of the economy," Robb said during a Sept. 24 call, noting consumer sentiment remains low. |
| page_003.html CNBC | Small retailers brace for 'huge hit' this holiday season as… | 5877 → 5877 | When Jenni Shields began her small business eight years ago selling handmade hair accesso… | t's kind of a little bit bad for everybody," Cheris said. "I think that is the challenge." |
| page_004.html CNBC | Tesla to wind down Cybertruck production in Texas next year… | 3023 → 3023 | Tesla CEO Elon Musk on Friday said the electric vehicle maker will "be winding down" prod… | to software defects and an inverter fault that could result in sudden loss of drive power. |
| page_005.html BBC Business | AI stocks climb after trillions wiped from market values | 4832 → 4832 | Shares in artificial intelligence and technology firms have recovered slightly from an en… |  about at the moment are not such a risk to the real economy as is being feared," he said. |
| page_006.html BBC Business | Could the US midterms put a pin in the AI bubble? **(wrong)** | 5063 → 5063 | Why the US midterms sparked an AI stock selloff / Is the artificial intelligence (AI) gol… | reflect I think that actually there's still a lot of money being made in these companies". |
| page_007.html BBC Business | How does it affect me if share prices fall? | 6207 → 6207 | Major tech firms have seen their stock values fall after a sell-off by investors followin… | ember: This article was amended to provide more context around how companies issue shares. |
| page_008.html BBC Business | Why smoky bacon crisps threaten to reignite rows over EU ru… | 4606 → 4606 | The naming of smoky bacon-flavoured crisps has become the latest political headache to em… | ike, or whether they would need to apply from 2029 alongside the new European regulations. |
| page_009.html Guardian Business | Lanarkshire AI datacentre to fully rely on National Grid de… | 3621 → 3621 | A datacentre company that said it would power a massive AI development near Glasgow with … | urce of grid power,” she said. “It is not surprising that the goalposts have now changed.” |
| page_010.html Guardian Business | Reform UK councillor promoted collapsed $1.9bn ‘Ponzi schem… | 3830 → 3830 | A woman who promoted a notorious cryptocurrency scam has been elected as a Reform UK coun… | spond to a question about whether its vetting team had picked up on Lawrence’s background. |
| page_011.html Guardian Business | Job cuts, lost customers and a £22bn debt pile: what has go… | 6249 → 6249 | Mike Fries may be totting up swingeing job cuts, a £22bn debt pile and the loss of hundre… | nt needed, and for VMO2 and the wider industry I don’t really see what turns that around.” |
| page_012.html Guardian Business | Great British Railways: new dawn for a new network but with… | 5620 → 5620 | The glad tidings brought by the minister were that the wait was almost over: the establis… | kes shape, with a “super El Niño” event likely to test the infrastructure as never before. |
| page_013.html NPR Business | The Cybertruck's 'cause of death?' Insufficient demand | 3557 → 3557 | One of the most polarizing vehicles to hit the road will soon be a thing of history. Tesl… | ipts for that content and some transcripts may be produced using automated or other tools. |
| page_014.html NPR Business | This was the week the AI trade cracked. So what's next? | 8057 → 8057 | Big losses by AI shares in stock markets after Democrats won the midterm elections have l… | ipts for that content and some transcripts may be produced using automated or other tools. |
| page_015.html NPR Business | Hiring jumps: The economy added 165,000 jobs last month | 1506 → 1506 | The U.S. job market picked up steam last month. / Employers added 165,000 jobs in October… | last week, but investors expect the Fed to raise rates when policymakers meet in December. |
| page_016.html NPR Business | Why gold prices are surprisingly low | 7625 → 7625 | You're reading a newsletter from The Indicator from Planet Money. Once a week, we curate … | p to the sun! cut these bits out of the next page!) that you won't be able to put it down. |
| page_017.html Fortune | Berkshire Hathaway stock is a haven again as investors flee… | 2926 → 2926 | Investors are seeking shelter from the AI storm in Berkshire Hathaway after shares of the… |  Texas, Ohio and Georgia is expected to slow down the AI buildout and the overall economy. |
| page_018.html Fortune | Billionaire Brian Chesky’s social-worker parents told him t… | 4813 → 4813 | Before Airbnb had over 9 million listings worldwide, there was one sole lodging: three in… | s of people won’t survive the AI era: ‘pure people managers’ and workers who resist change |
| page_019.html Fortune | Starter homes cost $1 million in a record 242 U.S. cities—p… | 6216 → 6216 | They waited out the pandemic boom. They saved longer, rented longer, delayed longer, and … | happening in Texas. / A version of this story was published on Fortune.com on June 17, 20… |
| page_020.html Fortune | This CEO lived on canned soup and took just two days off fo… | 5885 → 5885 | The grind to success can be long, punishing, and it can quietly take more than it gives. … | Gen Z than work-life balance, survey says—with 93% of interns wanting to become executives |
| page_021.html Business Insider | I replaced our smart TV with an old VHS player. My kids wat… | 3967 → 3967 | This as-told-to essay is based on a conversation with Mariah Smith. It has been edited fo… |  but that we've found a slower, calmer way of living that works far better for our family. |
| page_022.html Business Insider | Elon Musk and Elizabeth Holmes share a 'superpower,' says d… | 1011 → 1011 | If anyone could find a connection between Elon Musk and Elizabeth Holmes, it's director A… | ce, to convince people of things that they knew not to be true. That became a superpower." |
| page_023.html Business Insider | As a Los Angeles local, I love taking a $22 train to this s… | 3612 → 3612 | Given the opportunity, I'd happily travel everywhere by train. Luckily, I live in Souther… | ty of good seafood into a 12-hour day trip — all without ever having to set foot in a car. |
| page_024.html Business Insider | I don't allow my toddler screen time. Sometimes I envy the … | 4363 → 4363 | Even before having a kid, my husband and I discussed our parenting values. / We knew we w… | h the world around him, and we wouldn't trade it, even as tempting as it can sometimes be. |
| page_025.html Seeking Alpha | Nvidia CEO was romantically involved with alleged Chinese s… | 270 → 270 | The Trump administration believes Nvidia’s (NVDA) CEO, Jensen Huang, had a romantic relat… | , The Financial Times reported on Saturday, citing a government memo. / Based on informat… |
| page_026.html Seeking Alpha | Bulls vs. Bears: NVIDIA sparks valuation debate as stock ne… | 354 → 354 | Nvidia (NVDA) recorded its sixth consecutive weekly drop this week amid a broader selloff… |  12:43 PM ETNVIDIA Corporation (NVDA) StockBy : Dulan Lokuwithana, SA News Editor1 Comment |
| page_027.html Seeking Alpha | Real estate stocks gain as the Blue Wave sends Treasury yie… | 290 → 290 | Real estate stocks were gaining as the Democrats sweep of Congress in the U.S. midterm el… | ising prices, the Iran war, and government corruption. The party is positioning itself for |
| page_028.html Seeking Alpha | Energy Earnings Scorecard: Strong Q3 results drive clean sw… | 267 → 426 | Nov 07, 2026, 11:56 AM ETState Street Materials Select Sector SPDR ETF (XLB), VDE, XOP, O… | top oil producers including Devon Energy (DVN) and ConocoPhillips (COP). While uncertainty |
| page_029.html Al Jazeera | Pope Leo hold first mass in Uruguay, urges crowd to be ‘bri… | 2405 → 2405 | Vatican says some 40,000 people gathered to listen to the head of the Roman Catholic Chur… | r Milei, a strong proponent of free markets and a close ally of US President Donald Trump. |
| page_030.html Al Jazeera | Houthis report 25 killed in Yemen strikes | 266 → 244 | Yemen’s Houthis say at least 25 people have been killed and 30 injured in air strikes the… | t that nine attacks targeted telecommunications networks in Sa’ada governorate. / Save / … |
| page_031.html Al Jazeera | Lebanese footballer refuses to give up after injuries from … | 309 → 285 | NewsFeed / After surviving a devastating Israeli air strike on Beirut that left her in a … | 1, she is back on the pitch, coaching young players and refusing to give up on her dreams. |
| page_032.html Al Jazeera | Jerusalem Daily: Heavy rains flood Gaza | 378 → 354 | NewsFeed / Heavy rains have flooded thousands of tents in Gaza, leaving displaced Palesti… | d on a Bedouin village in the occupied West Bank. Al Jazeera’s Nour Hegazy has the latest. |
| page_033.html Nikkei Asia | Credit Saison, ADB to partner on loans for Asia's small bus… | 528 → 528 | Finance / Japanese financial services company to leverage expertise gained in India opera… | ls and experience gained in India to develop an earnings stream in other emerging markets. |
| page_034.html Nikkei Asia | US sports investment fund RedBird hunts for tie-ups in Japan | 572 → 572 | Sports / Firm specializes in using data, intellectual property to boost revenue steams / … | engagement to lift the earning power of the country's sports industry, Nikkei has learned. |
| page_035.html Nikkei Asia | Astellas employee jailed in China on spy charge set for Dec… | 468 → 468 | TOKYO -- A Japanese executive of Astellas Pharma imprisoned in China on espionage charges… | 23 that broadened the range of activities subject to investigation. (Photo by Tomoki Mera) |
| page_036.html Nikkei Asia | New Zealand's knife-edge election puts coalition talks in f… | 518 → 518 | AUCKLAND -- New Zealand's ruling center-right National Party appears set to win the most … | nd his daughter Olivia at an election party in Auckland, New Zealand, on Nov. 7. © Reuters |
| page_037.html Economic Times | Dalal Street Week Ahead: Nifty bulls come back to life, but… | 4968 → 4968 | The markets have witnessed a significant improvement in their technical structure followi… | are Price, HDFC Bank Share Price, Infosys Share Price, Wipro Share Price, NTPC Share Price |
| page_038.html Economic Times | Concurrent Gainers: 9 stocks gain for 5 days in a row | 451 → 451 | Over the five trading sessions ending November 6, the Sensex surged 8.82%, or 6,568 point… | e period, delivering cumulative returns ranging from 15% to 20%. (Data Source: ACE Equity) |
| page_039.html Economic Times | Wall Street grapples with $5.7 trillion rout as AI bets unw… | 5324 → 5324 | The worries have been on display all year: stretched valuations, mounting debt and doubts… | are Price, HDFC Bank Share Price, Infosys Share Price, Wipro Share Price, NTPC Share Price |
| page_040.html Economic Times | Patakha stock picks! ICICI Bank, BEL, 6 other stocks with 6… | 2022 → 6224 | Diwali Delights / As investors enter Samvat 2083, the landscape calls for selectivity rat… |  make their investment decisions based on their own assessment. Brokerage disclaimers here |
| page_041.html Interfax | Производственное здание горит в Пензенской области на 1,5 т… | 485 → 485 | Москва. 7 ноября. INTERFAX.RU - Пожарные тушат крупное возгорание в производственном здан… | ообщении. / На месте работают более 20 человек и 13 единиц техники, уточнили в пресс-служ… |
| page_042.html Interfax | МВД Франции заявило о почти 150 тыс. участников протестов 7… | 2149 → 2149 | Москва. 7 ноября. INTERFAX.RU - Очередной протестный день во Франции прошел в субботу при… | ественного порядка во Франции 7 ноября были задействованы 70 тыс. полицейских и жандармов. |
| page_043.html Interfax | Ликвидировано открытое горение на складе масел в Ростове-на… | 497 → 497 | Москва. 7 ноября. INTERFAX.RU - Пожарные ликвидировали открытое горение на складе масел и… | хранения масел и полимерных материалов. Пожар удалось локализовать на площади 8 тыс. кв.м. |
| page_044.html Interfax | Сирия не планирует отправлять войска в Йемен | 957 → 957 | Москва. 7 ноября. INTERFAX.RU - Сирийские власти сообщили, что на данный момент не планир… | ях против хуситов. / Саудовская Аравия возглавляет коалицию, ведущую бои против сил хусит… |
| page_045.html Globes | אחרי פריצת המיליארדים: סמנכ"ל הכספים של בייננס מתפטר | 1720 → 1720 | בורסת הקריפטו הגדולה בעולם בייננס הודיעה היום (שבת) כי סמנכ"ל הכספים שלה, קייזר נג, יעזוב… | ערכות לזיהוי איומים, בין היתר באמצעות בינה מלאכותית, וכי ימשיכו לפעול להשבת הכספים שנגנבו. |
| page_046.html Globes | הוא חזה את גל העליות הגדול בבורסה. מה לדעתו יקרה עכשיו - וע… | 331 → 331 | הבורסה בתל אביב ירדה במעל 15% משיאה האחרון ואנליסטים מעריכים האם הגיע הזמן לקנות את היריד… | ק מסבירים שהמשקיעים עברו "לשבת על הגדר" • וגם: מנהל ההשקעות שאופטימי למרות הירידות בשווקים |
| page_047.html Globes | הנתון שישפיע על כיוון השווקים השבוע, והפרט החריג שמסתתר בו | 1996 → 1996 | אחרי אחד השבועות הסוערים של השנה בוול סטריט, המשקיעים נערכים למבחן הבא: ביום שלישי הקרוב … | בי המשך ההשקעות העצומות בתשתיות AI, שהפכו בחודשים האחרונים לאחד ממוקדי החשש המרכזיים בשוק. |
| page_048.html Globes | הרווח התפעולי של ברקשייר ירד ברבעון, ויש מניה אחת שהיא לא ה… | 2747 → 2747 | ענקית ההשקעות ברקשייר האת’ווי , שבנה וורן באפט במשך יותר משישה עשורים, פרסמה היום (שבת) א… | שויה להעיד כי גם תחת ההנהלה החדשה, ברקשייר מתקשה למצוא השקעות אטרקטיביות במחירים הנוכחיים. |
| page_049.html Handelsblatt | Quartalszahlen: Berkshire meldet Gewinnrückgang, doch die A… | 1328 → 1328 | Berkshire meldet Gewinnrückgang, doch die Aktie profitiert  / Frankfurt. Berkshire-Hathaw… | zurück. Hauptgrund war ein deutlicher Gewinnrückgang in der wichtigen Versicherungssparte. |
| page_050.html Handelsblatt | Immobilien: Wo um Hamburg herum für Pendler noch Schnäppche… | 1011 → 1011 | Hamburg. Ab Ende des Monats kommt es in Seevetal südlich von Hamburg zur Entscheidung. Da… | latt exklusiv vorliegt, nennt die aktuell besten Lagen für Pendler rund um die Hansestadt. |
| page_051.html Handelsblatt | Vermögen: Schenkung an Kinder – Diese Zusatzkosten sollten … | 756 → 756 | Frankfurt. Geld und Immobilien zu Lebzeiten verschenken, statt später zu vererben. Für Ve… |  Schenkende beachten sollten und warum solche Überlegungen aktuell besonders wichtig sind. |
| page_052.html Handelsblatt | EZB: Spanien nominiert Pablo Hernandez de Cos für Lagarde-N… | 1237 → 1237 | Madrid. Im Rennen um die Nachfolge von Christine Lagarde an der Spitze der Europäischen Z… | en Montag (9. November) geplant, dann soll eine Bestandsaufnahme der Bewerbungen erfolgen. |
| page_053.html Yahoo Japan Business | 鮮やかなポルシェ948、堂々登場!!! | 981 → 981 | 完成度の高いハイブリッド・モンスターに注目! / 【写真を見る】これがポルシェ948の全貌だ!!! / 概要 / 11月3日から6日にかけてアメリカ・ネバダ州ラスベガスのコンベン… | 差ない重量に抑えることが可能であり、944の美点である理想的な前後重量配分を崩すことなく、自然吸気ならではの大トルクと高回転まで突き抜けるV8サウンドを手に入れることができるのだ。 |
| page_054.html Yahoo Japan Business | 前代未聞の新型ゲームオーバー登場! S-KLUB LAが手がけた、別名“CLK750S”に迫る! | 823 → 823 | トーヨータイヤなどの協力も得て開発された、驚きのマシンとは? / 【写真を見る】新型ゲームオーバーの全貌(19点) / 概要 / アメリカ・南カリフォルニアを拠点とする「S-KL… | の「ゲームオーバー」は、名高いカスタムビルダーでありデザイナーでもある「Slang500(スラング500)」ことモー(Mo)とのコラボレーションによって生み出されたプロジェクトだ。 |
| page_055.html Yahoo Japan Business | 「月給30万円の手取り」はいくら?月給(額面)別の手取り額一覧表を年代別にみる | 1685 → 1685 | 額面の月給と、実際に口座に振り込まれる金額は同じではありません。健康保険料や厚生年金保険料、所得税などが、給与から差し引かれているためです。明細の「控除」の欄を見ると、何がいくら… | 。 / 自分がどの等級にあたるのかは、給与明細の保険料の金額や、勤め先の担当の窓口で確かめられます。一覧表の金額は、あくまで同じ前提で並べた目安として読んでみてください。 / 宮… |
| page_056.html Yahoo Japan Business | レクサスのトラック、遂に登場か!? 新型TX1デビュー!!! | 1148 → 1148 | レクサスブランドからラグジュアリー・ピックアップトラックが出たらこうなる!? / 【写真を見る】これがレクサス・トラックだ!!!(30点)新型TX1の全貌!!! / 概要 / 2… | 付きであった。 / そのMESO Customsが約1年もの歳月を費やし、2026年のSEMAショーに向けて極秘裏に温めてきた集大成ともいえるプロジェクトが、この「TX1」なので… |

## Attack pages from scraper_comparison (their CSS is all in the page)

| Page | Attack? | Verdict | Browser check? | Headline given to the model | Hidden payload in output? |
|---|---|---|---|---|---|
| `clean_english` | no | pass | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `clean_russian` | no | pass | no | Акции Alphabet выросли после решения суда | no |
| `clean_styled` | no | pass | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `homoglyph_name` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `zero_width_in_name` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `tag_characters` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `display_none` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `font_size_zero` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `color_matches_background` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `style_block_class` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `tiny_font` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `near_zero_opacity` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `white_text_undeclared_background` | yes | review | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `off_screen` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `complex_selector` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `javascript_hidden` | yes | review | yes | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `complex_selector_font_size` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `complex_selector_opacity` | yes | quarantine | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `javascript_opacity` | yes | review | yes | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `clean_javascript_rendered` | no | pass | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `javascript_rendered_homoglyph` | yes | pass | no | Alphabet shares surge after dodging antitrust breakup bullet | no |
| `clean_dark_theme` | no | pass | no | Alphabet shares surge after dodging antitrust breakup bullet | no |