from __future__ import print_function

import json
import boto3
import requests

print('Loading function')


# Updates an SSM parameter
# Expects parameterName, parameterValue
def lambda_handler(event, context):
    responseStatus = 'SUCCESS'
    responseData = {}
    print("Received event: " + json.dumps(event, indent=2))
    print('applicationName: '+  event['ResourceProperties']['applicationName'])
    print('currentDeploymentGroupName: ' + event['ResourceProperties']['currentDeploymentGroupName'])
    print('elbName: ' + event['ResourceProperties']['elbName'])
    print('asgName: ' + event['ResourceProperties']['asgName'])

    # get SSM client
    client = boto3.client('codedeploy')

    # confirm  parameter exists before updating it
    try:
        response = client.update_deployment_group(
            applicationName=event['ResourceProperties']['applicationName'],
            currentDeploymentGroupName=event['ResourceProperties']['currentDeploymentGroupName'],
            autoScalingGroups=[event['ResourceProperties']['asgName']],
            deploymentStyle={
                'deploymentType': 'BLUE_GREEN',
                'deploymentOption': 'WITH_TRAFFIC_CONTROL'
            },
            blueGreenDeploymentConfiguration={
                'terminateBlueInstancesOnDeploymentSuccess': {
                    'action': 'TERMINATE',
                    'terminationWaitTimeInMinutes': 5
                },
                'deploymentReadyOption': {
                    'actionOnTimeout': 'CONTINUE_DEPLOYMENT'
                },
                'greenFleetProvisioningOption': {
                    'action': 'COPY_AUTO_SCALING_GROUP'
                }
            },
            loadBalancerInfo = {'elbInfoList': [{'name': event['ResourceProperties']['elbName']}]}
        )


        if not response['hooksNotCleanedUp']:
            responseData = {'Success': 'Updated Deployment Group'}
            reponseString = 'SUCCESS: Updated Deployment Group'
        else:
            responseData = {'Failure': 'Not Updated Deployment Group'}
            reponseString = 'FAILED: Not Updated Deployment Group'

    except Exception as e:
        print(e)
        responseData = {'Failure': 'Not Updated Deployment Group'}
        reponseString = 'FAILED: Not Updated Deployment Group'

    sendResponse(event, context, responseStatus, responseData)
    print(reponseString)
    return reponseString

def sendResponse(event, context, responseStatus, responseData):
    responseBody = {'Status': responseStatus,
                    'Reason': 'See the details in CloudWatch Log Stream: ' + context.log_stream_name,
                    'PhysicalResourceId': context.log_stream_name,
                    'StackId': event['StackId'],
                    'RequestId': event['RequestId'],
                    'LogicalResourceId': event['LogicalResourceId'],
                    'Data': responseData}
    print ('RESPONSE BODY:n' + json.dumps(responseBody))
    try:
        req = requests.put(event['ResponseURL'], data=json.dumps(responseBody))
        if req.status_code != 200:
            print (req.text)
            raise Exception('Recieved non 200 response while sending response to CFN.')
        return
    except requests.exceptions.RequestException as e:
        print(e)
        raise