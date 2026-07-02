"""Shared data constants used by multiple modules."""
import json
import os
from config import DATA_DIR

COUNTRY_FLAGS = {
    "Argentina": "🇦🇷", "Japan": "🇯🇵", "Germany": "🇩🇪", "Senegal": "🇸🇳",
    "France": "🇫🇷", "South Korea": "🇰🇷", "Brazil": "🇧🇷", "Ghana": "🇬🇭",
    "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Serbia": "🇷🇸", "Spain": "🇪🇸", "Ecuador": "🇪🇨",
    "Portugal": "🇵🇹", "Mexico": "🇲🇽", "Netherlands": "🇳🇱", "Colombia": "🇨🇴",
    "Italy": "🇮🇹", "Uruguay": "🇺🇾", "Croatia": "🇭🇷", "Morocco": "🇲🇦",
    "USA": "🇺🇸", "Canada": "🇨🇦", "Belgium": "🇧🇪", "Denmark": "🇩🇰",
    "Switzerland": "🇨🇭", "Sweden": "🇸🇪", "Poland": "🇵🇱", "Austria": "🇦🇹",
    "Egypt": "🇪🇬", "Nigeria": "🇳🇬", "Cameroon": "🇨🇲", "Ivory Coast": "🇨🇮",
    "Australia": "🇦🇺", "Iran": "🇮🇷", "Saudi Arabia": "🇸🇦", "Qatar": "🇶🇦",
    "Chile": "🇨🇱", "Peru": "🇵🇪", "Paraguay": "🇵🇾", "New Zealand": "🇳🇿",
    "Panama": "🇵🇦", "Jamaica": "🇯🇲", "UAE": "🇦🇪", "China": "🇨🇳",
    "South Africa": "🇿🇦", "Algeria": "🇩🇿", "Tunisia": "🇹🇳",
    "Bosnia and Herzegovina": "🇧🇦",
    "Cape Verde": "🇨🇻",
    "DR Congo": "🇨🇩",
    "Norway": "🇳🇴",
    "United States": "🇺🇸",
    "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "Turkey": "🇹🇷",
    "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "Czech Republic": "🇨🇿",
}


def load_cn_names(data_dir=None):
    """Load Chinese team name mappings from JSON."""
    if data_dir is None:
        data_dir = DATA_DIR
    path = os.path.join(data_dir, "team_names_cn.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)
