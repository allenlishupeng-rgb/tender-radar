from pathlib import Path
import os
import time

# Business dates (publish windows, days left before the deadline) are Beijing
# calendar days. Cloud hosts usually run in UTC, where date.today() lags Beijing
# by one day between 00:00 and 08:00. A POSIX TZ string needs no tzdata package;
# mainland China has no daylight saving time.
RADAR_TIMEZONE = os.getenv("RADAR_TIMEZONE") or "CST-8"


def apply_radar_timezone(value: str = RADAR_TIMEZONE) -> None:
    if not hasattr(time, "tzset"):  # Windows: keep the machine's local zone.
        return
    os.environ["TZ"] = value
    time.tzset()


apply_radar_timezone()

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("RADAR_DATA_DIR") or ROOT_DIR / "data")
EXPORT_DIR = Path(os.getenv("RADAR_EXPORT_DIR") or ROOT_DIR / "exports")
LOG_DIR = Path(os.getenv("RADAR_LOG_DIR") or ROOT_DIR / "logs")
DB_PATH = DATA_DIR / "tender_radar.db"
KEYWORDS_PATH = ROOT_DIR / "config" / "keywords.yaml"
SOURCES_PATH = ROOT_DIR / "config" / "sources.yaml"
ENTERPRISE_COMPANIES_PATH = ROOT_DIR / "config" / "enterprise_companies.yaml"

REQUEST_TIMEOUT = 12
REQUEST_INTERVAL_SECONDS = 2
USER_AGENT = (
    "ExhibitionTenderRadar/0.1 "
    "(local MVP; public pages only; contact: manual verification)"
)
