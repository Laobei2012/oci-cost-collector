"""Read cost reports from OCI Object Storage."""

from dataclasses import dataclass
from datetime import datetime

import oci

# Oracle keeps the reports of all tenancies in this namespace. The bucket name
# is the OCID of the tenancy.
NAMESPACE = "bling"
PREFIX = "reports/cost-csv/"


@dataclass(frozen=True)
class Report:
    name: str
    created_at: datetime | None


def make_client(
    auth: str, region: str | None, config_file: str | None, profile: str
) -> oci.object_storage.ObjectStorageClient:
    """Make an Object Storage client.

    auth is "instance_principal", "resource_principal" or "config_file". If
    region is None, the client uses the region of the signer or the config file.
    """
    if auth == "instance_principal":
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        config = {"region": region or signer.region}
    elif auth == "resource_principal":
        signer = oci.auth.signers.get_resource_principals_signer()
        config = {"region": region or signer.region}
    elif auth == "config_file":
        config = oci.config.from_file(config_file or oci.config.DEFAULT_LOCATION, profile)
        if region:
            config["region"] = region
        return oci.object_storage.ObjectStorageClient(config)
    else:
        raise ValueError(f"unknown auth method: {auth}")
    return oci.object_storage.ObjectStorageClient(config, signer=signer)


def list_reports(client: oci.object_storage.ObjectStorageClient, tenancy_id: str) -> list[Report]:
    response = oci.pagination.list_call_get_all_results(
        client.list_objects, NAMESPACE, tenancy_id, prefix=PREFIX, fields="name,timeCreated"
    )
    return [Report(o.name, o.time_created) for o in response.data.objects]


def download(client: oci.object_storage.ObjectStorageClient, tenancy_id: str, name: str) -> bytes:
    return client.get_object(NAMESPACE, tenancy_id, name).data.content
