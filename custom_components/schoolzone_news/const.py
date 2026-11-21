"""Constants for the SchoolZone News integration."""

DOMAIN = "schoolzone_news"

BASE_URL = "https://schoolzone.epsb.ca"
LOGIN_PAGE = f"{BASE_URL}/cf/index.cfm"
LOGIN_POST = f"{BASE_URL}/cf/login.cfm"
NEWS_URL = f"{BASE_URL}/cf/news/loadNews.cfm"
NEWS_PAGE = f"{BASE_URL}/cf/news/index.cfm"

CONF_NEWS_TYPES = "news_types"
CONF_MORNING_TIME = "morning_time"
CONF_EVENING_TIME = "evening_time"

# newsType values used by SchoolZone -> friendly names
NEWS_TYPES: dict[str, str] = {
    "school": "School",
    "class": "Class",
    "division": "Division",
    "trustee": "Trustee",
    "schoolzone": "SchoolZone",
    "transportation": "Transportation",
}

DEFAULT_NEWS_TYPES = ["school"]
# Checks run at these local (Home Assistant time zone) times every day.
DEFAULT_MORNING_TIME = "07:00:00"
DEFAULT_EVENING_TIME = "17:00:00"

# If a scheduled check fails (network blip, SchoolZone down), retry this many
# times, this many minutes apart, before waiting for the next scheduled check.
RETRY_DELAY_MIN = 15
MAX_RETRIES = 2

EVENT_NEW_ANNOUNCEMENT = f"{DOMAIN}_new_announcement"

STORAGE_VERSION = 1
MAX_ITEMS_IN_ATTRIBUTES = 15
MAX_SEEN_IDS = 500


def store_key(entry_id: str) -> str:
    """Storage key holding seen ids and the last fetched announcements."""
    return f"{DOMAIN}.{entry_id}"

# Weekends: no check on Saturday, a single check on Sunday evening. Weekdays use
# the configurable morning and evening times.
SUNDAY_CHECK_TIME = "19:00:00"
