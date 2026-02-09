"""CSV storage module for tracking dogs across runs."""

import csv
import logging
import os

logger = logging.getLogger(__name__)

FIELDNAMES = ["name", "breed", "age_years", "sex", "size", "url", "image_url"]


def load_existing_dogs(csv_path):
    """Load previously saved dogs from the CSV file.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        A set of dog names that have been seen before.
    """
    known_dogs = set()

    if not os.path.exists(csv_path):
        logger.info("No existing CSV file found at %s", csv_path)
        return known_dogs

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            known_dogs.add(row["name"])

    logger.info("Loaded %d known dogs from CSV", len(known_dogs))
    return known_dogs


def save_dogs(csv_path, dogs):
    """Save the current list of dogs to the CSV file.

    Args:
        csv_path: Path to the CSV file.
        dogs: A list of Dog objects.
    """
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for dog in dogs:
            writer.writerow(dog.to_dict())

    logger.info("Saved %d dogs to %s", len(dogs), csv_path)


def find_new_dogs(current_dogs, known_dog_names):
    """Find dogs that are new (not in the known set).

    Args:
        current_dogs: A list of Dog objects from the latest scrape.
        known_dog_names: A set of dog names from previous runs.

    Returns:
        A list of Dog objects that are new.
    """
    new_dogs = [dog for dog in current_dogs if dog.name not in known_dog_names]
    logger.info("Found %d new dogs", len(new_dogs))
    return new_dogs
