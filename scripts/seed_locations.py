"""
Idempotent location seed script.

Populates: countries, cities, sources, source_coverage.
Safe to run multiple times — all writes use ON CONFLICT DO UPDATE.

Usage:
  python -m scripts.seed_locations
  # or from repo root:
  python scripts/seed_locations.py
"""
import asyncio
import os
import sys

# Allow running directly from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.location_db import (
    ensure_location_schema,
    upsert_country,
    upsert_city,
    upsert_source,
    upsert_coverage,
)

# ───────────────────────────────────────────────────────────────────
# Countries
# ───────────────────────────────────────────────────────────────────

COUNTRIES = [
    {"name": "Germany",        "code": "DE", "flag": "🇩🇪"},
    {"name": "United Kingdom", "code": "GB", "flag": "🇬🇧"},
    {"name": "United States",  "code": "US", "flag": "🇺🇸"},
    {"name": "France",         "code": "FR", "flag": "🇫🇷"},
    {"name": "Netherlands",    "code": "NL", "flag": "🇳🇱"},
    {"name": "Spain",          "code": "ES", "flag": "🇪🇸"},
    {"name": "Italy",          "code": "IT", "flag": "🇮🇹"},
    {"name": "Austria",        "code": "AT", "flag": "🇦🇹"},
    {"name": "Switzerland",    "code": "CH", "flag": "🇨🇭"},
    {"name": "Poland",         "code": "PL", "flag": "🇵🇱"},
    {"name": "Turkey",         "code": "TR", "flag": "🇹🇷"},
    {"name": "Australia",      "code": "AU", "flag": "🇦🇺"},
    {"name": "India",          "code": "IN", "flag": "🇮🇳"},
]

# ───────────────────────────────────────────────────────────────────
# Cities  (country_code, display_name, slug, lat, lon)
# ───────────────────────────────────────────────────────────────────

CITIES = [
    # Germany
    ("DE", "Berlin",       "berlin",        52.52,   13.405),
    ("DE", "Munich",       "munich",        48.137,  11.576),
    ("DE", "Hamburg",      "hamburg",       53.551,   9.993),
    ("DE", "Frankfurt",    "frankfurt",     50.110,   8.682),
    # United Kingdom
    ("GB", "London",       "london",        51.507,  -0.128),
    ("GB", "Manchester",   "manchester",    53.483,  -2.244),
    # United States
    ("US", "New York",     "new-york",      40.713, -74.006),
    ("US", "San Francisco","san-francisco", 37.774,-122.419),
    ("US", "Chicago",      "chicago",       41.878, -87.630),
    # France
    ("FR", "Paris",        "paris",         48.857,   2.352),
    # Netherlands
    ("NL", "Amsterdam",    "amsterdam",     52.370,   4.895),
    # Spain
    ("ES", "Madrid",       "madrid",        40.416,  -3.703),
    ("ES", "Barcelona",    "barcelona",     41.385,   2.173),
    # Italy
    ("IT", "Rome",         "rome",          41.902,  12.496),
    ("IT", "Milan",        "milan",         45.464,   9.188),
    # Austria
    ("AT", "Vienna",       "vienna",        48.208,  16.373),
    # Switzerland
    ("CH", "Zurich",       "zurich",        47.377,   8.536),
    # Poland
    ("PL", "Warsaw",       "warsaw",        52.230,  21.012),
    # Turkey
    ("TR", "Istanbul",     "istanbul",      41.008,  28.978),
    # Australia
    ("AU", "Sydney",       "sydney",       -33.869, 151.209),
    ("AU", "Melbourne",    "melbourne",    -37.814, 144.963),
    ("AU", "Brisbane",     "brisbane",     -27.469, 153.025),
    ("AU", "Perth",        "perth",        -31.952, 115.861),
    # India
    ("IN", "Mumbai",       "mumbai",        19.076,  72.878),
    ("IN", "Delhi",        "delhi",         28.635,  77.224),
    ("IN", "Bangalore",    "bangalore",     12.972,  77.594),
    ("IN", "Chennai",      "chennai",       13.083,  80.270),
    ("IN", "Hyderabad",    "hyderabad",     17.385,  78.487),
]

# ───────────────────────────────────────────────────────────────────
# Sources
# Columns: name, rss_url, lang, category, coverage_level, country_code, city_slug
# country_code=None  → international source
# city_slug=None     → national or international source
# ───────────────────────────────────────────────────────────────────

