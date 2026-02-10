"""Tests for the dog shelter notification service."""

import csv
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.notifier import send_notification
from src.scraper import Dog, _clean_petharbor_name, parse_age, scrape_dogs
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

    def test_weeks_format(self):
        assert parse_age("16 weeks") == pytest.approx(16.0 / 52.0)

    def test_weeks_old_format(self):
        assert parse_age("16 weeks old") == pytest.approx(16.0 / 52.0)

    def test_year_old_suffix(self):
        assert parse_age("1 year old") == 1.0

    def test_years_old_suffix(self):
        assert parse_age("5 years old") == 5.0

    def test_year_months_old_suffix(self):
        assert parse_age("1 year, 4 months old") == pytest.approx(1 + 4/12.0)


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


# --- PetHarbor name cleaning tests ---


class TestCleanPetharborName:
    def test_name_with_id(self):
        assert _clean_petharbor_name("OSCAR (A170391)") == "OSCAR"

    def test_name_without_id(self):
        assert _clean_petharbor_name("Buddy") == "Buddy"

    def test_name_with_spaces_and_id(self):
        assert _clean_petharbor_name("LADY BUG (A170500)") == "LADY BUG"

    def test_empty_string(self):
        assert _clean_petharbor_name("") is None

    def test_only_parenthesized(self):
        assert _clean_petharbor_name("(A170391)") is None


# --- PetHarbor Portal scraper tests ---


