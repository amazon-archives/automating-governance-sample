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

__author__ = 'armandl'
__email__ = 'armandl@amazon.com'
__status__ = 'sample'

'''
Generic stub for Lambda handlers
By default just prints event and exist.
'''

print('Loading function')


# Start of generic block
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


def creat_audit_trail(message):
    return "Will create an audit trail in dynamo"


# End of generic block

def asg_healthy(instance):
    client = boto3.client('autoscaling', region_name=global_args.REGION)
    try:
        response = client.describe_auto_scaling_instances(
            InstanceIds=[
                instance
            ]
        )
        # return response
    except Exception as e:
        logging.info('API fail to describe ASG instances. Raw: ' + e.message)
        logging.info({'result': 'failure', 'message': 'API fail to describe ASG instances. Raw: ' + e.message})
        return True
    logging.info(response)
    for asg in response['AutoScalingInstances']:
        # logging.info(asg)
        asg_name = asg['AutoScalingGroupName']

    response = client.describe_auto_scaling_groups(
        AutoScalingGroupNames=[
            asg_name
        ]
    )
    healthy = 0
    other = 0
    for asg in response['AutoScalingGroups']:
        minimum_asg_size = asg['MinSize']
        for instance in asg['Instances']:
            if asg['AutoScalingInstances'] == 'InService':
                healthy += 1
            else:
                other += 1

    if healthy > minimum_asg_size / 2:
        return True
    else:
        return False

        # logging.info(response)


def remove_from_asg(instance):
    '''
    Identifies if instance is part of an ASG and removes it from group if that is the case.
    Takes an instance ID as input.
    Returns dict with outcome of requests.
    '''
    client = boto3.client('autoscaling', region_name=global_args.REGION)
    try:
        response = client.describe_auto_scaling_instances(
            InstanceIds=[
                instance
            ]
        )
    except Exception as e:
        logging.info('API fail to describe ASG instances. Raw: ' + e.message)
        return {'result': 'failure', 'message': 'API fail to describe ASG instances. Raw: ' + e.message}
    logging.info(response)

    if 'AutoScalingInstances' in response and len(response['AutoScalingInstances']) > 0:
        if 'AutoScalingGroupName' in response['AutoScalingInstances'][0]:
            asg_name = response['AutoScalingInstances'][0]['AutoScalingGroupName']
        else:
            logging.info('Unable to obtain ASG name... will not be able to deregister instance. Exiting.')
            return {'result': 'failure', 'message': 'unable to get ASG name'}

        # found ASG, will now remove
        try:
            response = client.detach_instances(
                InstanceIds=[
                    instance,
                ],
                AutoScalingGroupName=asg_name,
                ShouldDecrementDesiredCapacity=False
            )
            logging.info('ASG removal outcome: ' + str(response))
            subject = 'L3(' + instance + '): Successfuly removed instance from asg'
            message = 'Success in detaching instance from ASG,' + asg_name + '.'
            return {'result': 'ok', 'message': message, 'subject': subject}
        except Exception as e:
            logging.info('Unable to remove ' + instance + ' from ' + asg_name + '. Raw error: ' + e.message)
            return {'result': 'failure',
                    'message': 'Unable to remove ' + instance + ' from ' + asg_name + '. Raw error: ' + e.message}

    else:
        return {'result': 'notfound', 'message': 'Instance doesn\'t seem part of an ASG'}
    return "done"


