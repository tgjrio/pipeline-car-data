import pytest
from unittest.mock import MagicMock
import logging
import sys
import os
import json

# Add project root to sys.path so we can import Scraper
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from configs.scraper import Scraper

# -------------------------------------------------------------------
# Logging Configuration
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TestScraper:
    """
    Unit tests for the Scraper class, covering:
      - URL building
      - Initial page scrape
      - Pagination info extraction
      - Paginated URL generation
      - Paginated scraping with retries
      - Full scraping pipeline (initial + paginated)
    """

    @pytest.fixture
    def mock_spider_client(self):
        """
        Create a mocked spider client to avoid real network requests.
        """
        return MagicMock()

    @pytest.fixture
    def scraper(self, mock_spider_client):
        """
        Initialize the Scraper class with a mock spider client.
        """
        return Scraper(spider_client=mock_spider_client, max_retries=3, initial_sleep=0, batch_sleep=0)

    def test_build_car_url(self, scraper):
        """
        Test the URL generation logic.
        """
        logger.info("Testing build_car_url method...")
        make = "Toyota"
        city_state = "atlanta-ga"
        first_record = 1
        zip_code = 30301

        expected_url = (
            "https://www.autotrader.com/cars-for-sale/all-cars/"
            "Toyota/atlanta-ga?firstRecord=1&numRecords=100&searchRadius=50&startYear=2021&zip=30301"
        )

        actual_url = scraper.build_car_url(make, city_state, first_record, zip_code)
        logger.info(f"Generated URL: {actual_url}")
        assert actual_url == expected_url

    def test_scrape_initial_page_success(self, scraper, mock_spider_client):
        """
        Test scraping the initial page with a valid response.
        """
        logger.info("Testing scrape_initial_page with a successful response...")
        mock_response = [
            {
                "json_data": {
                    "NEXT_DATA": {
                        "props": {
                            "pageProps": {
                                "__eggsState": {
                                    "srp_pagination": {"numRecords": 100},
                                    "srp_results": {"count": 300}
                                }
                            }
                        }
                    }
                }
            }
        ]
        mock_spider_client.scrape_url.return_value = mock_response

        result = scraper.scrape_initial_page(
            city_state="atlanta-ga",
            make="Toyota",
            zip_code=30301
        )
        logger.info(f"Scrape result: {result}")

        assert result == mock_response[0]["json_data"]
        mock_spider_client.scrape_url.assert_called_once()

    def test_scrape_initial_page_failure(self, scraper, mock_spider_client):
        """
        Test scraping the initial page when the response is empty/invalid.
        """
        logger.info("Testing scrape_initial_page with an empty response...")
        mock_spider_client.scrape_url.return_value = []

        result = scraper.scrape_initial_page(
            city_state="atlanta-ga",
            make="Toyota",
            zip_code=30301
        )
        logger.info(f"Scrape result: {result}")

        assert result == {}
        mock_spider_client.scrape_url.assert_called_once()

    def test_get_pagination_info(self, scraper):
        """
        Test extracting pagination info from JSON data.
        """
        logger.info("Testing get_pagination_info...")
        json_data = {
            "NEXT_DATA": {
                "props": {
                    "pageProps": {
                        "__eggsState": {
                            "srp_pagination": {"numRecords": 100},
                            "srp_results": {"count": 300}
                        }
                    }
                }
            }
        }

        count, num_records = scraper.get_pagination_info(json_data)
        logger.info(f"Extracted count={count}, num_records={num_records}")

        assert count == 300
        assert num_records == 100

    def test_generate_paginated_urls(self, scraper):
        """
        Test generating all paginated URLs based on total listings & page size.
        """
        logger.info("Testing generate_paginated_urls...")
        make = "Toyota"
        city_state = "atlanta-ga"
        zip_code = 30301
        total_listings = 300
        page_size = 100

        urls = scraper.generate_paginated_urls(
            make, city_state, zip_code, total_listings, page_size
        )
        logger.info(f"Generated paginated URLs: {urls}")

        assert len(urls) == 3
        assert urls[0].endswith("firstRecord=1&numRecords=100&searchRadius=50&startYear=2021&zip=30301")
        assert urls[1].endswith("firstRecord=100&numRecords=100&searchRadius=50&startYear=2021&zip=30301")
        assert urls[2].endswith("firstRecord=200&numRecords=100&searchRadius=50&startYear=2021&zip=30301")

    def test_scrape_paginated_urls(self, scraper, mock_spider_client):
        """
        Test scrape_paginated_urls with multiple URLs,
        ensuring retries and leftover URL tracking.
        """
        logger.info("Testing scrape_paginated_urls with partial failures...")
        attempt_counts = {"url1": 0, "url2": 0, "url3": 0}

        def mock_scrape_side_effect(url, params):
            results = []
            for single_url in url.split(","):
                attempt_counts[single_url] += 1
                if single_url == "url1":
                    results.append({"url": "url1", "json_data": {"key": "value1"}})
                elif single_url == "url2":
                    # fail first time, succeed second
                    if attempt_counts["url2"] == 1:
                        results.append({"url": "url2", "json_data": {}})
                    else:
                        results.append({"url": "url2", "json_data": {"key": "value2"}})
                elif single_url == "url3":
                    # always fails
                    results.append({"url": "url3", "json_data": {}})
            return results

        mock_spider_client.scrape_url.side_effect = mock_scrape_side_effect

        urls = ["url1", "url2", "url3"]
        successful_results, leftover_urls = scraper.scrape_paginated_urls(urls)

        logger.info(f"Attempt counts: {attempt_counts}")
        logger.info(f"Successful Results: {successful_results}")
        logger.info(f"Leftover URLs: {leftover_urls}")

        # Verify successful results
        assert len(successful_results) == 2
        assert successful_results[0]["url"] == "url1"
        assert successful_results[1]["url"] == "url2"

        # Verify leftover URLs
        assert leftover_urls == ["url3"]

    def test_run_scraper_with_retries(self, scraper, mock_spider_client):
        """
        Test the full scraping pipeline: initial page + paginated URLs,
        simulating a scenario with successes, retries, and leftover URLs.
        """
        logger.info("Testing run_scraper with a multi-page scenario...")
        # Initial page tells us there are 300 total listings, 100 per page => 3 pages
        mock_initial_response = [
            {
                "json_data": {
                    "NEXT_DATA": {
                        "props": {
                            "pageProps": {
                                "__eggsState": {
                                    "srp_pagination": {"numRecords": 100},
                                    "srp_results": {"count": 300}
                                }
                            }
                        }
                    }
                }
            }
        ]

        attempt_counts = {}

        def mock_scrape_side_effect(*, url=None, params=None, **kwargs):
            results = []

            # Detect initial page request (e.g. firstRecord=1 & no commas)
            if "firstRecord=1" in url and url.count(",") == 0:
                logger.info("Mocking initial page response...")
                return mock_initial_response

            # Handle paginated URLs (could be multiple joined by commas)
            for single_url in url.split(","):
                attempt_counts.setdefault(single_url, 0)
                attempt_counts[single_url] += 1

                if "firstRecord=1" in single_url:
                    results.append({"url": single_url, "json_data": {"key": "page1"}})
                elif "firstRecord=100" in single_url or "firstRecord=101" in single_url:
                    # Fail once, succeed second
                    if attempt_counts[single_url] == 1:
                        results.append({"url": single_url, "json_data": {}})
                    else:
                        results.append({"url": single_url, "json_data": {"key": "page2"}})
                elif "firstRecord=200" in single_url or "firstRecord=201" in single_url:
                    # Always fail
                    results.append({"url": single_url, "json_data": {}})

            return results

        mock_spider_client.scrape_url.side_effect = mock_scrape_side_effect

        city_state = "atlanta-ga"
        zip_code = 30301
        make = "Toyota"

        successful_results, leftover_urls = scraper.run_scraper(city_state, zip_code, make)

        logger.info("Completed run_scraper. Checking results...")
        logger.info("Attempt counts per URL:")
        for url_key, count in attempt_counts.items():
            logger.info(f" - {url_key} => {count} attempt(s)")

        logger.info(f"Successful Results: {successful_results}")
        logger.info(f"Leftover URLs: {leftover_urls}")

        # We expect page1 & page2 to eventually succeed, page3 leftover
        assert len(successful_results) == 2
        assert len(leftover_urls) == 1

        leftover_page_3 = leftover_urls[0]
        # leftover should be the third page offset
        assert "firstRecord=200" in leftover_page_3 or "firstRecord=201" in leftover_page_3
