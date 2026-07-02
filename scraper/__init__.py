"""Scraper: multi-source web scraping for World Cup match data."""
from scraper.models import MatchData, BettingOdds, NewsItem
from scraper.betting import scrape_betting_odds
from scraper.news import scrape_news_and_commentary
from scraper.live_fetcher import live_refresh_results, fetch_espn_scoreboard
