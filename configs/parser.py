import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Parser:
    """
    Responsible for extracting the relevant fields from each response item.
    """

    def parse_inventory(self, response_item: dict) -> dict:
        raw_next_data = response_item.get("json_data", {}).get("NEXT_DATA", {})
        if isinstance(raw_next_data, str):
            try:
                raw_next_data = json.loads(raw_next_data)
            except json.JSONDecodeError as err:
                logger.warning(f"Failed to parse NEXT_DATA for inventory: {err}")
                return {}

        return (
            raw_next_data
            .get("props", {})
            .get("pageProps", {})
            .get("__eggsState", {})
            .get("inventory", {})
        )

    def parse_owners(self, response_item: dict) -> dict:
        raw_next_data = response_item.get("json_data", {}).get("NEXT_DATA", {})
        if isinstance(raw_next_data, str):
            try:
                raw_next_data = json.loads(raw_next_data)
            except json.JSONDecodeError as err:
                logger.warning(f"Failed to parse NEXT_DATA for owners: {err}")
                return {}

        return (
            raw_next_data
            .get("props", {})
            .get("pageProps", {})
            .get("__eggsState", {})
            .get("owners", {})
        )
