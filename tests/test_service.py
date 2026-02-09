"""Tests for the dog shelter notification service."""

import csv
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.notifier import send_notification
from src.scraper import Dog, parse_age, scrape_dogs
from src.storage import find_new_dogs, load_existing_dogs, save_dogs


# --- parse_age tests ---


class TestParseAge:
    def test_years_only(self):
        assert parse_age("2 years") == 2.0

    def test_year_singular(self):
        assert parse_age("1 year") == 1.0

    def test_months_only(self):
        assert parse_age("6 months") == pytest.approx(0.5)

    def test_years_and_months(self):
        assert parse_age("1 year 6 months") == pytest.approx(1.5)

    def test_abbreviated_years(self):
        assert parse_age("3 yrs") == 3.0

    def test_abbreviated_months(self):
        assert parse_age("6 mos") == pytest.approx(0.5)

    def test_no_space(self):
        assert parse_age("2yr") == 2.0

    def test_empty_string(self):
        assert parse_age("") == 0.0

    def test_none(self):
        assert parse_age(None) == 0.0

    def test_unparseable(self):
        assert parse_age("unknown") == 0.0

    def test_case_insensitive(self):
        assert parse_age("2 Years") == 2.0

    def test_months_no_space(self):
        assert parse_age("6mo") == pytest.approx(0.5)


# --- Dog model tests ---


class TestDog:
    def test_to_dict(self):
        dog = Dog(
            name="Buddy",
            breed="Labrador",
            age_years=3.0,
            sex="Male",
            size="Large",
            url="https://shelter.com/dogs/buddy",
            image_url="https://shelter.com/images/buddy.jpg",
        )
        d = dog.to_dict()
        assert d["name"] == "Buddy"
        assert d["breed"] == "Labrador"
        assert d["age_years"] == 3.0
        assert d["sex"] == "Male"
        assert d["size"] == "Large"
        assert d["url"] == "https://shelter.com/dogs/buddy"
        assert d["image_url"] == "https://shelter.com/images/buddy.jpg"


# --- Storage tests ---


