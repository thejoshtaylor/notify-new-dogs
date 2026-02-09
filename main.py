"""Main entry point for the dog shelter notification service."""

import logging
import os
import sys
import time

import schedule
from dotenv import load_dotenv

from src.notifier import send_notification
from src.scraper import scrape_dogs
from src.storage import find_new_dogs, load_existing_dogs, save_dogs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def check_for_new_dogs():
    """Run a single check for new dogs at the shelter."""
    shelter_url = os.environ["SHELTER_URL"]
    webhook_url = os.environ["WEBHOOK_URL"]
    max_age_years = float(os.environ.get("MAX_AGE_YEARS", "5"))
    csv_path = os.environ.get("CSV_FILE_PATH", "data/dogs.csv")

    logger.info("Starting check for new dogs...")

    try:
        current_dogs = scrape_dogs(shelter_url)
    except Exception:
        logger.error("Failed to scrape shelter website", exc_info=True)
        return

    if not current_dogs:
        logger.warning("No dogs found on the shelter website")
        return

    known_dog_names = load_existing_dogs(csv_path)
    new_dogs = find_new_dogs(current_dogs, known_dog_names)

    # Save the full current list to CSV
    save_dogs(csv_path, current_dogs)

    # Filter new dogs by max age and send notifications
    for dog in new_dogs:
        if dog.age_years <= max_age_years:
            logger.info(
                "New dog meets age criteria: %s (%.1f years old)",
                dog.name,
                dog.age_years,
            )
            send_notification(webhook_url, dog)
        else:
            logger.info(
                "Skipping %s (%.1f years old, max is %.1f)",
                dog.name,
                dog.age_years,
                max_age_years,
            )

    logger.info("Check complete. Found %d new dogs total.", len(new_dogs))


def main():
    """Start the scheduled dog checker service."""
    load_dotenv()

    # Validate required environment variables
    required_vars = ["SHELTER_URL", "WEBHOOK_URL"]
    missing = [var for var in required_vars if not os.environ.get(var)]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    interval_hours = float(os.environ.get("CHECK_INTERVAL_HOURS", "6"))

    logger.info("Dog shelter notification service starting")
    logger.info("Check interval: %.1f hours", interval_hours)
    logger.info("Shelter URL: %s", os.environ["SHELTER_URL"])
    logger.info("Max age filter: %s years", os.environ.get("MAX_AGE_YEARS", "5"))

    # Run immediately on startup
    check_for_new_dogs()

    # Schedule recurring checks
    schedule.every(interval_hours).hours.do(check_for_new_dogs)

    logger.info("Scheduler started. Next run in %.1f hours.", interval_hours)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
