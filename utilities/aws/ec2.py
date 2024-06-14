import base64
import time

from utilities.aws import get_aws_client
from utilities.logging import get_logger


logger = get_logger(name="ec2", file_name="job-hunt")


class EC2:
    def __init__(
        self,
        instance_id=None,
        instance_pricing_model=None,
        ami_id=None,
        instance_type=None,
        key_name=None,
        security_group=None,
        iam_fleet_role=None,
        user_data_script=None,
    ):
        self.client = get_aws_client("ec2")
        if instance_id:
            self.instance_id = instance_id
        else:
            self.ami_id = ami_id
            self.instance_type = instance_type
            self.key_name = key_name
            self.security_group = security_group
            self.iam_fleet_role = iam_fleet_role
            self.user_data_script = user_data_script

            if instance_pricing_model == "spot":
                self.launch_spot_instance()
            elif instance_pricing_model == "on_demand":
                self.launch_on_demand_instance()

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
                        "UserData": base64.b64encode(
                            self.user_data_script.encode("utf-8")
                        )
                        .decode("utf-8")
                        .strip(),
                    },
                ],
                "TargetCapacity": 1,
            }
        )

        spot_fleet_request_id = response["SpotFleetRequestId"]

        # Custom polling mechanism to wait for the spot instance to be fulfilled
        instance_fulfilled = False
        while not instance_fulfilled:
            logger.info("Sleeping for 10 seconds to check spot_fleet_response later...")
            time.sleep(10)  # Wait for 10 seconds before checking the status again
            spot_fleet_response = self.client.describe_spot_fleet_requests(
                SpotFleetRequestIds=[spot_fleet_request_id]
            )
            status = spot_fleet_response["SpotFleetRequestConfigs"][0]["ActivityStatus"]
            if status == "fulfilled":
                instance_fulfilled = True

        # Get the instance ID
        spot_instances = self.client.describe_spot_fleet_instances(
            SpotFleetRequestId=spot_fleet_request_id
        )
        self.instance_id = spot_instances["ActiveInstances"][0]["InstanceId"]
        logger.info(
            f"Spot instance request fulfilled. instance_id - {self.instance_id}"
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
        return True

    def stop_instance(self):
        self.client.stop_instances(InstanceIds=[self.instance_id])
        logger.info(f"Instance stopped. instance_id - {self.instance_id}")

    def terminate_instance(self):
        response = self.client.terminate_instances(InstanceIds=[self.instance_id])
        terminated_instance_id = response["TerminatingInstances"][0]["InstanceId"]
        logger.info(f"Instance terminated. instance_id - {terminated_instance_id}")
        return True

    def create_snapshot(self):
        # Create an AMI from the instance
        ami_response = self.client.create_image(
            InstanceId=self.instance_id,
            Name=f"snapshot-{self.instance_id}",
            NoReboot=True,
        )

        ami_id = ami_response["ImageId"]

        # Wait for the AMI to be available
        waiter = self.client.get_waiter("image_available")
        waiter.wait(ImageIds=[ami_id])

        # Describe the AMI to get the snapshot ID
        image_info = self.client.describe_images(ImageIds=[ami_id])
        snapshot_id = image_info["Images"][0]["BlockDeviceMappings"][0]["Ebs"][
            "SnapshotId"
        ]

        return snapshot_id
