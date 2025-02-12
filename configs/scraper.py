import math
import json
import time
import logging
from typing import Tuple, List
from configs import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Scraper:
    def __init__(self, spider_client, max_retries=10, initial_sleep=5, batch_sleep=10):
        """
        :param spider_client: An instance of your Spider client for making requests
        :param max_retries: Max number of retries for each URL
        :param initial_sleep: Sleep before initial page scraping attempts
        :param batch_sleep: Sleep before each batch of paginated URL requests
        """
        self.spider_client = spider_client
        self.max_retries = max_retries
        self.initial_sleep = initial_sleep
        self.batch_sleep = batch_sleep

    def build_car_url(self, make: str, city_state: str, first_record: int, zip_code: int) -> str:
        """
        Build a URL for the car scrape.
        """
        return (
            f"https://www.autotrader.com/cars-for-sale/all-cars/electric/"
            f"{make}/{city_state}?endYear=2025&firstRecord={first_record}&numRecords=100&searchRadius=50&startYear=2020&zip={zip_code}"
        )

    def scrape_initial_page(self, city_state: str, make: str, zip_code: int) -> dict:
        """
        Attempt to scrape the first page for pagination data.
        Returns the JSON data if successful, otherwise an empty dict.
        """
        try:
            url = self.build_car_url(make, city_state, first_record=1, zip_code=zip_code)
            logger.info(f"Scraping initial page for make={make}, zip={zip_code} -> {url}")

            response_list = self.spider_client.scrape_url(url=url, params=settings.PARAMS)
            if not response_list:
                logger.warning(f"Empty response list for make={make}, zip={zip_code}")
                return {}

            first_item = response_list[0]
            json_data = first_item.get("json_data", {})

            # Convert JSON string to dict if needed
            if isinstance(json_data, str):
                json_data = json.loads(json_data)

            # Confirm it’s a dictionary
            if not isinstance(json_data, dict):
                logger.error(f"Expected json_data to be a dictionary, but got {type(json_data)}")
                return {}

            return json_data

        except Exception as exc:
            logger.error(f"Error scraping initial page for {make}, zip={zip_code}: {exc}")
            return {}

    def get_pagination_info(self, json_data: dict) -> Tuple[int, int]:
        """
        Extract pagination info from the JSON response (total listings, page size).
        """
        next_data = json_data.get("NEXT_DATA", {})
        if isinstance(next_data, str):
            next_data = json.loads(next_data)

        eggs_state = next_data.get("props", {}).get("pageProps", {}).get("__eggsState", {})
        srp_pagination = eggs_state.get("srp_pagination", {})
        srp_results = eggs_state.get("srp_results", {})

        count = srp_results.get("count", 0)
        num_records = srp_pagination.get("numRecords", 100)
        return count, num_records

    def generate_paginated_urls(self, make: str, city_state: str, zip_code: int, 
                                total_listings: int, page_size: int) -> List[str]:
        """
        Return a list of all paginated URLs for the given city/make/zip.
        """
        total_pages = math.ceil(total_listings / page_size)
        all_urls = []
        for page_num in range(1, total_pages + 1):
            first_record = 1 if page_num == 1 else page_size * (page_num - 1)
            page_url = self.build_car_url(make, city_state, first_record, zip_code)
            all_urls.append(page_url)

        return all_urls

    def scrape_paginated_urls(self, urls: List[str]) -> Tuple[List[dict], List[str]]:
        """
        Scrape the provided list of URLs with retry logic.
        Returns:
        - successful_results: list of response items (each representing a successful scrape)
        - leftover_urls: list of URLs that couldn't be scraped after max retries
        """
        successful_results = []
        retry_queue = urls[:]  # Start with all URLs
        retries = {url: 0 for url in urls}
        exhausted_urls = []    # Track URLs that hit max retries

        while retry_queue:
            logger.info(f"Starting batch for {len(retry_queue)} URLs.")
            batch_urls_str = ",".join(retry_queue)
            
            try:
                results = self.spider_client.scrape_url(url=batch_urls_str, params=settings.PARAMS)
            except Exception as exc:
                logger.error(f"Error scraping batch URLs: {exc}")
                break

            batch_success_count = 0
            batch_retry_count = 0
            next_retry_queue = []

            # Process each response in the batch
            for response_item in results:
                response_url = response_item.get("url")
                resp_json = response_item.get("json_data", {})
                if isinstance(resp_json, str):
                    try:
                        resp_json = json.loads(resp_json)
                    except json.JSONDecodeError:
                        resp_json = {}

                # If response is empty or blocked:
                if not resp_json or resp_json.get("other_scripts") == []:
                    if retries[response_url] < self.max_retries:
                        retries[response_url] += 1
                        next_retry_queue.append(response_url)
                        batch_retry_count += 1
                    else:
                        logger.error(f"Max retries reached for {response_url}")
                        exhausted_urls.append(response_url)
                else:
                    successful_results.append(response_item)
                    batch_success_count += 1

            # Additionally, check for any URLs that never appeared in the results
            found_urls = {item.get("url") for item in results}
            for url in retry_queue:
                if url not in found_urls:
                    if retries[url] < self.max_retries:
                        retries[url] += 1
                        next_retry_queue.append(url)
                        batch_retry_count += 1
                    else:
                        logger.error(f"Max retries reached for missing response {url}")
                        exhausted_urls.append(url)

            logger.info(
                f"Batch summary: {batch_success_count} URLs scraped successfully, "
                f"{batch_retry_count} URLs require retry."
            )

            retry_queue = next_retry_queue

            if retry_queue:
                logger.debug(f"Sleeping for {self.batch_sleep} seconds before next batch.")
                time.sleep(self.batch_sleep)

        leftover_urls = exhausted_urls
        return successful_results, leftover_urls

    def run_scraper(self, city_state: str, zip_code: int, make: str) -> Tuple[List[dict], List[str]]:
        """
        High-level method to:
          1) Scrape initial page (with retries).
          2) Get pagination info.
          3) Generate all URLs & scrape them.
        Returns (successful_responses, leftover_urls).
        """
        initial_json_data = None
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"Scraping initial page (Attempt {attempt}) for make={make}, zip={zip_code}.")
            time.sleep(self.initial_sleep)  # wait between attempts
            json_data = self.scrape_initial_page(city_state, make, zip_code)

            if not json_data or json_data.get("other_scripts") == []:
                logger.warning(f"Initial page blocked or empty for {make}/{zip_code}. Retrying...")
            else:
                initial_json_data = json_data
                break

        if not initial_json_data:
            logger.error(f"Failed initial scrape for {make}/{zip_code} after {self.max_retries} retries.")
            # Return empty results and assume the caller handles it
            return [], []

        # Extract pagination info from valid initial page
        total_listings, page_size = self.get_pagination_info(initial_json_data)
        logger.info(f"For make={make}, zip={zip_code}, found {total_listings} listings, page_size={page_size}.")

        if total_listings == 0:
            logger.info(f"No listings found for {make}/{zip_code}. Skipping.")
            return [], []

        # Generate all paginated URLs
        paginated_urls = self.generate_paginated_urls(make, city_state, zip_code, total_listings, page_size)
        logger.info(f"Total URLs to scrape: {len(paginated_urls)}")

        # Scrape them
        successful_results, leftover_urls = self.scrape_paginated_urls(paginated_urls)

        return successful_results, leftover_urls