SOURCES = [
    # ── Germany — Berlin ────────────────────────────────────────────
    ("Berliner Morgenpost", "https://www.morgenpost.de/rss",
     "de", "local_news", "city", "DE", "berlin"),
    ("Tagesspiegel", "https://www.tagesspiegel.de/contentexport/feed/home",
     "de", "local_news", "city", "DE", "berlin"),
    ("RBB Berlin", "https://www.rbb24.de/rss/rss.xml",
     "de", "local_news", "city", "DE", "berlin"),
    # ── Germany — Munich ────────────────────────────────────────────
    ("Süddeutsche Zeitung", "https://rss.sueddeutsche.de/rss/Topthemen",
     "de", "local_news", "city", "DE", "munich"),
    ("Münchner Merkur", "https://www.merkur.de/welt/rssfeed.rdf",
     "de", "local_news", "city", "DE", "munich"),
    # ── Germany — Hamburg ──────────────────────────────────────────
    ("NDR Hamburg", "https://www.ndr.de/nachrichten/hamburg/index~rss2.xml",
     "de", "local_news", "city", "DE", "hamburg"),
    ("Hamburger Abendblatt", "https://www.abendblatt.de/rss",
     "de", "local_news", "city", "DE", "hamburg"),
    # ── Germany — Frankfurt ────────────────────────────────────────
    ("Frankfurter Allgemeine", "https://www.faz.net/rss/aktuell",
     "de", "national_news", "city", "DE", "frankfurt"),
    # ── Germany — National ─────────────────────────────────────────
    ("Der Spiegel", "https://www.spiegel.de/schlagzeilen/index.rss",
     "de", "national_news", "national", "DE", None),
    ("Die Zeit", "https://newsfeed.zeit.de/all",
     "de", "national_news", "national", "DE", None),
    # ── UK — London ───────────────────────────────────────────────
    ("Time Out London", "https://www.timeout.com/london/rss.xml",
     "en", "culture", "city", "GB", "london"),
    ("Evening Standard", "https://www.standard.co.uk/rss",
     "en", "local_news", "city", "GB", "london"),
    # ── UK — Manchester ─────────────────────────────────────────
    ("Manchester Evening News", "https://www.manchestereveningnews.co.uk/rss.xml",
     "en", "local_news", "city", "GB", "manchester"),
    # ── UK — National ──────────────────────────────────────────
    ("BBC News", "http://feeds.bbci.co.uk/news/rss.xml",
     "en", "national_news", "national", "GB", None),
    ("The Guardian UK", "https://www.theguardian.com/uk/rss",
     "en", "national_news", "national", "GB", None),
    # ── US — New York ─────────────────────────────────────────
    ("Gothamist", "https://gothamist.com/feed",
     "en", "local_news", "city", "US", "new-york"),
    ("New York Times Metro", "https://rss.nytimes.com/services/xml/rss/nyt/NYRegion.xml",
     "en", "local_news", "city", "US", "new-york"),
    # ── US — San Francisco ─────────────────────────────────────
    ("SF Gate", "https://www.sfgate.com/rss/feed/SFGate-Top-News-476.php",
     "en", "local_news", "city", "US", "san-francisco"),
    ("KQED", "https://www.kqed.org/news/feed",
     "en", "local_news", "city", "US", "san-francisco"),
    # ── US — Chicago ──────────────────────────────────────────
    ("Chicago Tribune", "https://www.chicagotribune.com/arcio/rss/",
     "en", "local_news", "city", "US", "chicago"),
    ("Block Club Chicago", "https://blockclubchicago.org/feed/",
     "en", "local_news", "city", "US", "chicago"),
    # ── US — National ─────────────────────────────────────────
    ("NPR", "https://feeds.npr.org/1001/rss.xml",
     "en", "national_news", "national", "US", None),
    ("The Atlantic", "https://www.theatlantic.com/feed/all/",
     "en", "national_news", "national", "US", None),
    # ── France — Paris ────────────────────────────────────────
    ("Le Parisien", "https://feeds.leparisien.fr/leparisien/rss",
     "fr", "local_news", "city", "FR", "paris"),
    ("Time Out Paris", "https://www.timeout.com/paris/rss.xml",
     "fr", "culture", "city", "FR", "paris"),
    # ── France — National ──────────────────────────────────────
    ("Le Monde", "https://www.lemonde.fr/rss/une.xml",
     "fr", "national_news", "national", "FR", None),
    ("France 24", "https://www.france24.com/fr/rss",
     "fr", "national_news", "national", "FR", None),
    # ── Netherlands — Amsterdam ────────────────────────────────
    ("AT5", "https://www.at5.nl/rss",
     "nl", "local_news", "city", "NL", "amsterdam"),
    ("Het Parool", "https://www.parool.nl/rss",
     "nl", "local_news", "city", "NL", "amsterdam"),
    # ── Netherlands — National ───────────────────────────────
    ("NOS", "https://feeds.nos.nl/nosnieuwsalgemeen",
     "nl", "national_news", "national", "NL", None),
    ("De Volkskrant", "https://www.volkskrant.nl/rss.xml",
     "nl", "national_news", "national", "NL", None),
    # ── Spain — Madrid ────────────────────────────────────────
    ("El País Madrid", "https://ep00.epimg.net/rss/ccaa/madrid.xml",
     "es", "local_news", "city", "ES", "madrid"),
    # ── Spain — Barcelona ────────────────────────────────────
    ("La Vanguardia", "https://www.lavanguardia.com/rss/home.xml",
     "es", "local_news", "city", "ES", "barcelona"),
    # ── Spain — National ──────────────────────────────────────
    ("El Mundo", "https://e00-elmundo.uecdn.es/elmundo/rss/portada.xml",
     "es", "national_news", "national", "ES", None),
    # ── Italy — Rome ──────────────────────────────────────────
    ("Roma Today", "https://www.romatoday.it/rss/",
     "it", "local_news", "city", "IT", "rome"),
    ("Il Messaggero", "https://www.ilmessaggero.it/rss/home.xml",
     "it", "local_news", "city", "IT", "rome"),
    # ── Italy — Milan ─────────────────────────────────────────
    ("Milano Today", "https://www.milanotoday.it/rss/",
     "it", "local_news", "city", "IT", "milan"),
    ("Corriere della Sera", "https://xml2.corriereobjects.it/rss/homepage.xml",
     "it", "national_news", "city", "IT", "milan"),
    # ── Austria — Vienna ──────────────────────────────────────
    ("Der Standard", "https://derstandard.at/rss",
     "de", "local_news", "city", "AT", "vienna"),
    ("Wiener Zeitung", "https://www.wienerzeitung.at/meinungen/rss",
     "de", "local_news", "city", "AT", "vienna"),
    # ── Austria — National ─────────────────────────────────────
    ("ORF", "https://rss.orf.at/news.xml",
     "de", "national_news", "national", "AT", None),
    # ── Switzerland — Zurich ──────────────────────────────────
    ("NZZ", "https://www.nzz.ch/recent.rss",
     "de", "national_news", "city", "CH", "zurich"),
    ("20 Minuten", "https://www.20min.ch/rss/rss.tmpl",
     "de", "local_news", "city", "CH", "zurich"),
    # ── Poland — Warsaw ──────────────────────────────────────
    ("Gazeta Wyborcza", "https://rss.gazeta.pl/pub/rss/najnowsze_wyborcza.xml",
     "pl", "local_news", "city", "PL", "warsaw"),
    # ── Poland — National ────────────────────────────────────
    ("TVN24", "https://tvn24.pl/najnowsze.xml",
     "pl", "national_news", "national", "PL", None),
    # ── Turkey — Istanbul ─────────────────────────────────────
    ("Hürriyet", "https://www.hurriyet.com.tr/rss/anasayfa",
     "tr", "local_news", "city", "TR", "istanbul"),
    ("Sabah", "https://www.sabah.com.tr/rss/gundem.xml",
     "tr", "local_news", "city", "TR", "istanbul"),
    # ── Australia — Sydney ────────────────────────────────────
    ("Sydney Morning Herald", "https://www.smh.com.au/rss/feed.xml",
     "en", "local_news", "city", "AU", "sydney"),
    ("Time Out Sydney", "https://www.timeout.com/sydney/rss.xml",
     "en", "culture", "city", "AU", "sydney"),
    ("ABC Sydney", "https://www.abc.net.au/news/feed/51120/rss.xml",
     "en", "local_news", "city", "AU", "sydney"),
    # ── Australia — Melbourne ───────────────────────────────
    ("The Age", "https://www.theage.com.au/rss/feed.xml",
     "en", "local_news", "city", "AU", "melbourne"),
    ("Herald Sun", "https://www.heraldsun.com.au/news/breaking-news/rss",
     "en", "local_news", "city", "AU", "melbourne"),
    ("Time Out Melbourne", "https://www.timeout.com/melbourne/rss.xml",
     "en", "culture", "city", "AU", "melbourne"),
    # ── Australia — Brisbane ───────────────────────────────
    ("Brisbane Times", "https://www.brisbanetimes.com.au/rss/feed.xml",
     "en", "local_news", "city", "AU", "brisbane"),
    ("Courier Mail", "https://www.couriermail.com.au/news/breaking-news/rss",
     "en", "local_news", "city", "AU", "brisbane"),
    # ── Australia — Perth ───────────────────────────────────
    ("WAtoday", "https://www.watoday.com.au/rss/feed.xml",
     "en", "local_news", "city", "AU", "perth"),
    ("The West Australian", "https://thewest.com.au/rss",
     "en", "local_news", "city", "AU", "perth"),
    # ── Australia — National ───────────────────────────────
    ("ABC News Australia", "https://www.abc.net.au/news/feed/51120/rss.xml",
     "en", "national_news", "national", "AU", None),
    ("The Guardian Australia", "https://www.theguardian.com/australia-news/rss",
     "en", "national_news", "national", "AU", None),
    ("news.com.au", "https://www.news.com.au/content-feeds/latest-news-national/",
     "en", "national_news", "national", "AU", None),
    # ── India — Mumbai ──────────────────────────────────────
    ("Mumbai Mirror", "https://mumbaimirror.indiatimes.com/rssfeeds/1305925.cms",
     "en", "local_news", "city", "IN", "mumbai"),
    ("Mid-Day", "https://www.mid-day.com/rss/latest-news",
     "en", "local_news", "city", "IN", "mumbai"),
    # ── India — Delhi ───────────────────────────────────────
    ("Delhi Times", "https://timesofindia.indiatimes.com/rssfeeds/3908999.cms",
     "en", "local_news", "city", "IN", "delhi"),
    ("Hindustan Times Delhi", "https://www.hindustantimes.com/feeds/rss/delhi/rssfeed.xml",
     "en", "local_news", "city", "IN", "delhi"),
    # ── India — Bangalore ───────────────────────────────────
    ("Deccan Herald", "https://www.deccanherald.com/rss-feeds/bangalore",
     "en", "local_news", "city", "IN", "bangalore"),
    ("The Hindu Bangalore", "https://www.thehindu.com/news/cities/bangalore/?service=rss",
     "en", "local_news", "city", "IN", "bangalore"),
    # ── India — Chennai ─────────────────────────────────────
    ("The Hindu Chennai", "https://www.thehindu.com/news/cities/Chennai/?service=rss",
     "en", "local_news", "city", "IN", "chennai"),
    ("New Indian Express", "https://www.newindianexpress.com/rss/city/chennai.xml",
     "en", "local_news", "city", "IN", "chennai"),
    # ── India — Hyderabad ──────────────────────────────────
    ("Deccan Chronicle", "https://www.deccanchronicle.com/rss-feeds/hyderabad",
     "en", "local_news", "city", "IN", "hyderabad"),
    ("Hans India", "https://www.thehansindia.com/rss-feeds",
     "en", "local_news", "city", "IN", "hyderabad"),
    # ── India — National ────────────────────────────────────
    ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
     "en", "national_news", "national", "IN", None),
    ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories",
     "en", "national_news", "national", "IN", None),
    ("The Hindu", "https://www.thehindu.com/news/national/?service=rss",
     "en", "national_news", "national", "IN", None),
    ("Indian Express", "https://indianexpress.com/section/india/feed/",
     "en", "national_news", "national", "IN", None),
    ("Mint", "https://www.livemint.com/rss/news",
     "en", "business", "national", "IN", None),
    # ── International ─────────────────────────────────────────────
    ("Reuters", "https://feeds.reuters.com/reuters/topNews",
     "en", "national_news", "international", None, None),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml",
     "en", "national_news", "international", None, None),
    ("DW (Deutsche Welle)", "https://rss.dw.com/xml/rss-en-all",
     "en", "national_news", "international", None, None),
    ("Euronews", "https://www.euronews.com/rss",
     "en", "national_news", "international", None, None),
]


