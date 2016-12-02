# Copyright 2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#  http://aws.amazon.com/apache2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

from __future__ import print_function
import boto3
import json
import logging
import time

__email__ = 'armandl@amazon.com'
__status__ = 'sample'

'''
generic helpers

'''


class global_args:
    '''
    Helper to define global statics
    '''
    REGION = '<DEPLOYMENT REGION>'
    LOG = logging.INFO
    SNS_ARN = '<ARN FOR SNS NOTIFICATIONS>'
    SNS_ARN_REGION = '<REGION WHERE SNS RESIDES>'
    FLOWLOGS_ARN_ROLE = '<ARN FOR ROLE THAT PROVIDES FLOWLOGS ACCESS>'


def set_logging(lv=global_args.LOG):
    '''
    Helper to enable debugging
    '''
    return logging.basicConfig(level=lv)


def send_notification(subject='', message='', SNS_ARN_REGION=global_args.SNS_ARN_REGION, SNS_ARN=global_args.SNS_ARN):
    '''
    Helper to send SNS message to subscribers
    '''
    clientSNS = boto3.client('sns', region_name=SNS_ARN_REGION)
    response = clientSNS.publish(TargetArn=SNS_ARN,
                                 Message=message,
                                 Subject=subject)
    return response


'''
start of custom
'''


def flowlogs_enabled(nic=''):
    client = boto3.client('ec2', region_name=global_args.REGION)
    response = client.describe_flow_logs(
        Filters=[{'Name': 'resource-id', 'Values': [nic]}]
    )
    logging.info("enable?" + str(response))
    return True if len(response['FlowLogs']) > 0 else False


def lambda_handler(event, context):
    # TODO: making assumption of a single instance ID with a single NIC.
    logging.info(event)
    if 'detail' in event:
        instancesl = event['detail']['instance']  # [0]
    else:
        return "No instance specified..."


    # get first interface in instance
    client = boto3.resource('ec2', region_name=global_args.REGION)
    instance = client.Instance(instancesl)
    nic = instance.network_interfaces_attribute[0]['NetworkInterfaceId']
    logging.info(nic)
    loggroup_name = 'forensic-' + str(instancesl)

    if not flowlogs_enabled(nic):
        try:
            client = boto3.client('logs', region_name=global_args.REGION)
            response = client.create_log_group(
                logGroupName=loggroup_name
            )
            logging.info(response)
        except Exception as e:
            logging.info('Unable to create loggroup - assuming it exists and continuing')

        try:
            client = boto3.client('ec2', region_name=global_args.REGION)
            response = client.create_flow_logs(
                ResourceIds=[
                    nic
                ],
                ResourceType='NetworkInterface',
                TrafficType='ALL',
                LogGroupName=loggroup_name,
                DeliverLogsPermissionArn=global_args.FLOWLOGS_ARN_ROLE
            )
        except Exception as e:
            response = send_notification(subject='L2: Failed to start flowlogs for ' + str(instancesl),
                                         message='VPC flowlogs not started - investigate urgently or escalate to level 3 response.\n'
                                                 'raw return message follows:' + e.message)
            return response

        response = send_notification(subject='L2' + str(instancesl) + ' flowslogs started.',
                                     message='LogGroup created under ' + loggroup_name + '.\nStarting lambda filter.')
        logging.info(response)
    else:
        logging.info('Flowlogs already enabled for nic. Will proceed with Lambda setup.')
        response = send_notification(subject="L2: Flowlogs already enabled for " + str(instancesl),
                                     message="Will attempt Lambda subscription.")


    # Add permission to push of events to lambda by flowlogs
    try:
        client = boto3.client('lambda', region_name=global_args.REGION)
        response = client.add_permission(
            FunctionName='FlowLogsResponderCWEvent',
            StatementId='FlowLogsResponderCWEvent' + str(instancesl),
            Action='lambda:InvokeFunction',
            Principal='logs.us-east-1.amazonaws.com',
            SourceArn='arn:aws:logs:us-east-1:333051327088:log-group:' + loggroup_name + ':*'
        )
        logging.info(response)
    except Exception as e:
        logging.info('Unable to add permission for flowlogsresponser... likely already setup. Will attempt subscription.'+e.message)

    # Creating subscription for flowlogs
    try:
        client = boto3.client('logs', region_name=global_args.REGION)

        response = client.put_subscription_filter(
            logGroupName=loggroup_name,
            filterName=loggroup_name,
            filterPattern='',
            destinationArn='<ARN FOR LAMBDA HANDLING FLOWLOGS e.g. arn:aws:lambda:REGION:ACCOUNT:function:FlowLogsResponderCWEvent',
        )
        logging.info(response)
        response = send_notification(subject="L2("+str(instancesl)+"): Responder for flowlogs subscribed.",
                                     message="Flowlogs under " + loggroup_name + ". FlowLogsResponderCWEvent subscription complete.")
        logging.info(response)
    except Exception as e:
        logging.info("L2: Failed to setup subscription for flowlogs"+e.message)
        response = send_notification(subject="L2("+str(instancesl)+": unable to setup flowlogs responder.",
                                     message="Raw error:" + e.message)


    # Add permission to push of events to lambda for /var/log/secure
    try:
        client = boto3.client('lambda', region_name=global_args.REGION)
        response = client.add_permission(
            FunctionName='secureLogResponderCWEvent',
            StatementId='secureLogResponderCWEvent' + str(instancesl),
            Action='lambda:InvokeFunction',
            Principal='logs.us-east-1.amazonaws.com',
            SourceArn='<ARN FOR VAR/LOG/SECURE CODE: arn:aws:logs:REGION:ACCOUNT:log-group:/var/log/secure:*>'
        )
        logging.info(response)
    except Exception as e:
        logging.info('Unable to add permission for /var/log/secure. likely already setup. Will attempt subscription. RAW'+e.message)

    # Creating subscription for /var/log/secure
    try:
        client = boto3.client('logs', region_name=global_args.REGION)
        # check if logroup is already subscribed to
        response = client.put_subscription_filter(
                logGroupName='/var/log/secure',
                filterName='/var/log/secure' + str(instancesl),
                filterPattern='[date, day, hour, hostname, daemon="su*",...]',
                destinationArn='<ARN FOR LAMBDA HANDLING VAR/LOG/SECURE E.G. arn:aws:lambda:REGION:XXXXX:function:secureLogResponderCWEvent'
            )
        logging.info(response)
        subject="L2("+str(instancesl)+"): Responder for /var/log/secure subscribed."
        message="/var/log/secure responder enabled. Will deploy full instance isolation if root access attempted."
        response = send_notification(subject=subject, message=message)
        logging.info(response)
    except Exception as e:
        logging.info(e.message)
        response = send_notification(subject="L2("+str(instancesl)+"): Unable to setup /var/secure responder. ",
                                     message="Raw error:" + e.message)
        logging.info(response)

    # We should be done at this point.

    return "I'm done..."  # Echo back the first key value


if __name__ == '__main__':
    event = {
        "account": "TESTACCOUNT",
        "region": "us-east-1",
        "detail": {
            "instance":
                "i-62693cff"
            ,
            "actionsRequested": "enableFlowLogs"
        },
        "detail-type": "enhanceMonitoring",
        "source": "auto.responder.level1",
        "version": "0",
        "time": "2016-05-08T03:45:05Z",
        "id": "c8392513-92e4-4e81-b754-9866a9f6dbfa",
        "resources": [
            "['i-62693cff']"
        ]
    }
    set_logging(logging.INFO)
    lambda_handler(event, '')
