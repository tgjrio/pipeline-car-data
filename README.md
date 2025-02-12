# Autotrader Web Scraping Pipeline

This pipeline is designed to scrape automobile listings from [AutoTrader](https://www.autotrader.com/) and parse structured data. It utilizes two main classes—**Scraper** and **Parser**—and a coordinating script to manage the workflow end-to-end.

## Table of Contents
1. [Overview](#overview)
2. [Components](#components)
    - [Scraper Class](#scraper-class)
    - [Parser Class](#parser-class)
    - [Main Script](#main-script)
3. [Data Flow](#data-flow)
4. [Retry Logic & Leftover URLs](#retry-logic--leftover-urls)
5. [Future Enhancements](#future-enhancements)

## Overview

**Goal**: Collect up-to-date car listings for specific makes and ZIP codes, then parse relevant details (e.g., inventory and owners) for downstream analysis. The pipeline is designed to be resilient against temporary blocks or empty responses, logging unprocessed URLs for retry.

**Key Points**:
- Configurable **maximum retry** attempts for each URL.
- Flexible **pagination** support, dynamically adapting to the listing count.
- **Logging** of both successful and failed scrapes.
- **Modular design** for easy integration into other pipelines (e.g., Databricks).


## Components

### Scraper Class
- **Purpose**: Encapsulates all network-related logic, including URL generation, initial-page scraping, and iterative retrieval of paginated results.  
- **Notable Methods**:
  - **`build_car_url`**: Constructs the base URL for a given make, city/state, and pagination offset.  
  - **`scrape_initial_page`**: Fetches the first page to discover the total number of listings and the expected page size.  
  - **`get_pagination_info`**: Extracts total listing count and page size from the returned JSON.  
  - **`generate_paginated_urls`**: Creates a list of URLs to cover all result pages.  
  - **`scrape_paginated_urls`**: Performs concurrent/batch scraping of all pages with retry logic.  
  - **`run_daily_scrape`**: Orchestrates the entire scrape process (initial page → pagination → batch scraping).

### Parser Class
- **Purpose**: Handles extraction of specific data structures (e.g., `inventory` and `owners`) from the JSON response.  
- **Notable Methods**:
  - **`parse_inventory`**: Grabs the portion of the JSON detailing the vehicle listings.  
  - **`parse_owners`**: Retrieves the information about vehicle owners or dealerships.

### Main Script
- **Orchestration**:  
  1. Sets up **logging** and **configuration** (e.g., ZIP codes, makes).  
  2. Instantiates the `Scraper` and `Parser`.  
  3. Iterates through each make/ZIP combination, calling `run_scraper`.  
  4. Saves both the raw JSON and the parsed data to disk.  
  5. Handles leftover URLs that surpass the maximum retries, writing them to a separate file for potential downstream retrial.


## Data Flow

1. **Initial Page Request**  
   - The pipeline requests the first page for a given (make, zip) pair.  
   - This response includes metadata like total listings and page size.

2. **Pagination & URL Generation**  
   - Using the total listing count, the pipeline generates a list of URLs covering all pages (e.g., first record at 1, 101, 201, etc.).

3. **Parallel/Batch Scraping**  
   - The pipeline requests each page in batches via the `scrape_paginated_urls` method.  
   - If a page is empty or blocked, it will be retried until the maximum retry limit is reached.

4. **Data Parsing**  
   - Once responses are collected, the `Parser` class extracts the `inventory` and `owners` data from each JSON record.

5. **Result Storage**  
   - The pipeline stores:
     - **Raw Results**: Full JSON payloads (for debugging or future processing).  
     - **Parsed Data**: Inventory and owner details in separate JSON files.


## Retry Logic & Leftover URLs

- **Max Retries**: Configurable (e.g., 10 attempts).  
- If a page consistently fails (e.g., returning an empty or blocked response), it gets logged.  
- The pipeline outputs any **leftover URLs** that exceed the retry limit into a separate file. These can be fed into another pipeline or run manually later.


## Future Enhancements

- **Databricks Integration**:  
  - Package the scraper and parser logic into a notebook or wheel for scheduling via Databricks Jobs.  
  - Store leftover URLs in a distributed file system or table for downstream pickup.

- **Additional Data Extraction**:  
  - Extend the `Parser` to handle new fields as the site’s JSON structure evolves.  
  - Incorporate advanced transformations (e.g., standardizing vehicle attributes).

- **Distributed Scraping**:  
  - If necessary, distribute the URL list across multiple workers or cluster nodes to handle large-scale scrapes more quickly.

---

**Questions or Feedback?**  
Feel free to open an issue or make a pull request to suggest additional features or improvements.
