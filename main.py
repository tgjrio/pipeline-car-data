import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import os
import logging
import datetime

from spider import Spider
from configs.scraper import Scraper
from configs.parser import Parser
from configs import settings
from dotenv import load_dotenv
from snowflake.snowpark import Session

# Initialize FastAPI app
app = FastAPI()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration variables
SPIDER_CLOUD_KEY = os.getenv("SPIDER_CLOUD_KEY")

# Snowflake connection parameters (do not include protocol or domain suffix)
SNOWFLAKE_ACCOUNT   = os.getenv("SNOWFLAKE_ACCOUNT")
SNOWFLAKE_USER      = os.getenv("SNOWFLAKE_USER")
SNOWFLAKE_PASSWORD  = os.getenv("SNOWFLAKE_PASSWORD")
SNOWFLAKE_DATABASE  = os.getenv("SNOWFLAKE_DATABASE")
SNOWFLAKE_SCHEMA    = os.getenv("SNOWFLAKE_SCHEMA")

sf_connection_params = {
    "account": SNOWFLAKE_ACCOUNT,
    "user": SNOWFLAKE_USER,
    "password": SNOWFLAKE_PASSWORD,
    "database": SNOWFLAKE_DATABASE,
    "schema": SNOWFLAKE_SCHEMA,
}

# Create a Snowflake session using Snowpark
session = Session.builder.configs(sf_connection_params).create()

# Constants for scraping
ZIP_CODES = {
    "atlanta-ga": 30306,
    "houston-tx": 77001,
    "dallas-tx" : 75201,
    "los-angeles-ca": 90001,
    "san-francisco-ca": 94102,
    "seattle-wa": 98101,
    "new-york-ny": 10001,
}
DAILY_DRIVER_MAKES = [
    "Kia",  
    "Tesla", 
    "Toyota", 
    "Honda", 
    "Hyundai", 
    "Ford", 
    "Rivian", 
    "BMW", 
    "Audi",  
    "mercedes-benz",
    "volkswagen"
]

def insert_data_to_snowflake(data, table_name):
    """
    Insert a list of dictionaries into a specified Snowflake table using Snowpark.
    """
    if not data:
        logger.info(f"No data to insert into table {table_name}.")
        return
    try:
        df = session.create_dataframe(data)
        df.write.save_as_table(table_name, mode="append")
        logger.info(f"Inserted {len(data)} records into {table_name}.")
    except Exception as e:
        logger.error(f"Error inserting data into {table_name}: {e}")

def run_scraping_pipeline():
    """
    Runs the complete pipeline:
      - For each city, aggregates URLs for all makes.
      - Submits one combined scraping request per city using retry logic.
      - Parses the results.
      - Inserts data into Snowflake.
    """
    # Initialize scraper components
    spider_client = Spider(api_key=SPIDER_CLOUD_KEY)
    scraper = Scraper(spider_client=spider_client, max_retries=10)
    parser = Parser()

    all_inventories = []
    all_owners = []
    current_timestamp = datetime.datetime.now().isoformat()

    # Loop through each city
    for city_state, zip_code in ZIP_CODES.items():
        combined_urls = []  # Collect URLs for all makes in the city.
        logger.info(f"Processing city: {city_state} (zip: {zip_code})")

        # Loop through each make and generate its URLs.
        for make in DAILY_DRIVER_MAKES:
            logger.info(f"  Generating URLs for make '{make}' in {city_state}.")
            # Get the initial page to determine pagination info.
            initial_json_data = None
            for attempt in range(1, scraper.max_retries + 1):
                time.sleep(scraper.initial_sleep)
                json_data = scraper.scrape_initial_page(city_state, make, zip_code)
                if json_data and json_data.get("other_scripts") != []:
                    initial_json_data = json_data
                    break
                else:
                    logger.warning(f"    Attempt {attempt}: Initial page blocked/empty for {make} in {city_state}.")
            if not initial_json_data:
                logger.error(f"    Failed initial scrape for {make} in {city_state} after {scraper.max_retries} retries.")
                continue

            total_listings, page_size = scraper.get_pagination_info(initial_json_data)
            if total_listings == 0:
                logger.info(f"    No listings found for {make} in {city_state}. Skipping.")
                continue

            paginated_urls = scraper.generate_paginated_urls(make, city_state, zip_code, total_listings, page_size)
            logger.info(f"    Generated {len(paginated_urls)} URLs for {make} in {city_state}.")
            combined_urls.extend(paginated_urls)

        if not combined_urls:
            logger.info(f"No URLs generated for any makes in {city_state}. Skipping scraping for this city.")
            continue

        # Use the retry logic method to scrape all the combined URLs.
        logger.info(f"Submitting combined scraping request for {city_state} with {len(combined_urls)} URLs.")
        successful_results, leftover_urls = scraper.scrape_paginated_urls(combined_urls)
        if leftover_urls:
            logger.warning(f"{len(leftover_urls)} URLs could not be scraped for {city_state}.")
        else:
            logger.info(f"All URLs scraped successfully for {city_state}.")

        # Process each response
        for response_item in successful_results:
            url = response_item.get("url", "")
            # Extract make info from URL if needed.
            make_extracted = "unknown"
            try:
                parts = url.split("/")
                if "electric" in parts:
                    idx = parts.index("electric")
                    if len(parts) > idx + 1:
                        make_extracted = parts[idx + 1]
            except Exception as e:
                logger.warning(f"Could not extract make from URL: {url} ({e})")

            # Parse inventory and owners data
            inventory_data = parser.parse_inventory(response_item)
            owners_data = parser.parse_owners(response_item)
            inv_record = {"scrape_date": current_timestamp, "make": make_extracted, "data": inventory_data}
            owner_record = {"scrape_date": current_timestamp, "data": owners_data}
            all_inventories.append(inv_record)
            all_owners.append(owner_record)

    # Insert data into Snowflake
    insert_data_to_snowflake(all_inventories, f"{SNOWFLAKE_SCHEMA}.inventory")
    insert_data_to_snowflake(all_owners, f"{SNOWFLAKE_SCHEMA}.owners")
    return {"status": "success", "message": "Scraping pipeline executed successfully"}



@app.post("/run")
async def run_pipeline():
    """
    Endpoint to trigger the scraping pipeline.
    Cloud Scheduler can be configured to send an HTTP POST request here.
    """
    try:
        result = run_scraping_pipeline()
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        logger.error(f"Error running pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# For local testing, run: uvicorn main:app --reload --port 8080