class TestPetHarborPortal:
    @patch("src.scraper.requests.get")
    def test_scrape_petharbor_portal_cards(self, mock_get):
        """Test scraping a PetHarbor Shelter Portal page with animal cards."""
        html = """
        <html>
        <body>
        <div class="container">
          <nav class="navbar navbar-expand-lg navbarCSS">
            <div class="navHeaderText"></div>
          </nav>
          <form action="/PetHarborShelter/GetAnimalBySearchInput" method="post">
            <input name="SearchText" type="search" />
          </form>
          <script>AdoptableAnimals('WestSlopeShelterAdoptablePets')</script>

          <div class="row">
            <div class="col-lg-4 col-md-6">
              <div class="card">
                <img src="https://shelter.com/photos/oscar.jpg" class="card-img-top" />
                <div class="card-body">
                  <h5 class="card-title">OSCAR (A170391)</h5>
                  <p><b>Breed:</b> Pit Bull</p>
                  <p><b>Age:</b> 2 years</p>
                  <p><b>Sex:</b> Male</p>
                  <p><b>Size:</b> Large</p>
                  <a href="/PetHarborShelter/Detail/A170391">More Info</a>
                </div>
              </div>
            </div>
            <div class="col-lg-4 col-md-6">
              <div class="card">
                <img src="https://shelter.com/photos/daisy.jpg" class="card-img-top" />
                <div class="card-body">
                  <h5 class="card-title">DAISY (A170450)</h5>
                  <p><b>Breed:</b> Labrador Retriever</p>
                  <p><b>Age:</b> 6 months</p>
                  <p><b>Sex:</b> Female</p>
                  <p><b>Size:</b> Medium</p>
                  <a href="/PetHarborShelter/Detail/A170450">More Info</a>
                </div>
              </div>
            </div>
            <div class="col-lg-4 col-md-6">
              <div class="card">
                <img src="https://shelter.com/photos/rex.jpg" class="card-img-top" />
                <div class="card-body">
                  <h5 class="card-title">REX (A170500)</h5>
                  <p><b>Breed:</b> German Shepherd</p>
                  <p><b>Age:</b> 8 years</p>
                  <p><b>Sex:</b> Male</p>
                  <p><b>Size:</b> Large</p>
                  <a href="/PetHarborShelter/Detail/A170500">More Info</a>
                </div>
              </div>
            </div>
          </div>
        </div>
        </body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        dogs = scrape_dogs("https://shelter.petharbor.com/available-dogs")

        assert len(dogs) == 3

        # First dog: OSCAR
        assert dogs[0].name == "OSCAR"
        assert dogs[0].breed == "Pit Bull"
        assert dogs[0].age_years == 2.0
        assert dogs[0].sex == "Male"
        assert dogs[0].size == "Large"
        assert dogs[0].image_url == "https://shelter.com/photos/oscar.jpg"
        assert "/PetHarborShelter/Detail/A170391" in dogs[0].url

        # Second dog: DAISY
        assert dogs[1].name == "DAISY"
        assert dogs[1].breed == "Labrador Retriever"
        assert dogs[1].age_years == pytest.approx(0.5)
        assert dogs[1].sex == "Female"

        # Third dog: REX
        assert dogs[2].name == "REX"
        assert dogs[2].age_years == 8.0

    @patch("src.scraper.requests.get")
    def test_scrape_petharbor_classic_table(self, mock_get):
        """Test scraping a classic PetHarbor ResultsTable page."""
        html = """
        <html>
        <body>
        <table class="ResultsTable" align="center" border="0">
          <tr><th>Photo</th><th>Name</th><th>Sex</th><th>Color</th><th>Breed</th><th>Age</th></tr>
          <tr>
            <td><a href="/pet.asp?uession=GRND.A170391">Photo</a></td>
            <td>OSCAR (A170391)</td>
            <td>Male</td>
            <td>Brown</td>
            <td>Pit Bull</td>
            <td>2 years</td>
          </tr>
          <tr>
            <td><a href="/pet.asp?uession=GRND.A170450">Photo</a></td>
            <td>DAISY (A170450)</td>
            <td>Female</td>
            <td>Yellow</td>
            <td>Labrador</td>
            <td>6 months</td>
          </tr>
        </table>
        </body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        dogs = scrape_dogs("https://petharbor.com/results.asp")

        assert len(dogs) == 2
        assert dogs[0].name == "OSCAR"
        assert dogs[0].breed == "Pit Bull"
        assert dogs[0].age_years == 2.0
        assert dogs[0].sex == "Male"
        assert dogs[1].name == "DAISY"
        assert dogs[1].age_years == pytest.approx(0.5)

    @patch("src.scraper.requests.get")
    def test_petharbor_portal_with_nav_only(self, mock_get):
        """Test that a PetHarbor page with only nav (no cards) returns empty."""
        html = """
        <html>
        <body>
        <div class="container">
          <nav class="navbar navbar-expand-lg navbarCSS">
            <div class="navHeaderText"></div>
            <div class="navbar-collapse" id="navbarSupportedContent">
              <ul class="navbar-nav mr-auto">
                <li class="nav-item navAdopt"
                    onclick="AdoptableAnimals('WestSlopeShelterAdoptablePets')">
                  <a class="nav-link active" id="adopt-tab">
                    <span>Adoptable Pets</span>
                  </a>
                </li>
              </ul>
            </div>
          </nav>
          <form action="/PetHarborShelter/GetAnimalBySearchInput" method="post">
            <input name="SearchText" type="search" />
          </form>
        </div>
        </body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        dogs = scrape_dogs("https://shelter.petharbor.com/available-dogs")
        # No animal cards present, should return empty list
        assert len(dogs) == 0


# --- Result_* div format tests ---


class TestResultDivs:
    @patch("src.scraper.requests.get")
    def test_scrape_result_divs_format(self, mock_get):
        """Test scraping divs with IDs matching Result_* pattern."""
        html = """
        <html>
        <body>
        <div class="results-container">
          <div id="Result_1">
            <img src="https://shelter.com/photos/buddy.jpg" />
            <a href="/dogs/buddy">View Details</a>
            <div class="line_Name">
              <span class="label">Name:</span>
              <span class="results">Buddy</span>
            </div>
            <div class="line_Gender">
              <span class="label">Gender:</span>
              <span class="results">Male</span>
            </div>
            <div class="line_Breed">
              <span class="label">Breed:</span>
              <span class="results">Labrador Retriever</span>
            </div>
            <div class="line_Age">
              <span class="label">Age:</span>
              <span class="results">1 year, 4 months old</span>
            </div>
          </div>
          <div id="Result_2">
            <img src="https://shelter.com/photos/luna.jpg" />
            <a href="/dogs/luna">View Details</a>
            <div class="line_Name">
              <span class="label">Name:</span>
              <span class="results">Luna</span>
            </div>
            <div class="line_Gender">
              <span class="label">Gender:</span>
              <span class="results">Female</span>
            </div>
            <div class="line_Breed">
              <span class="label">Breed:</span>
              <span class="results">Poodle Mix</span>
            </div>
            <div class="line_Age">
              <span class="label">Age:</span>
              <span class="results">16 weeks old</span>
            </div>
          </div>
          <div id="Result_3">
            <img src="https://shelter.com/photos/max.jpg" />
            <a href="/dogs/max">View Details</a>
            <div class="line_Name">
              <span class="label">Name:</span>
              <span class="results">Max</span>
            </div>
            <div class="line_Gender">
              <span class="label">Gender:</span>
              <span class="results">Male</span>
            </div>
            <div class="line_Breed">
              <span class="label">Breed:</span>
              <span class="results">German Shepherd</span>
            </div>
            <div class="line_Age">
              <span class="label">Age:</span>
              <span class="results">5 years</span>
            </div>
          </div>
          <div id="Result_4">
            <img src="https://shelter.com/photos/daisy.jpg" />
            <a href="/dogs/daisy">View Details</a>
            <div class="line_Name">
              <span class="label">Name:</span>
              <span class="results">Daisy</span>
            </div>
            <div class="line_Gender">
              <span class="label">Gender:</span>
              <span class="results">Female</span>
            </div>
            <div class="line_Breed">
              <span class="label">Breed:</span>
              <span class="results">Beagle</span>
            </div>
            <div class="line_Age">
              <span class="label">Age:</span>
              <span class="results">1 year old</span>
            </div>
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

        assert len(dogs) == 4

        # First dog: Buddy - 1 year, 4 months old
        assert dogs[0].name == "Buddy"
        assert dogs[0].breed == "Labrador Retriever"
        assert dogs[0].age_years == pytest.approx(1 + 4/12.0)
        assert dogs[0].sex == "Male"
        assert dogs[0].image_url == "https://shelter.com/photos/buddy.jpg"
        assert "/dogs/buddy" in dogs[0].url

        # Second dog: Luna - 16 weeks old
        assert dogs[1].name == "Luna"
        assert dogs[1].breed == "Poodle Mix"
        assert dogs[1].age_years == pytest.approx(16.0 / 52.0)
        assert dogs[1].sex == "Female"
        assert dogs[1].image_url == "https://shelter.com/photos/luna.jpg"

        # Third dog: Max - 5 years
        assert dogs[2].name == "Max"
        assert dogs[2].breed == "German Shepherd"
        assert dogs[2].age_years == 5.0
        assert dogs[2].sex == "Male"

        # Fourth dog: Daisy - 1 year old
        assert dogs[3].name == "Daisy"
        assert dogs[3].breed == "Beagle"
        assert dogs[3].age_years == 1.0
        assert dogs[3].sex == "Female"

    @patch("src.scraper.requests.get")
    def test_result_divs_case_insensitive(self, mock_get):
        """Test that Result_* matching is case insensitive."""
        html = """
        <html>
        <body>
          <div id="result_1">
            <img src="https://shelter.com/photos/rex.jpg" />
            <div class="line_Name">
              <span class="results">Rex</span>
            </div>
            <div class="line_Gender">
              <span class="results">Male</span>
            </div>
            <div class="line_Breed">
              <span class="results">Bulldog</span>
            </div>
            <div class="line_Age">
              <span class="results">2 years</span>
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

        assert len(dogs) == 1
        assert dogs[0].name == "Rex"
        assert dogs[0].breed == "Bulldog"
        assert dogs[0].age_years == 2.0


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
