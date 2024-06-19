from utilities.aws.ec2 import EC2

ec2 = EC2(self_identify_instance=True)
print(ec2.instance_id)
# ec2.terminate_instance()
