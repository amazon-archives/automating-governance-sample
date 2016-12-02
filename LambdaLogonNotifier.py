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

print('Loading function')

__author__ = 'armandl'
__email__ = 'armandl@amazon.com'
__status__ = 'sample'

'''
Handles events related to logon by:
1. notifying subscribers to a pre-defined SNS topic.
2. Based on user, takes next action as:
    a. Root: Remove instance from ASG, Deploys block and NACL to block external IP.
    b. Others: Notify level 2 to increase monitoring (flowlogs + OS actions monitored).
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


def send_notification(subject='', message='', SNS_ARN_REGION=global_args.SNS_ARN_REGION, SNS_ARN=global_args.SNS_ARN):
    '''
    Helper to send SNS message to subscribers
    '''
    clientSNS = boto3.client('sns', region_name=SNS_ARN_REGION)
    response = clientSNS.publish(TargetArn=SNS_ARN,
                                 Message=message,
                                 Subject=subject)
    return response


def set_logging():
    '''
    Helper to enable debugging
    '''
    return logging.basicConfig(level=global_args.LOG)


def set_enhanced_monitoring(instance='none'):
    '''
    Request second tier of responders to kick off monitoring
    Only flowlogs supported at the moment.
    '''
    client = boto3.client('events', region_name=global_args.REGION)
    detail = {'instance': instance, 'actionsRequested': 'enableFlowLogs'}
    response = client.put_events(
        Entries=[
            {
                'Time': int(time.time()),
                'Source': 'auto.responder.level1',
                'Resources': [
                    str(instance)
                ],
                'DetailType': 'enhanceMonitoring',
                'Detail': json.dumps(detail)
            }
        ]
    )
    return response

# Logon TT dynamo interaction

def send_dynamo(event, table,region='us-east-1'):
    client = get_connector(region)
    tab=get_table(client, table)
    response = tab.put_item(Item=event)
    return response

def get_table(client, table):
    return client.Table(table)

def get_connector(region):
    client = boto3.resource('dynamodb',region_name=region)
    return client

def remove_dynamo(event, table,region='us-east-1'):
    client = get_connector(region)
    tab=get_table(client, table)
    response = tab.delete_item(Key ={'target_ip':event['target_ip']})
    return response

def exists_in_dynamo(ip_address, table, region='us-east-1'):
    try:
        client = boto3.resource("dynamodb", region_name=region)
        table = client.Table(table)
        response = table.get_item(Key ={'target_ip':ip_address})
        if 'Item' in response:
            response['result']=True
        else:
            response['result']=False
        return response
    except Exception as e:
        response['result'] = False
        return response

# end of logon TT dynamo interaction

def get_ip_from_instance_id(id):
    try:
        ec2 = boto3.resource('ec2', region_name='us-east-1')
        ip = ec2.Instance(id).private_ip_address
    except Exception as e:
        return 'unable to get private_ip_address'
    return ip

# FIXME: corresponds to OSLogonCWEvent in Lambda
def lambda_handler(event, context):
    response = set_logging()
    logging.info(response)
    logging.info("Received event: " + json.dumps(event, indent=2))

    '''
    Get IP, Username and Instance ID so we can ring the alarm.
    '''
    if 'detail' in event:
        ip = event['detail']['ip']
        user = event['detail']['user']
    else:
        ip = 'unknown'
        user = 'unknown'

    if 'resources' in event and len(event['resources'])>0:
        instance_id = event['resources'][0] #assumes single instance
    else:
        instance_id='unknown'

    ip_address = get_ip_from_instance_id(instance_id)
    response = exists_in_dynamo(ip_address,'logonCanary') #DYNAMO TABLE CONTAINING 'AUTHORISED' ACCESS RECORD WITH DESTIONATION IP.
    if 'result' in response and response['result']:
        print('no alarm')
        response = remove_dynamo({'target_ip':ip_address},'logonCanary')
        return "approved logon"


    #TODO check for multiple logons
    response = send_notification(subject='L1: '+ user +' logon to ' + str(instance_id),
                                 message=user + ' logon from ' + ip + ' to ' + str(instance_id))
    logging.debug(response)

    response = set_enhanced_monitoring(instance_id)
    logging.debug(response)

    return "I'm done..."
