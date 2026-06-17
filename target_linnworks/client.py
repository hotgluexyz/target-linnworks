import requests
from typing import Optional

from hotglue_singer_sdk.target_sdk.client import HotglueSink
from hotglue_singer_sdk.exceptions import FatalAPIError, RetriableAPIError
from hotglue_etl_exceptions import InvalidCredentialsError, InvalidPayloadError

from target_linnworks.auth import LinnworksAuth


class LinnworksSink(HotglueSink):
    def __init__(self, target, stream_name, schema, key_properties):
        super().__init__(target, stream_name, schema, key_properties)
        self.authenticator = LinnworksAuth(self._target)

    @property
    def base_url(self) -> str:
        return getattr(self._target, "_server", "https://eu-ext.linnworks.net")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Authenticated request with one 401 retry to handle expired session tokens.

        Calling self.default_headers first ensures auth runs (and sets _server) before
        base_url is read.
        """
        headers = self.default_headers
        response = requests.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            self.authenticator._token = None
            headers = self.default_headers
            response = requests.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        self.validate_response(response)
        return response

    def linnworks_post(self, path: str, form_data: dict) -> requests.Response:
        """POST form-encoded data (used by legacy endpoints like CreateOrders)."""
        return self._request("POST", path, data=form_data)

    def _find_item_by_sku(self, sku: str) -> Optional[dict]:
        """Return an existing StockItem dict for the given SKU, or None if not found.

        Linnworks returns 400 (not 404) when the SKU does not exist, so we bypass
        validate_response and check the status code directly.
        """
        headers = self.default_headers
        response = requests.get(
            f"{self.base_url}/api/Inventory/GetInventoryItem",
            headers=headers,
            params={"sKU": sku},
        )
        if response.status_code == 400:
            return None
        self.validate_response(response)
        return response.json()

    def _get_location_id(self, location_name: str) -> Optional[str]:
        """Resolve a stock location name to its UUID, with per-target caching."""
        if not hasattr(self._target, "_location_cache"):
            self._target._location_cache = {}
        cache = self._target._location_cache
        if location_name not in cache:
            for loc in self._request("GET", "/api/Inventory/GetStockLocations").json():
                cache[loc["LocationName"]] = loc["StockLocationId"]
        return cache.get(location_name)

    def validate_response(self, response: requests.Response) -> None:
        if response.status_code == 401:
            try:
                msg = response.json().get("Message") or response.text
            except Exception:
                msg = response.text
            raise InvalidCredentialsError(msg)

        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise RetriableAPIError(
                f"{response.status_code} error from Linnworks: {response.text}", response
            )

        if 400 <= response.status_code < 500:
            try:
                error = response.json()
                msg = error.get("Message") or error.get("message") or response.text
            except Exception:
                msg = response.text
            if response.status_code == 400:
                raise InvalidPayloadError(msg)
            raise FatalAPIError(msg)