class TestStorage:
    def test_save_and_load_dogs(self):
        dogs = [
            Dog("Buddy", "Labrador", 3.0, "Male", "Large", "http://x.com/1", "http://x.com/1.jpg"),
            Dog("Luna", "Poodle", 1.5, "Female", "Medium", "http://x.com/2", "http://x.com/2.jpg"),
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            save_dogs(csv_path, dogs)

            # Verify the CSV content
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 2
            assert rows[0]["name"] == "Buddy"
            assert rows[1]["name"] == "Luna"

            # Load and verify known names
            known = load_existing_dogs(csv_path)
            assert known == {"Buddy", "Luna"}
        finally:
            os.unlink(csv_path)

    def test_load_nonexistent_file(self):
        known = load_existing_dogs("/tmp/nonexistent_dogs_test.csv")
        assert known == set()

    def test_find_new_dogs(self):
        dogs = [
            Dog("Buddy", "Labrador", 3.0, "Male", "Large", "", ""),
            Dog("Luna", "Poodle", 1.5, "Female", "Medium", "", ""),
            Dog("Max", "Beagle", 2.0, "Male", "Medium", "", ""),
        ]
        known = {"Buddy"}

        new_dogs = find_new_dogs(dogs, known)
        assert len(new_dogs) == 2
        names = {d.name for d in new_dogs}
        assert names == {"Luna", "Max"}

    def test_find_new_dogs_none_new(self):
        dogs = [
            Dog("Buddy", "Labrador", 3.0, "Male", "Large", "", ""),
        ]
        known = {"Buddy"}

        new_dogs = find_new_dogs(dogs, known)
        assert len(new_dogs) == 0

    def test_find_new_dogs_all_new(self):
        dogs = [
            Dog("Buddy", "Labrador", 3.0, "Male", "Large", "", ""),
        ]
        known = set()

        new_dogs = find_new_dogs(dogs, known)
        assert len(new_dogs) == 1


# --- Notifier tests ---


class TestNotifier:
    @patch("src.notifier.requests.post")
    def test_send_notification_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        dog = Dog("Buddy", "Labrador", 3.0, "Male", "Large",
                   "http://shelter.com/buddy", "http://shelter.com/buddy.jpg")

        result = send_notification("https://hooks.example.com/webhook", dog)
        assert result is True

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["name"] == "Buddy"
        assert payload["breed"] == "Labrador"
        assert payload["age_years"] == 3.0
        assert payload["image_url"] == "http://shelter.com/buddy.jpg"

    @patch("src.notifier.requests.post")
    def test_send_notification_failure(self, mock_post):
        import requests
        mock_post.side_effect = requests.RequestException("Connection failed")

        dog = Dog("Buddy", "Labrador", 3.0, "Male", "Large", "", "")
        result = send_notification("https://hooks.example.com/webhook", dog)
        assert result is False


# --- Scraper tests ---


class TestScraper:
    @patch("src.scraper.requests.get")
    def test_scrape_dogs_with_cards(self, mock_get):
        html = """
        <html>
        <body>
            <div class="pet-list">
                <div class="pet-card">
                    <h3 class="name">Buddy</h3>
                    <img src="https://shelter.com/buddy.jpg" />
                    <a href="/dogs/buddy">View</a>
                    <span class="breed">Labrador Retriever</span>
                    <span class="age">2 years</span>
                    <span class="sex">Male</span>
                    <span class="size">Large</span>
                </div>
                <div class="pet-card">
                    <h3 class="name">Luna</h3>
                    <img src="https://shelter.com/luna.jpg" />
                    <a href="/dogs/luna">View</a>
                    <span class="breed">Poodle Mix</span>
                    <span class="age">6 months</span>
                    <span class="sex">Female</span>
                    <span class="size">Medium</span>
                </div>
            </div>
        </body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        dogs = scrape_dogs("https://shelter.com/available-dogs")

        assert len(dogs) == 2
        assert dogs[0].name == "Buddy"
        assert dogs[0].breed == "Labrador Retriever"
        assert dogs[0].age_years == 2.0
        assert dogs[0].sex == "Male"
        assert dogs[0].image_url == "https://shelter.com/buddy.jpg"
        assert dogs[1].name == "Luna"
        assert dogs[1].age_years == pytest.approx(0.5)

    @patch("src.scraper.requests.get")
    def test_scrape_dogs_empty_page(self, mock_get):
        mock_response = MagicMock()
        mock_response.text = "<html><body><p>No dogs available</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        dogs = scrape_dogs("https://shelter.com/available-dogs")
        assert len(dogs) == 0


# --- Integration test for check_for_new_dogs ---


class TestCheckForNewDogs:
    @patch("src.notifier.requests.post")
    @patch("src.scraper.requests.get")
    def test_check_for_new_dogs_sends_webhook(self, mock_get, mock_post):
        from main import check_for_new_dogs

        html = """
        <html><body>
        <div class="pet-card">
            <h3 class="name">Rex</h3>
            <img src="https://shelter.com/rex.jpg" />
            <a href="/dogs/rex">View</a>
            <span class="breed">German Shepherd</span>
            <span class="age">2 years</span>
            <span class="sex">Male</span>
            <span class="size">Large</span>
        </div>
        </body></html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        mock_post_response = MagicMock()
        mock_post_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_post_response

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            os.environ["SHELTER_URL"] = "https://shelter.com/dogs"
            os.environ["WEBHOOK_URL"] = "https://hooks.example.com/webhook"
            os.environ["MAX_AGE_YEARS"] = "5"
            os.environ["CSV_FILE_PATH"] = csv_path

            check_for_new_dogs()

            # Webhook should have been called for the new dog
            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs["json"]
            assert payload["name"] == "Rex"
            assert payload["image_url"] == "https://shelter.com/rex.jpg"
        finally:
            os.unlink(csv_path)
            for var in ["SHELTER_URL", "WEBHOOK_URL", "MAX_AGE_YEARS", "CSV_FILE_PATH"]:
                os.environ.pop(var, None)

    @patch("src.notifier.requests.post")
    @patch("src.scraper.requests.get")
    def test_age_filter_skips_old_dogs(self, mock_get, mock_post):
        from main import check_for_new_dogs

        html = """
        <html><body>
        <div class="pet-card">
            <h3 class="name">OldBoy</h3>
            <img src="https://shelter.com/oldboy.jpg" />
            <a href="/dogs/oldboy">View</a>
            <span class="breed">Bulldog</span>
            <span class="age">10 years</span>
            <span class="sex">Male</span>
            <span class="size">Medium</span>
        </div>
        </body></html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        mock_post_response = MagicMock()
        mock_post_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_post_response

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            os.environ["SHELTER_URL"] = "https://shelter.com/dogs"
            os.environ["WEBHOOK_URL"] = "https://hooks.example.com/webhook"
            os.environ["MAX_AGE_YEARS"] = "5"
            os.environ["CSV_FILE_PATH"] = csv_path

            check_for_new_dogs()

            # Webhook should NOT have been called because the dog is too old
            mock_post.assert_not_called()
        finally:
            os.unlink(csv_path)
            for var in ["SHELTER_URL", "WEBHOOK_URL", "MAX_AGE_YEARS", "CSV_FILE_PATH"]:
                os.environ.pop(var, None)
