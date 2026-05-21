import requests
from datetime import datetime, timedelta

from hotglue_etl_exceptions import InvalidCredentialsError
from hotglue_singer_sdk.target_sdk.auth import Authenticator

# Linnworks session tokens expire after 20 minutes of inactivity; we refresh 60 s early.
_SESSION_TTL_SECONDS = 19 * 60


class LinnworksAuth(Authenticator):
    def __init__(self, target):
        super().__init__(target)
        self._session = requests.Session()
        self._token = None
        self._expires_at = None
        self._credentials_error = None

    def _authorize(self):
        if self._credentials_error is not None:
            raise InvalidCredentialsError(self._credentials_error)

        response = self._session.post(
            "https://api.linnworks.net/api/Auth/AuthorizeByApplication",
            data={
                "ApplicationId": self._config.get("application_id"),
                "ApplicationSecret": self._config.get("application_secret"),
                "Token": self._config.get("installation_token"),
            },
        )

        if response.status_code != 429 and (400 <= response.status_code < 500):
            self._credentials_error = response.text
            raise InvalidCredentialsError(response.text)

        if response.status_code != 200:
            raise Exception(f"Linnworks auth failed ({response.status_code}): {response.text}")

        data = response.json()
        self._token = data["Token"]
        self._expires_at = datetime.utcnow() + timedelta(seconds=_SESSION_TTL_SECONDS)

        # Store the server URL on the target so the sink can build base_url.
        self._target._server = data["Server"]

    @property
    def auth_headers(self) -> dict:
        if self._token is None or datetime.utcnow() >= self._expires_at:
            self._authorize()
        return {"Authorization": self._token}
