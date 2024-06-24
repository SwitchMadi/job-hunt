from utilities.aws.ec2 import EC2


def lambda_handler(event, context):
    script = r"""<script>
    echo Current date and time >> C:\Users\JobHunt\Desktop\startup.log
    echo %DATE% %TIME% >> C:\Users\JobHunt\Desktop\startup.log
    echo user_email: 'bhaskar2choudhary@gmail.com' >> C:\Users\JobHunt\Desktop\startup_input.yml
    </script>
    <persist>true</persist>"""

    EC2(
        instance_pricing_model="on_demand",
        ami_id="ami-0613ebfe01c12abcc",
        instance_type="t3a.2xlarge",
        key_name="job-hunt",
        security_group="sg-011a3786d569e6382",
        user_data_script=script,
    )
    return
