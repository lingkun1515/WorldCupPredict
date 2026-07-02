"""WorldCupPredict configuration."""
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("wcp")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
LOCAL_LLM_URL = os.environ.get("LOCAL_LLM_URL", "http://localhost:1234/v1")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3-vl-4b-instruct")
HTTP_PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:7897")
HTTPS_PROXY = os.environ.get("HTTPS_PROXY", "http://127.0.0.1:7897")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MATCHES_FILE = os.path.join(DATA_DIR, "matches.json")
PREDICTIONS_FILE = os.path.join(DATA_DIR, "predictions.json")
COMMENTATORS_FILE = os.path.join(DATA_DIR, "commentators.json")

LIVE_FETCH_MODE = os.environ.get("LIVE_FETCH", "auto")  # "espn", "wikipedia", "auto"
LIVE_FETCH_DAYS = int(os.environ.get("LIVE_FETCH_DAYS", "5"))
SCRAPER_TIMEOUT = 8
SCRAPER_HEADLESS = True
SCRAPER_MAX_CONCURRENT = 2

BETTING_SITES = [
    "https://www.oddschecker.com/football/world-cup-2026",
    "https://www.bet365.com",
]

NEWS_SOURCES = [
    {"name": "BBC Sport", "url": "https://www.bbc.com/sport/football/world-cup"},
    {"name": "ESPN FC", "url": "https://www.espn.com/soccer/league/_/name/fifa.world"},
    {"name": "The Guardian", "url": "https://www.theguardian.com/football/world-cup-2026"},
    {"name": "Sky Sports", "url": "https://www.skysports.com/world-cup"},
]
