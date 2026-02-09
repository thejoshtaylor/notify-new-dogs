"""Webhook notification module for sending alerts about new dogs."""

import logging

import requests

logger = logging.getLogger(__name__)


def send_notification(webhook_url, dog):
    """Send a webhook notification about a new dog.

    Args:
        webhook_url: The URL to send the POST request to.
        dog: A Dog object with details about the new dog.

    Returns:
        True if the notification was sent successfully, False otherwise.
    """
    payload = {
        "name": dog.name,
        "breed": dog.breed,
        "age_years": dog.age_years,
        "sex": dog.sex,
        "size": dog.size,
        "url": dog.url,
        "image_url": dog.image_url,
    }

    logger.info("Sending notification for new dog: %s", dog.name)

    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        logger.info("Notification sent successfully for %s", dog.name)
        return True
    except requests.RequestException:
        logger.error("Failed to send notification for %s", dog.name, exc_info=True)
        return False
