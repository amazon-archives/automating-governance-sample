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
import json
import base64
import zlib
import logging
import boto3
import time

__email__ = 'armandl@amazon.com'
__status__ = 'sample'


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


def set_logging(lv=global_args.LOG):
    '''
    Helper to enable debugging
    '''
    return logging.basicConfig(level=lv)


def eval_message(message):
    data = message.split()
    # use case 1 - su to root
    if 'root' in message or 'uid=0' in message:
        logging.info(data)
        if 'session opened for user root by' in message or 'USER=root' in message:
            logging.info('User is escalating to root: '+message)
            return {'action':'Level3Escalation','reason':'Escalation to root privileges','message':message}
    return {'action':'NoAction','reason':'no signature triggered','message':message}

def set_instance_isolation(instance='none'):
    '''
    Request third tier of responders to isolate instance.
    '''
    client = boto3.client('events', region_name=global_args.REGION)
    detail = {'instance': instance, 'actionsRequested': 'instanceIsolation'}
    response = client.put_events(
        Entries=[
            {
                'Time': int(time.time()),
                'Source': 'auto.responder.level2',
                'Resources': [
                    str(instance)
                ],
                'DetailType': 'activeResponse',
                'Detail': json.dumps(detail)
            }
        ]
    )
    logging.info(response)
    return response


def lambda_handler(event, context):
    # print("Received event: " + json.dumps(event, indent=2))
    set_logging()
    print("Decoding from b64")
    compressed_data = base64.b64decode(event['awslogs']['data'])
    logging.debug(compressed_data)  # the compressed message (binary data)
    data = json.loads(zlib.decompress(compressed_data, zlib.MAX_WBITS | 32))
    logging.info(data)  # now we have the message.
    if 'logStream' in data: # logstream is the instance id
        instance = data['logStream']
    else:
        instance = 'Unknown'
    if 'logEvents' in data:  # sanity check - JSON doc must include 'logEvents' array.
        for event in data['logEvents']:
            logging.info("Let take care one at a time..." + str(event['message']))
            response = eval_message(event['message'])
            if 'action' in response and response['action']=='Level3Escalation':
                try:
                    response = send_notification(subject='Root escalation at '+str(instance)+". No isolation.",message='Likely escalation to root detected from '+str(response['message'])+'. Will isolate instance.')
                except Exception as e:
                    logging.info('Unable to send notification of root escalation. Will still attempt to isolate instance. Error: '+e.message)
                #We kick off responder here...
                try:
                    response=set_instance_isolation(instance)
                except Exception as e:
                    logging.info('Failure to isolate instance. Error: '+e.message)

                logging.info(response)
                exit(1)
    return "I'm done..."

