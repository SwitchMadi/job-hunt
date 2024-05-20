from utilities.aws import get_aws_client


class EC2:
    def __init__(
        self,
        instance_id=None,
        instance_pricing_model=None,
        ami_id=None,
        instance_type=None,
        key_name=None,
        security_group=None,
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
            self.user_data_script = user_data_script

            if instance_pricing_model == "spot":
                self.launch_spot_instance()
            elif instance_pricing_model == "on_demand":
                self.launch_on_demand_instance()

    def launch_spot_instance(self):
        response = self.client.request_spot_fleet(
            SpotFleetRequestConfig={
                "AllocationStrategy": "lowestPrice",
                "LaunchSpecifications": [
                    {
                        "ImageId": self.ami_id,
                        "InstanceType": self.instance_type,
                        "KeyName": self.key_name,
                        "SecurityGroups": [{"GroupName": self.security_group}],
                        "UserData": self.user_data_script.encode("utf-8").strip(),
                    },
                ],
                "TargetCapacity": 1,
            }
        )

        spot_fleet_request_id = response["SpotFleetRequestId"]

        # Wait for the spot instance to be fulfilled
        waiter = self.client.get_waiter("spot_fleet_request_fulfilled")
        waiter.wait(SpotFleetRequestIds=[spot_fleet_request_id])

        # Get the instance ID
        spot_instances = self.client.describe_spot_fleet_instances(
            SpotFleetRequestId=spot_fleet_request_id
        )
        self.instance_id = spot_instances["ActiveInstances"][0]["InstanceId"]

        return True

    def launch_on_demand_instance(self):
        response = self.client.run_instances(
            ImageId=self.ami_id,
            InstanceType=self.instance_type,
            MinCount=1,
            MaxCount=1,
            KeyName=self.key_name,
            SecurityGroups=[self.security_group],
            UserData=self.user_data_script.encode("utf-8").strip(),
        )

        self.instance_id = response["Instances"][0]["InstanceId"]
        return True

    def stop_instance(self):
        self.client.stop_instances(InstanceIds=[self.instance_id])