def preserve_forensic_data(instance):
    client = boto3.client('ec2', region_name=global_args.REGION)
    message = ''
    result_b = 0
    try:
        response = client.modify_instance_attribute(
            InstanceId=instance,
            DisableApiTermination={
                'Value': True
            }
        )
        logging.info('API Termination done.' + str(response))
        message += 'API Termination enabled.\n'
        result_b += 4
    except Exception as e:
        logging.info('Unable to enable ApiTermination protection. Raw: ' + e.message)
        message += 'Failed to enable API termination protection.\n'

    # modify shutdown behavior to stop
    try:
        response = client.modify_instance_attribute(
            InstanceId=instance,
            InstanceInitiatedShutdownBehavior={
                'Value': 'stop'
            }
        )
        logging.info('Istance shutdown behavior set to STOP.' + str(response))
        message += 'Instance shutdown behavior set to STOP\n'
        result_b += 2
    except Exception as e:
        logging.info('Unable to update shutdown behavior. Raw: ' + e.message)
        message += 'Failed to update shutdown behavior\n'

    sg = get_default_sg(instance)
    try:
        response = client.modify_instance_attribute(
            InstanceId=instance,
            Groups=[sg]
        )
        logging.info('SG set to block (default sg). Raw: ' + str(response))
        message += 'SG set to block (default sg)\n'
        result_b += 1
    except Exception as e:
        logging.info('Unable to change SG. Raw: ' + e.message)
        message += 'Failed deploy SG to isolate.\n'

    if result_b == 7:
        return {'result': 'ok', 'message': message}
    elif result_b > 0:
        return {'result': 'partial', 'message': message}
    else:
        return {'result': 'failure', 'message': message}


# find the default group for the VPC
def get_default_sg(instance):
    try:
        # find instance VPC
        ec2 = boto3.resource('ec2', region_name=global_args.REGION)
        instance_o = ec2.Instance(instance)
        vpc = instance_o.vpc_id
        vpc_o = ec2.Vpc(vpc)
        for sg in vpc_o.security_groups.all():
            if sg.group_name == 'default':
                logging.info('default group id: ' + sg.group_name)
                return sg.group_id
        return "none"
    except Exception as e:
        logging.info('Unable to get default SG... Raw:' + e.message)
        return 'none'


def terminate_instance(instance):
    try:
        client = boto3.client('ec2')
        response = client.terminate_instances(
            InstanceIds=[instance])
        logging.info('Terminated...' + str(response))
        return {'result': 'ok', 'message': 'Instance terminated.', 'subject': 'L3(' + instance + '): Terminated.'}
    except Exception as e:
        logging.info('Unable to termiante instance. Raw:' + e.message)
        return {'result': 'failure', 'message': 'Unable to terminate instance. Raw: ' + e.message,
                'subject': 'L3(' + instance + '): unable to terminate.'}


def lambda_handler(event, context):
    set_logging(logging.INFO)
    if global_args.TEMPORARY_DISABLE:
        logging.info('Isolation currently disabled - check code for responder and set var to \'True\'')
    # print("Received event: " + json.dumps(event, indent=2))


    instance = 'none'
    if 'detail' in event and 'instance' in event['detail']:
        instance = event['detail']['instance']
        logging.info('instance ' + instance)
    else:
        logging.info('No instance specified or unable to retrieve from event... no action taken.')
        return 'Exiting due to no instance being specified'

    if asg_healthy(instance):
        if 'actionsRequested' in event['detail'] and event['detail']['actionsRequested'] == 'instanceTermination':
            response = terminate_instance(instance)
            send_notification(subject=response['subject'], message=response['message'])
            return "Instance termination complete"


            # prevent termination, force stop on shutdown, deploy isolation sg
        response = preserve_forensic_data(instance)
        if 'result' in response:
            if response['result'] == 'ok':
                send_notification(subject='L3(' + instance + '): Success in isolating instance.',
                                  message=response['message'])
            elif response['result'] == 'partial':
                send_notification(subject='L3(' + instance + '): Only partial isolation accomplished.',
                                  message=response['message'])
            else:
                send_notification(subject='L3(' + instance + '): Failed to isolate instance.',
                                  message=response['message'])


                # check is instance in ASG and remove.
        response = remove_from_asg(instance)
        if 'result' in response:
            if response['result'] == 'ok':
            # FIXME assumption that response will always have a subject and message.
                send_notification(subject=response['subject'], message=response['message'])
            elif response['result'] == 'notfound':
                send_notification(subject='L3(' + instance + ') not part of an ASG - no detachment made.',
                              message=response['message'])
            else:
                send_notification(subject='L3(' + instance + ') failure in ASG detachment - detail in full alert.',
                              message=response['message'])


    return "Exiting function..."  # Echo back the first key value
