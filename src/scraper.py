"""Scraper module for fetching available dogs from a shelter website."""

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

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


def _resolve_url(href, base_url):
    """Resolve a relative or absolute URL against a base URL."""
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(base_url, href)


def scrape_dogs(shelter_url):
    """Scrape the shelter website and return a list of Dog objects.

    Supports multiple shelter website formats:
    - PetHarbor Shelter Portal (Bootstrap card layout with labeled fields)
    - PetHarbor classic (ResultsTable with tr/td rows)
    - Generic shelter sites with card-based layouts

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

    # Try PetHarbor Shelter Portal format first
    dogs = _try_petharbor_portal(soup, shelter_url)
    if dogs:
        return dogs

    # Try PetHarbor classic ResultsTable format
    dogs = _try_petharbor_classic(soup, shelter_url)
    if dogs:
        return dogs

    # Fall back to generic card-based scraping
    dogs = []
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


def _try_petharbor_portal(soup, base_url):
    """Try to parse a PetHarbor Shelter Portal page.

    PetHarbor Shelter Portal sites use Bootstrap cards with labeled fields
    like 'Breed:', 'Age:', 'Sex:' etc. Animal names follow the format
    'NAME (ID)' e.g. 'OSCAR (A170391)'.
    """
    # Detect PetHarbor Shelter Portal by looking for its characteristic
    # JavaScript function or form action
    is_petharbor = bool(
        soup.find(string=re.compile(r"AdoptableAnimals|PetHarborShelter", re.I))
        or soup.find("form", action=re.compile(r"PetHarborShelter", re.I))
    )

    if not is_petharbor:
        return None

    logger.info("Detected PetHarbor Shelter Portal format")

    # PetHarbor portal renders animal cards inside Bootstrap card divs.
    # Each card contains an image and labeled text fields.
    cards = soup.select(".card")
    if not cards:
        cards = soup.find_all("div", class_=re.compile(r"card", re.I))

    dogs = []
    for card in cards:
        try:
            dog = _parse_petharbor_card(card, base_url)
            if dog:
                dogs.append(dog)
        except Exception:
            logger.warning("Failed to parse PetHarbor card, skipping", exc_info=True)

    logger.info("Found %d dogs (PetHarbor Portal)", len(dogs))
    return dogs if dogs else None


def _parse_petharbor_card(card, base_url):
    """Parse a single PetHarbor Shelter Portal animal card."""
    # Extract name - PetHarbor uses headings or bold text with format
    # "NAME (ID)" e.g. "OSCAR (A170391)"
    name = _extract_petharbor_name(card)
    if not name:
        return None

    # Extract image URL
    image_url = ""
    img_el = card.find("img")
    if img_el:
        src = img_el.get("src", "") or img_el.get("data-src", "")
        image_url = _resolve_url(src, base_url)

    # Extract link URL
    url = ""
    link_el = card.find("a", href=True)
    if link_el:
        url = _resolve_url(link_el["href"], base_url)

    # Extract labeled fields from the card text
    breed = _extract_labeled_value(card, r"breed")
    age_text = _extract_labeled_value(card, r"age")
    sex = _extract_labeled_value(card, r"sex|gender")
    size = _extract_labeled_value(card, r"size")

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


def _extract_petharbor_name(card):
    """Extract the animal name from a PetHarbor card.

    Handles formats like 'OSCAR (A170391)' by stripping the ID portion.
    Also looks for headings, card-title elements, and bold text.
    """
    # Try heading elements and card-title class
    for selector in ["h1", "h2", "h3", "h4", "h5", ".card-title"]:
        el = card.select_one(selector)
        if el:
            raw = el.get_text(strip=True)
            if raw:
                return _clean_petharbor_name(raw)

    # Try bold/strong elements
    for el in card.find_all(["b", "strong"]):
        raw = el.get_text(strip=True)
        # Skip labels like "Breed:", "Age:", etc.
        if raw and not re.match(r"^(breed|age|sex|gender|size|weight|color)\s*:", raw, re.I):
            return _clean_petharbor_name(raw)

    return None


def _clean_petharbor_name(raw_name):
    """Clean a PetHarbor-style name by removing the ID portion.

    'OSCAR (A170391)' -> 'OSCAR'
    'Buddy' -> 'Buddy'
    """
    # Strip parenthesized ID like (A170391)
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", raw_name).strip()
    return cleaned if cleaned else None


def _extract_labeled_value(card, label_pattern):
    """Extract a value from a labeled field in a card.

    Looks for patterns like:
    - <b>Breed:</b> Labrador
    - <strong>Age:</strong> 2 years
    - <span class="label">Breed:</span> <span>Labrador</span>
    - <dt>Breed</dt><dd>Labrador</dd>
    - Breed: Labrador (in plain text)
    - Elements with matching class names
    """
    # Look for elements with a matching class name
    el = card.find(class_=re.compile(label_pattern, re.I))
    if el:
        text = el.get_text(strip=True)
        # If the element text contains the label, strip it
        cleaned = re.sub(rf".*{label_pattern}\s*:\s*", "", text, flags=re.I)
        if cleaned and cleaned != text:
            return cleaned.strip()
        # If no label in text, it's likely a value-only element
        return text

    # Look for dt/dd pairs
    dt = card.find("dt", string=re.compile(label_pattern, re.I))
    if dt:
        dd = dt.find_next_sibling("dd")
        if dd:
            return dd.get_text(strip=True)

    # Look for bold/strong labels followed by text
    for tag in card.find_all(["b", "strong", "label"]):
        tag_text = tag.get_text(strip=True)
        if re.search(rf"{label_pattern}\s*:?\s*$", tag_text, re.I):
            # Get the next sibling text or element
            next_node = tag.next_sibling
            if next_node:
                value = next_node.string if hasattr(next_node, "string") and next_node.string else str(next_node)
                value = value.strip().lstrip(":").strip()
                if value:
                    return value
            # Try next sibling element
            next_el = tag.find_next_sibling()
            if next_el:
                return next_el.get_text(strip=True)

    # Look for "Label: Value" in text strings
    for text_node in card.find_all(string=re.compile(rf"{label_pattern}\s*:", re.I)):
        parent = text_node.parent if hasattr(text_node, "parent") else None
        if parent:
            full_text = parent.get_text(strip=True)
            match = re.search(rf"{label_pattern}\s*:\s*(.+)", full_text, re.I)
            if match:
                return match.group(1).strip()

    return ""


def _try_petharbor_classic(soup, base_url):
    """Try to parse a classic PetHarbor ResultsTable page.

    Classic PetHarbor uses a table with class 'ResultsTable' where each row
    contains columns for name, gender, color, breed, age, etc.
    """
    table = soup.find("table", class_="ResultsTable")
    if not table:
        return None

    logger.info("Detected PetHarbor classic ResultsTable format")

    rows = table.find_all("tr")
    dogs = []

    for row in rows[1:]:  # Skip header row
        tds = row.find_all("td")
        if len(tds) < 6:
            continue

        try:
            # Extract detail link
            link = tds[0].find("a", href=True)
            url = _resolve_url(link["href"], base_url) if link else ""

            raw_name = tds[1].get_text(strip=True)
            name = _clean_petharbor_name(raw_name)
            if not name:
                continue

            sex = tds[2].get_text(strip=True)
            breed = tds[4].get_text(strip=True)
            age_text = tds[5].get_text(strip=True)
            age_years = parse_age(age_text)

            dogs.append(Dog(
                name=name,
                breed=breed,
                age_years=age_years,
                sex=sex,
                size="",
                url=url,
                image_url="",
            ))
        except Exception:
            logger.warning("Failed to parse ResultsTable row, skipping", exc_info=True)

    logger.info("Found %d dogs (PetHarbor Classic)", len(dogs))
    return dogs if dogs else None


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
    url = _resolve_url(link_el["href"], base_url) if link_el else ""

    # Extract image URL
    img_el = card.find("img", src=True)
    image_url = ""
    if img_el:
        src = img_el.get("src", "") or img_el.get("data-src", "")
        image_url = _resolve_url(src, base_url)

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
    for field_name in field_names:
        # Look for labeled elements
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
