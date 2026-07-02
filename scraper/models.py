"""Data models for scraped content."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class BettingOdds:
    source: str
    home_win: float
    draw: float
    away_win: float
    over_under: Optional[float] = None
    handicap: Optional[float] = None

    @property
    def implied_home_prob(self) -> float:
        total = 1 / self.home_win + 1 / self.draw + 1 / self.away_win
        return (1 / self.home_win) / total

    @property
    def implied_draw_prob(self) -> float:
        total = 1 / self.home_win + 1 / self.draw + 1 / self.away_win
        return (1 / self.draw) / total

    @property
    def implied_away_prob(self) -> float:
        total = 1 / self.home_win + 1 / self.draw + 1 / self.away_win
        return (1 / self.away_win) / total


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    summary: str = ""
    commentator: str = ""
    prediction: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class MatchData:
    match_id: str
    home_team: str
    away_team: str
    kickoff: str
    venue: str
    stage: str
    odds: list = field(default_factory=list)
    news: list = field(default_factory=list)


@dataclass
class ScrapedBundle:
    matches: list
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
