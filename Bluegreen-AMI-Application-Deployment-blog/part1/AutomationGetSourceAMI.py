from __future__ import print_function

import json
import boto3

print('Loading function')

ARCH_TO_AMI_NAME_PATTERN = {
    # Architecture: (pattern, owner)
    "PV64": ("amzn-ami-pv*.x86_64-ebs", "amazon"),
    "HVM64": ("amzn-ami-hvm*.x86_64-gp2", "amazon"),
    "HVMG2": ("amzn-ami-graphics-hvm-*x86_64-ebs*", "679593333241")
}


def find_latest_ami_name(region, arch):

    pattern, owner = ARCH_TO_AMI_NAME_PATTERN[arch]

    ec2 = boto3.client("ec2", region_name=region)

    images = ec2.describe_images(
        Filters=[dict(
            Name="name",
            Values=[pattern]
        )],
        Owners=[owner]
    ).get("Images", [])

    assert images, "No images were found"

    sorted_images = sorted(images, key=lambda image: image["Name"],
                           reverse=True)

    latest_image = sorted_images[0]
    print("latest_image:" + latest_image["ImageId"])
    return latest_image["ImageId"]

# Expects parameterName, parameterValue
def lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))

    region = event['Region']
    arch = event['Architecture']

    return find_latest_ami_name(region, arch)