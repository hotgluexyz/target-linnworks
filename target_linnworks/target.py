"""Linnworks target class."""

from hotglue_singer_sdk import typing as th
from hotglue_singer_sdk.target_sdk.target import TargetHotglue
from hotglue_singer_sdk.helpers.capabilities import AlertingLevel

from target_linnworks.sinks import OrdersSink, ProductsSink


class TargetLinnworks(TargetHotglue):
    """Singer target for Linnworks."""

    SINK_TYPES = [
        OrdersSink,
        ProductsSink,
    ]
    name = "target-linnworks"
    alerting_level = AlertingLevel.ERROR

    config_jsonschema = th.PropertiesList(
        th.Property("application_id", th.StringType, required=True),
        th.Property("application_secret", th.StringType, required=True),
        th.Property("installation_token", th.StringType, required=True),
        th.Property("location", th.StringType, required=False),
        th.Property("default_source", th.StringType, required=False),
        th.Property("default_subsource", th.StringType, required=False),
    ).to_dict()


if __name__ == "__main__":
    TargetLinnworks.cli()