# ───────────────────────────────────────────────────────────────────
async def run_seed() -> None:
    print("▶ Ensuring location schema …")
    await ensure_location_schema()

    # ─ Countries ──────────────────────────────────────────────────
    print("▶ Seeding countries …")
    country_id_map: dict[str, int] = {}
    for c in COUNTRIES:
        cid = await upsert_country(c["name"], c["code"], c["flag"])
        country_id_map[c["code"]] = cid
        print(f"  {c['flag']} {c['name']} ({c['code']}) → id={cid}")

    # ─ Cities ───────────────────────────────────────────────────
    print("▶ Seeding cities …")
    city_id_map: dict[str, int] = {}
    for code, name, slug, lat, lon in CITIES:
        cid = await upsert_city(name, country_id_map[code], slug, lat, lon)
        city_id_map[slug] = cid
        print(f"  {name} ({slug}) → id={cid}")

    # ─ Sources + Coverage ───────────────────────────────────────
    print("▶ Seeding sources and coverage …")
    for (name, rss_url, lang, cat, cov_level, country_code, city_slug) in SOURCES:
        sid = await upsert_source(
            name=name,
            rss_url=rss_url,
            language=lang,
            category=cat,
        )
        country_id = country_id_map.get(country_code) if country_code else None
        city_id    = city_id_map.get(city_slug)    if city_slug    else None
        await upsert_coverage(sid, city_id, country_id, cov_level)
        print(f"  {name} → source_id={sid} [{cov_level}]")

    print("\n✅ Seed complete.")


if __name__ == "__main__":
    asyncio.run(run_seed())
