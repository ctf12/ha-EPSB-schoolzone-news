"""SchoolZone (Edmonton Public Schools) client and news parser.

Kept free of Home Assistant imports so the parser can be tested on its own.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup, NavigableString, Tag

from .const import BASE_URL, LOGIN_PAGE, LOGIN_POST, NEWS_PAGE, NEWS_URL

_LOGGER = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (HomeAssistant; schoolzone_news) "
        "AppleWebKit/537.36 (KHTML, like Gecko)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_POSTED_RE = re.compile(r"Posted on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})")


class SchoolZoneError(Exception):
    """Generic SchoolZone failure (network, unexpected page)."""


class SchoolZoneAuthError(SchoolZoneError):
    """Credentials rejected or session could not be established."""


@dataclass
class Attachment:
    name: str
    url: str


@dataclass
class Announcement:
    id: str
    title: str
    posted: str | None  # ISO date, e.g. "2026-11-02"
    pinned: bool
    is_new: bool
    text: str
    html: str
    links: list[dict[str, str]] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    image: str | None = None
    sort_key: int = 0

    def as_dict(self) -> dict:
        """Public representation (events, attributes)."""
        data = asdict(self)
        data.pop("sort_key", None)
        return data

    def to_storage(self) -> dict:
        """Full representation, including the sort key, for the on-disk cache."""
        return asdict(self)

    @classmethod
    def from_storage(cls, data: dict) -> Announcement:
        data = dict(data)
        data["attachments"] = [Attachment(**a) for a in data.get("attachments", [])]
        return cls(**data)


def looks_like_login_page(html: str) -> bool:
    """True if SchoolZone handed back its sign-in page instead of content."""
    return 'id="loginForm"' in html or "loginPassword" in html


def _html_to_text(node: Tag) -> str:
    """Flatten a body div to readable text, keeping line breaks."""
    parts: list[str] = []
    for el in node.descendants:
        if isinstance(el, NavigableString):
            parts.append(str(el))
        elif isinstance(el, Tag) and el.name in ("br", "p", "li", "div"):
            parts.append("\n")
    text = "".join(parts).replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    # collapse 3+ blank lines into one blank line
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out


def _parse_posted(text: str) -> str | None:
    m = _POSTED_RE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_news(html: str) -> list[Announcement]:
    """Parse the HTML fragment returned by loadNews.cfm."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[Announcement] = []

    for div in soup.select("div.news-item"):
        item_id = div.get("id") or ""
        classes = div.get("class") or []

        h3 = div.find("h3")
        is_new = False
        title = ""
        if h3:
            label = h3.find("label")
            if label and "new" in label.get_text(strip=True).lower():
                is_new = True
            for junk in h3.find_all(["label", "div"]):
                junk.extract()
            title = " ".join(h3.get_text(" ", strip=True).split())

        dateline = div.select_one("small.dateline")
        posted = _parse_posted(dateline.get_text(" ", strip=True)) if dateline else None

        # Body = first direct row after the dateline row that isn't the attachments row.
        rows = [r for r in div.find_all("div", class_="row", recursive=False)]
        body_col: Tag | None = None
        image: str | None = None
        for row in rows:
            if row.get("id") == "attachmentDiv":
                continue
            if row.find("h3") or row.select_one("small.dateline"):
                continue
            cols = row.find_all("div", recursive=False)
            if not cols:
                continue
            body_col = cols[0]
            img = row.find("img")
            if img and img.get("src"):
                image = urljoin(BASE_URL, img["src"])
            break

        text = _html_to_text(body_col) if body_col else ""
        body_html = body_col.decode_contents().strip() if body_col else ""
        links = []
        if body_col:
            for a in body_col.find_all("a", href=True):
                links.append(
                    {"text": a.get_text(" ", strip=True), "url": urljoin(BASE_URL, a["href"])}
                )

        attachments = []
        att = div.find(id="attachmentDiv")
        if att:
            for a in att.find_all("a", href=True):
                attachments.append(
                    Attachment(name=a.get_text(strip=True), url=urljoin(BASE_URL, a["href"]))
                )

        try:
            sort_key = int(div.get("data-time") or 0)
        except ValueError:
            sort_key = 0
        if posted:
            sort_key = date.fromisoformat(posted).toordinal()

        items.append(
            Announcement(
                id=str(item_id),
                title=title,
                posted=posted,
                pinned="pinned" in classes,
                is_new=is_new,
                text=text,
                html=body_html,
                links=links,
                attachments=attachments,
                image=image,
                sort_key=sort_key,
            )
        )

    if not items and "news-item" not in html and len(html.strip()) > 500:
        _LOGGER.warning(
            "SchoolZone returned a page with no recognizable announcements; "
            "the page layout may have changed"
        )

    # Newest first (pinned posts are listed first on the site regardless of date).
    # Same-day ties fall back to the post id, which increases over time.
    items.sort(key=lambda a: (a.sort_key, int(a.id) if a.id.isdigit() else 0), reverse=True)
    return items


class SchoolZoneClient:
    """Minimal session-based client."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._logged_in = False

    async def login(self) -> None:
        try:
            # Prime cookies (ColdFusion session) before posting the form.
            async with self._session.get(LOGIN_PAGE, headers=_HEADERS) as resp:
                await resp.text()
            data = {
                "userID": self._username,
                "loginPassword": self._password,
                "bSubmitForm": "1",
                "btnSignIn": "Sign in",
            }
            headers = {**_HEADERS, "Referer": LOGIN_PAGE, "Origin": BASE_URL}
            async with self._session.post(
                LOGIN_POST, data=data, headers=headers, allow_redirects=True
            ) as resp:
                html = await resp.text()
                if resp.status >= 500:
                    raise SchoolZoneError(f"Sign-in failed: HTTP {resp.status}")
        except aiohttp.ClientError as err:
            raise SchoolZoneError(f"Could not reach SchoolZone: {err}") from err

        if looks_like_login_page(html):
            self._logged_in = False
            raise SchoolZoneAuthError("SchoolZone rejected the username or password")
        self._logged_in = True

    async def _get_news_html(self, news_type: str) -> str:
        params = {"newsType": news_type, "showHistory": "false", "offset": "0"}
        headers = {
            **_HEADERS,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{NEWS_PAGE}?type={news_type}",
        }
        try:
            async with self._session.get(NEWS_URL, params=params, headers=headers) as resp:
                if resp.status in (401, 403):
                    raise SchoolZoneAuthError("Session expired")
                if resp.status != 200:
                    raise SchoolZoneError(f"News request failed: HTTP {resp.status}")
                return await resp.text()
        except aiohttp.ClientError as err:
            raise SchoolZoneError(f"Could not reach SchoolZone: {err}") from err

    async def fetch_news(self, news_type: str) -> list[Announcement]:
        """Fetch one news stream, signing in (or back in) as needed."""
        if not self._logged_in:
            await self.login()

        # An expired session shows up either as the sign-in page or as an HTTP
        # 401/403. Both mean "sign in again", not "the password is wrong".
        try:
            html = await self._get_news_html(news_type)
            expired = looks_like_login_page(html)
        except SchoolZoneAuthError:
            expired = True

        if expired:
            _LOGGER.debug("SchoolZone session expired; signing in again")
            self._logged_in = False
            await self.login()
            html = await self._get_news_html(news_type)
            if looks_like_login_page(html):
                raise SchoolZoneAuthError("Could not stay signed in to SchoolZone")

        return parse_news(html)
