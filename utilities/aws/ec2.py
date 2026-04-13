import base64
import time
import requests

from utilities.aws import get_aws_client
from utilities.logging import get_logger


logger = get_logger(name="ec2")

_METADATA_BASE = "http://169.254.169.254/latest/meta-data"


class EC2:
    def __init__(
        self,
        self_identify_instance=False,
        instance_id=None,
        instance_pricing_model=None,
        ami_id=None,
        instance_type=None,
        key_name=None,
        security_group=None,
        iam_fleet_role=None,
        user_data_script=None,
        instance_name=None,
    ):
        self.client = get_aws_client("ec2")
        if self_identify_instance:
            metadata_url = f"{_METADATA_BASE}/instance-id"

            try:
                response = requests.get(metadata_url)
                response.raise_for_status()
                self.instance_id = response.text
            except requests.RequestException as e:
                logger.exception(f"Error fetching instance ID: {e}")
        elif instance_id:
            self.instance_id = instance_id
        else:
            self.ami_id = ami_id
            self.instance_type = instance_type
            self.key_name = key_name
            self.security_group = security_group
            self.iam_fleet_role = iam_fleet_role
            self.user_data_script = user_data_script
            self.instance_name = instance_name

            if instance_pricing_model == "spot":
                self.launch_spot_instance()
            elif instance_pricing_model == "on_demand":
                self.launch_on_demand_instance()

    @staticmethod
    def _metadata_text(path_suffix: str, timeout: float = 2) -> str:
        url = f"{_METADATA_BASE}/{path_suffix.lstrip('/')}"
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return (response.text or "").strip()
        except requests.RequestException as e:
            logger.debug("IMDS read failed for %s: %s", path_suffix, e)
            return ""

    def get_public_hostname(self) -> str:
        """Public DNS for this instance from IMDS, or empty string if unavailable."""
        return self._metadata_text("public-hostname")

    def get_public_ipv4(self) -> str:
        """Public IPv4 for this instance from IMDS, or empty string if unavailable."""
        return self._metadata_text("public-ipv4")

    def resolve_public_connectable_host(self) -> str:
        """
        Hostname or IP suitable for HTTPS URLs to this instance (browser, DCV web client, etc.).
        Prefer DNS; fall back to IPv4. Uses instance metadata only.
        """
        host = self.get_public_hostname()
        if host:
            return host
        return self.get_public_ipv4()

    def launch_spot_instance(self):
        response = self.client.request_spot_fleet(
            SpotFleetRequestConfig={
                "IamFleetRole": self.iam_fleet_role,
                "AllocationStrategy": "lowestPrice",
                "LaunchSpecifications": [
                    {
                        "ImageId": self.ami_id,
                        "InstanceType": self.instance_type,
                        "KeyName": self.key_name,
                        "SecurityGroups": [{"GroupName": self.security_group}],
                        "UserData": (
                            base64.b64encode(self.user_data_script.encode("utf-8"))
                            .decode("utf-8")
                            .strip()
                        ),
                    },
                ],
                "TargetCapacity": 1,
            }
        )

        spot_fleet_request_id = response["SpotFleetRequestId"]

        instance_fulfilled = False
        while not instance_fulfilled:
            logger.info("Sleeping for 10 seconds to check spot_fleet_response later...")
            time.sleep(10)
            spot_fleet_response = self.client.describe_spot_fleet_requests(
                SpotFleetRequestIds=[spot_fleet_request_id]
            )
            status = spot_fleet_response["SpotFleetRequestConfigs"][0]["ActivityStatus"]
            if status == "fulfilled":
                instance_fulfilled = True

        spot_instances = self.client.describe_spot_fleet_instances(
            SpotFleetRequestId=spot_fleet_request_id
        )
        self.instance_id = spot_instances["ActiveInstances"][0]["InstanceId"]
        logger.info(
            f"Spot instance request fulfilled. instance_id - {self.instance_id}"
        )

        if self.instance_name:
            self.client.create_tags(
                Resources=[self.instance_id],
                Tags=[{"Key": "Name", "Value": self.instance_name}],
            )

        return True

    def launch_on_demand_instance(self):
        response = self.client.run_instances(
            ImageId=self.ami_id,
            InstanceType=self.instance_type,
            MinCount=1,
            MaxCount=1,
            KeyName=self.key_name,
            SecurityGroupIds=[self.security_group],
            UserData=f"{self.user_data_script}",
        )

        self.instance_id = response["Instances"][0]["InstanceId"]

        if self.instance_name:
            self.client.create_tags(
                Resources=[self.instance_id],
                Tags=[{"Key": "Name", "Value": self.instance_name}],
            )

        return True

    def stop_instance(self):
        self.client.stop_instances(InstanceIds=[self.instance_id])
        logger.info(f"Instance stopped. instance_id - {self.instance_id}")

    def terminate_instance(self):
        logger.info(f"Terminating instance...\ninstance_id - {self.instance_id}")
        response = self.client.terminate_instances(InstanceIds=[self.instance_id])
        terminated_instance_id = response["TerminatingInstances"][0]["InstanceId"]
        logger.info(f"Instance terminated. instance_id - {terminated_instance_id}")
        return True

    def create_snapshot(self, name=None):
        ami_response = self.client.create_image(
            InstanceId=self.instance_id,
            Name=name if name else f"snapshot-{self.instance_id}",
            NoReboot=True,
        )

        ami_id = ami_response["ImageId"]

        waiter = self.client.get_waiter("image_available")
        waiter.wait(ImageIds=[ami_id])

        image_info = self.client.describe_images(ImageIds=[ami_id])
        snapshot_id = image_info["Images"][0]["BlockDeviceMappings"][0]["Ebs"][
            "SnapshotId"
        ]

        return snapshot_id
