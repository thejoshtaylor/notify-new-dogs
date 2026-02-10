# notify-new-dogs

A Python service that runs on a configurable interval to check a dog shelter website for new adoptable dogs. When a new dog is found that meets the age criteria, it sends a webhook notification with the dog's details and picture URL.

## Features

- Scrapes a shelter website for available dogs on a recurring schedule
- Saves all found dogs to a CSV file for tracking
- Detects new dogs by comparing against previously seen dogs
- Filters notifications by a configurable maximum age (in years)
- Sends a JSON webhook notification with dog details and image URL
- Deployable via Docker Compose

## Setup

1. Copy the example environment file and fill in your values:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your configuration:

   | Variable               | Description                                      | Example                                  |
   |------------------------|--------------------------------------------------|------------------------------------------|
   | `CHECK_INTERVAL_HOURS` | How often to check for new dogs (in hours)       | `6`                                      |
   | `SHELTER_URL`          | URL of the shelter's available dogs page          | `https://www.shelter.com/available-dogs`  |
   | `MAX_AGE_YEARS`        | Maximum dog age (years) to trigger notifications  | `5`                                      |
   | `WEBHOOK_URL`          | Webhook URL for notifications                     | `https://hooks.example.com/webhook`      |
   | `CSV_FILE_PATH`        | Path to store the CSV tracking file               | `data/dogs.csv`                          |

## Running with Docker Compose

```bash
docker compose up -d
```

To view logs:

```bash
docker compose logs -f dog-checker
```

## Running Locally

```bash
pip install -r requirements.txt
python main.py
```

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Webhook Payload

When a new dog is found that meets the age filter, a POST request is sent to the configured webhook URL with this JSON payload:

```json
{
  "name": "Buddy",
  "breed": "Labrador Retriever",
  "age_years": 2.0,
  "sex": "Male",
  "size": "Large",
  "url": "https://shelter.com/dogs/buddy",
  "image_url": "https://shelter.com/images/buddy.jpg"
}
```
