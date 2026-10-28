"""Region-to-geography mapping used for residency checks across clouds.

Data residency is usually stated with one cloud's region names. Endpoints hosted by another cloud
(for example AWS Bedrock fallback for an Azure-hosted application) are placed in a native region
of the same geography and validated by geography. This is a packaged snapshot; verify regional
availability and inference-profile destinations with the provider.
"""

from __future__ import annotations

REGION_GEOGRAPHY: dict[str, str] = {
    # Azure
    "westeurope": "EU",
    "northeurope": "EU",
    "francecentral": "EU",
    "germanywestcentral": "EU",
    "swedencentral": "EU",
    "italynorth": "EU",
    "polandcentral": "EU",
    "spaincentral": "EU",
    "switzerlandnorth": "CH",
    "uksouth": "UK",
    "ukwest": "UK",
    "eastus": "US",
    "eastus2": "US",
    "westus": "US",
    "westus2": "US",
    "westus3": "US",
    "centralus": "US",
    "southcentralus": "US",
    "northcentralus": "US",
    "canadacentral": "CA",
    "canadaeast": "CA",
    "japaneast": "JP",
    "australiaeast": "AU",
    "southeastasia": "APAC",
    "centralindia": "IN",
    # AWS
    "eu-west-1": "EU",
    "eu-west-3": "EU",
    "eu-central-1": "EU",
    "eu-north-1": "EU",
    "eu-south-1": "EU",
    "eu-south-2": "EU",
    "eu-central-2": "CH",
    "eu-west-2": "UK",
    "us-east-1": "US",
    "us-east-2": "US",
    "us-west-2": "US",
    "ca-central-1": "CA",
    "ap-northeast-1": "JP",
    "ap-southeast-2": "AU",
    "ap-southeast-1": "APAC",
    "ap-south-1": "IN",
    # Google Cloud
    "europe-west1": "EU",
    "europe-west3": "EU",
    "europe-west4": "EU",
    "us-central1": "US",
    "us-east4": "US",
}
AZURE_REGIONS = {name for name in REGION_GEOGRAPHY if "-" not in name}
AWS_PREFIXES = ("eu-", "us-", "ca-", "ap-", "sa-", "me-", "af-")
NATIVE_REGION: dict[tuple[str, str], str] = {
    ("aws", "EU"): "eu-central-1",
    ("aws", "US"): "us-east-1",
    ("aws", "UK"): "eu-west-2",
    ("aws", "CH"): "eu-central-2",
    ("aws", "CA"): "ca-central-1",
    ("aws", "JP"): "ap-northeast-1",
    ("aws", "AU"): "ap-southeast-2",
    ("aws", "IN"): "ap-south-1",
    ("aws", "APAC"): "ap-southeast-1",
    ("azure", "EU"): "westeurope",
    ("azure", "US"): "eastus2",
    ("azure", "UK"): "uksouth",
    ("azure", "CH"): "switzerlandnorth",
    ("azure", "CA"): "canadacentral",
    ("azure", "JP"): "japaneast",
    ("azure", "AU"): "australiaeast",
    ("azure", "IN"): "centralindia",
    ("azure", "APAC"): "southeastasia",
    ("gcp", "EU"): "europe-west4",
    ("gcp", "US"): "us-central1",
}


def geography(region: str) -> str | None:
    return REGION_GEOGRAPHY.get(region.strip().lower())


def region_cloud(region: str) -> str | None:
    name = region.strip().lower()
    if name in AZURE_REGIONS:
        return "azure"
    if name.startswith(("europe-", "us-central", "us-east4", "asia-")):
        return "gcp"
    if name.startswith(AWS_PREFIXES):
        return "aws"
    return None


def provider_cloud(provider: str) -> str | None:
    name = provider.lower()
    if "azure" in name:
        return "azure"
    if "bedrock" in name or "aws" in name:
        return "aws"
    if "vertex" in name or "google" in name:
        return "gcp"
    return None


def endpoint_region(provider: str, residency: list[str]) -> str:
    """A region for the provider that stays inside the approved residency."""
    home = residency[0]
    cloud = provider_cloud(provider)
    if cloud is None or cloud == region_cloud(home):
        return home
    for region in residency:
        if region_cloud(region) == cloud:
            return region
    native = NATIVE_REGION.get((cloud, geography(home) or ""))
    return native or home


def within_residency(region: str, residency: list[str]) -> bool:
    if region in residency:
        return True
    target = geography(region)
    return target is not None and target in {geography(item) for item in residency}
