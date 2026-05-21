import requests

from typing import Dict, List, Optional

from hotglue_singer_sdk.target_sdk.client import HotglueSink
from hotglue_singer_sdk.exceptions import FatalAPIError, RetriableAPIError
from hotglue_etl_exceptions import InvalidCredentialsError, InvalidPayloadError
from hotglue_singer_sdk.plugin_base import PluginBase

from target_linnworks.auth import LinnworksAuth


class LinnworksSink(HotglueSink):
    def __init__(
        self,
        target: PluginBase,
        stream_name: str,
        schema: Dict,
        key_properties: Optional[List[str]],
    ) -> None:
        super().__init__(target, stream_name, schema, key_properties)
        self.authenticator = LinnworksAuth(self._target)

    @property
    def base_url(self) -> str:
        return getattr(self._target, "_server", "https://eu-ext.linnworks.net")

    def linnworks_post(self, path: str, form_data: dict) -> requests.Response:
        """POST form-encoded data to a Linnworks API path.

        Auth headers are resolved first so that _server is populated before base_url is read.
        On a 401 the token is cleared and the request is retried once with a fresh session,
        handling the case where the server invalidates a token before our local TTL expires.
        """
        headers = self.default_headers
        response = requests.post(f"{self.base_url}{path}", headers=headers, data=form_data)
        if response.status_code == 401:
            self.authenticator._token = None
            headers = self.default_headers  # triggers _authorize(); raises if credentials are bad
            response = requests.post(f"{self.base_url}{path}", headers=headers, data=form_data)
        self.validate_response(response)
        return response

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

