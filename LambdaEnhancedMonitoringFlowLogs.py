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

__email__ = 'armandl@amazon.com'
__status__ = 'sample'

print('Loading function')


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


def eval_flow(message,instance_ip='none'):
    data = message.split()
    # Port 22 to rest of internal network
    common_ports = ['80','443','22','123'] #ugly... we alert if any other ports used.
    logging.debug(data)
    if len(data) == 14:
        src_ip = data[3]
        src_port = data[5]
        dst_ip = data[4]
        dst_port = data[6]
        filter_result = data[12]
        #instance_ip = get_ip_by_nic(data[2])
        logging.info('from: ' + src_ip + ':' + src_port + ' to: ' + dst_ip + ':' + dst_port+' - instance ip: '+instance_ip)

        #Basic list of heuristics...
        #ssh from this host to somewhere else...
        ssh_hosts=[]
        other_hosts=[]
        if src_ip == instance_ip and dst_port == '22' and src_port!='22' and dst_ip not in ssh_hosts:
            logging.info('SSH outbound detected...')
            if dst_ip not in ssh_hosts:
                send_notification(subject="L2("+instance_ip+'): starting SSH outbound to '+dst_ip,message='Instance initiating SSH.')
                ssh_hosts.append(dst_ip)
                if '10.0' in dst_ip:
                    send_notification(subject="L2("+instance_ip+'): SSH to internal host at '+dst_ip+'. Will isolate',message='Instance initiating SSH.')

            #start isolation...
        if  src_port not in ['80','443','22','123'] and dst_port<1024 and src_ip==instance_ip:
            if dst_ip not in other_hosts:
                other_hosts.append(dst_ip)
                send_notification(subject="L2("+instance_ip+'): Unrecognised traffic.',message='Unrecognised traffic started by instance. From port:'+src_port+' To port: '+dst_port)
            logging.info('Unrecognised traffic initiated from host...'+filter_result)
    return {'action': 'NoAction', 'reason': 'no signature triggered', 'message': message}

def get_ip_by_nic(nic):
    try:
        client = boto3.resource('ec2', region_name=global_args.REGION)
        network_interface = client.NetworkInterface(nic)
        logging.info(network_interface.private_ip_address)
        return network_interface.private_ip_address
    except Exception as e:
        logging.info('Unable to get internal IP... error: '+e.message)
        return ''

def lambda_handler(event, context):
    set_logging(logging.INFO)
    print("Decoding from b64")
    compressed_data = base64.b64decode(event['awslogs']['data'])
    logging.debug(compressed_data)  # the compressed message (binary data)
    data = json.loads(zlib.decompress(compressed_data, zlib.MAX_WBITS | 32))
    logging.info(data)  # now we have the message.

    #Get instance name from Loggroup
    if 'logGroup' in data:
        instance = str(data['logGroup']).replace('forensic-','')
        logging.info(data['logGroup'].replace('forensic-',''))
    else:
        instance = ''

    #Check each flow log
    if 'logEvents' in data:
        instance_ip ='none'
        instance_interface = 'none'
        for event in data['logEvents']:
            data = event['message'].split()
            if data[2] != instance_interface:  #check for change in network interface
                instance_ip = get_ip_by_nic(data[2])
                instance_interface = data[2]
                logging.info(data[2])
            eval_flow(event['message'],instance_ip)
    return "I'm done..."  # Echo back the first key value
    # raise Exception('Something went wrong')


