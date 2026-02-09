"""Scraper module for fetching available dogs from a shelter website."""

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class Dog:
    """Represents an available dog from the shelter."""

    name: str
    breed: str
    age_years: float
    sex: str
    size: str
    url: str
    image_url: str

    def to_dict(self):
        """Convert to dictionary for CSV/JSON serialization."""
        return {
            "name": self.name,
            "breed": self.breed,
            "age_years": self.age_years,
            "sex": self.sex,
            "size": self.size,
            "url": self.url,
            "image_url": self.image_url,
        }


def parse_age(age_text):
    """Parse age text into a float representing years.

    Handles formats like:
        '2 years', '3 Years', '6 months', '1 year 3 months',
        '2 yrs', '6 mos', '2yr', '6mo'

    Returns the age in years as a float, or 0.0 if unparseable.
    """
    if not age_text:
        return 0.0

    age_text = age_text.strip().lower()
    total_years = 0.0

    year_match = re.search(r"(\d+)\s*(?:year|yr)s?", age_text)
    if year_match:
        total_years += int(year_match.group(1))

    month_match = re.search(r"(\d+)\s*(?:month|mo)s?", age_text)
    if month_match:
        total_years += int(month_match.group(1)) / 12.0

    return total_years


def scrape_dogs(shelter_url):
    """Scrape the shelter website and return a list of Dog objects.

    This scraper looks for common HTML patterns used by shelter websites.
    It searches for dog listing cards/containers and extracts name, breed,
    age, sex, size, detail URL, and image URL from each.

    Args:
        shelter_url: The URL of the shelter's available dogs page.

    Returns:
        A list of Dog objects.
    """
    logger.info("Fetching dogs from %s", shelter_url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(shelter_url, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    dogs = []

    # Strategy: look for common shelter website card patterns
    # Many shelter sites use grid/list layouts with cards for each animal
    cards = _find_animal_cards(soup)

    for card in cards:
        try:
            dog = _parse_card(card, shelter_url)
            if dog:
                dogs.append(dog)
        except Exception:
            logger.warning("Failed to parse a dog card, skipping", exc_info=True)

    logger.info("Found %d dogs", len(dogs))
    return dogs


def _find_animal_cards(soup):
    """Find animal listing cards in the page using common CSS patterns."""
    # Try common class/id patterns used by shelter websites
    selectors = [
        "[class*='animal-card']",
        "[class*='pet-card']",
        "[class*='dog-card']",
        "[class*='animal-list'] [class*='item']",
        "[class*='pet-list'] [class*='item']",
        "[class*='grid'] [class*='card']",
        "[class*='adoptable'] [class*='card']",
        "[class*='available'] [class*='card']",
        ".dog-listing",
        ".pet-listing",
        ".animal-listing",
    ]

    for selector in selectors:
        cards = soup.select(selector)
        if cards:
            logger.debug("Found %d cards with selector: %s", len(cards), selector)
            return cards

    # Fallback: look for repeating structures with images and links
    # that look like animal listings
    cards = soup.find_all("div", class_=re.compile(r"card|item|listing", re.I))
    if cards:
        logger.debug("Found %d cards with fallback div search", len(cards))
        return cards

    logger.warning("No animal cards found on page")
    return []


def _parse_card(card, base_url):
    """Parse a single animal card element into a Dog object."""
    # Extract name
    name_el = card.find(["h2", "h3", "h4", "a"], class_=re.compile(r"name|title", re.I))
    if not name_el:
        name_el = card.find(["h2", "h3", "h4"])
    name = name_el.get_text(strip=True) if name_el else None

    if not name:
        return None

    # Extract link URL
    link_el = card.find("a", href=True)
    url = ""
    if link_el:
        href = link_el["href"]
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            from urllib.parse import urljoin

            url = urljoin(base_url, href)
        else:
            url = href

    # Extract image URL
    img_el = card.find("img", src=True)
    image_url = ""
    if img_el:
        src = img_el.get("src", "") or img_el.get("data-src", "")
        if src.startswith("http"):
            image_url = src
        elif src.startswith("/"):
            from urllib.parse import urljoin

            image_url = urljoin(base_url, src)
        else:
            image_url = src

    # Extract breed, age, sex, size from text content
    text_content = card.get_text(separator="|", strip=True)
    breed = _extract_field(card, text_content, ["breed"])
    age_text = _extract_field(card, text_content, ["age"])
    sex = _extract_field(card, text_content, ["sex", "gender"])
    size = _extract_field(card, text_content, ["size"])

    age_years = parse_age(age_text)

    return Dog(
        name=name,
        breed=breed,
        age_years=age_years,
        sex=sex,
        size=size,
        url=url,
        image_url=image_url,
    )


def _extract_field(card, text_content, field_names):
    """Try to extract a field value from a card element."""
    # Look for labeled elements
    for field_name in field_names:
        el = card.find(
            class_=re.compile(rf"{field_name}", re.I)
        )
        if el:
            return el.get_text(strip=True)

        # Look for dt/dd pairs
        dt = card.find("dt", string=re.compile(rf"{field_name}", re.I))
        if dt:
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(strip=True)

        # Look for label/value spans
        label = card.find(
            string=re.compile(rf"{field_name}\s*:", re.I)
        )
        if label:
            parent = label.parent if hasattr(label, "parent") else None
            if parent:
                value = parent.get_text(strip=True)
                # Remove the label part
                value = re.sub(rf".*{field_name}\s*:\s*", "", value, flags=re.I)
                return value.strip()

    return ""
