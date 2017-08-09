from __future__ import print_function

import json
import boto3
import time
import datetime

print('Loading function')
ssm = boto3.client('ssm')
lambda_client = boto3.client('lambda')
code_pipeline = boto3.client('codepipeline')
client_autoscaling = boto3.client('autoscaling')
client_elb = boto3.client('elb')
client_codedeploy = boto3.client('codedeploy')

# Updates an SSM parameter
def lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))
    job_id = event['CodePipeline.job']['id']
    print("job_id: " + job_id)
    # Extract the Job Data
    job_data = event['CodePipeline.job']['data']
    # Extract the params
    params = get_user_params(job_data)

    ssm_document_name = params['ssm_document_name']
    elb_name = params['elb_name']
    iam_instanceprofile_name = params['iam_instanceprofile_name']
    deployment_group_name = params['deployment_group_name']
    application_name = params['application_name']

    try:
        if (_ssm_execution_exists_for_document(ssm_document_name)):
            automation_execution_id = _ssm_execution_id(ssm_document_name)
            print('An SSM execution is already in progress: ' + automation_execution_id)
            print('Not performing SSM automation execution')
        else:
            response = ssm.start_automation_execution(
                DocumentName=ssm_document_name
            )
            automation_execution_id = str(response['AutomationExecutionId'])
            print('started automation and automation_execution_id:' + automation_execution_id)

        while(_get_automation_execution_status(automation_execution_id) != 'Success' and _get_automation_execution_status(automation_execution_id) != 'Failed'):
            print("Time remaining (MS):", context.get_remaining_time_in_millis())
            if(context.get_remaining_time_in_millis() < 10000):
                continue_job_later(job_id,'Continue the job. SSM Document execution in progress:'+automation_execution_id)
                break
            time.sleep(5)

        if(_get_automation_execution_status(automation_execution_id) == 'Success'):
            result = updateASG(elb_name,iam_instanceprofile_name,deployment_group_name,application_name)
            if(result == 'SUCCESS'):
                put_job_success(job_id, 'SSM Document execution completed and ASG is updated with new golden AMI: ' + ssm_document_name)
            else:
                put_job_failure(job_id, 'SSM Document execution is completed. But, ASG update failed: ' + ssm_document_name)

        if(_get_automation_execution_status(automation_execution_id) == 'Failed'):
            put_job_failure(job_id, 'SSM Document execution failed: ' + ssm_document_name)

        return

    except Exception as e:
        print(e)
        #put_job_failure(job_id, 'Function exception: Failed ' + str(e))
        return

def updateASG(elb_name,iam_instanceprofile_name,deployment_group_name,application_name):
    ssm_client = boto3.client('ssm')
    try:
        print('going to get the parameter value of GoldenAMIID')
        response = ssm_client.get_parameters(Names=['GoldenAMIID'])
        golden_ami_id = response['Parameters'][0]['Value']
        print('golden_ami_id:' + response['Parameters'][0]['Value'])

        # get object for the ASG we're going to update, filter by name of target ASG
        response = client_codedeploy.get_deployment_group(applicationName=application_name,
                                                          deploymentGroupName=deployment_group_name)
        if not response['deploymentGroupInfo']['autoScalingGroups']:
            print('No such ASG')
        else:
            asg_name = response['deploymentGroupInfo']['autoScalingGroups'][0]['name']
            print(asg_name)

        # get the subnets list from the ELB
        response = client_elb.describe_load_balancers(LoadBalancerNames=[elb_name])
        subnetsString = ",".join(response['LoadBalancerDescriptions'][0]['Subnets'])
        print('subnetsString:' + subnetsString)
        sgString = ",".join(response['LoadBalancerDescriptions'][0]['SecurityGroups'])
        print('sgString:' + sgString)

        # create LC using instance from target ASG as a template, only diff is the name of the new LC and new AMI
        timeStamp = time.time()
        timeStampString = datetime.datetime.fromtimestamp(timeStamp).strftime('%Y-%m-%d  %H-%M-%S')
        newLaunchConfigName = 'LC ' + asg_name + ' ' + timeStampString
        print('newLaunchConfigName:' + newLaunchConfigName)
        response = client_autoscaling.create_launch_configuration(
            SecurityGroups=[sgString],
            LaunchConfigurationName=newLaunchConfigName,
            ImageId=golden_ami_id,
            InstanceType='t2.small',
            IamInstanceProfile=iam_instanceprofile_name)
        print('created new launch configuration with new AMI ID')
        print(response)
        # update ASG to use new LC
        response = client_autoscaling.update_auto_scaling_group(AutoScalingGroupName=asg_name,
                                                                LaunchConfigurationName=newLaunchConfigName,
                                                                VPCZoneIdentifier=subnetsString)
        # print('Updated ASG with old LC')
        print('Updated ASG `%s` with new launch configuration `%s` which includes AMI `%s`.' % (
            asg_name, newLaunchConfigName, golden_ami_id))
        return 'SUCCESS'

    except Exception as e:
        print(e)
        return 'ERROR'

def _ssm_execution_exists_for_document(ssm_document_name):
    """Determine whether an automation execution exists for a given
        document and status.

    Keyword arguments:
    ssm_document_name -- the name of the SSM document
    execution_status -- the SSM execution status
    """
    response = ssm.describe_automation_executions(
        Filters=[
            {
                'Key': 'DocumentNamePrefix',
                'Values': [
                    ssm_document_name,
                ]
            },
            {
                'Key': 'ExecutionStatus',
                'Values': ['Pending','InProgress',
                ]
            },
        ],
        MaxResults=1
    )
    if len(response['AutomationExecutionMetadataList']) == 0:
        return False
    else:
        thisExecutionID = response['AutomationExecutionMetadataList'][0]['AutomationExecutionId']
        return True

def _ssm_execution_id(ssm_document_name):
    """Determine whether an automation execution exists for a given
        document and status.

    Keyword arguments:
    ssm_document_name -- the name of the SSM document
    execution_status -- the SSM execution status
    """
    response = ssm.describe_automation_executions(
        Filters=[
            {
                'Key': 'DocumentNamePrefix',
                'Values': [
                    ssm_document_name,
                ]
            },
            {
                'Key': 'ExecutionStatus',
                'Values': ['Pending','InProgress',
                ]
            },
        ],
        MaxResults=1
    )

    return response['AutomationExecutionMetadataList'][0]['AutomationExecutionId']

def _get_automation_execution_status(automation_execution_id):
    """Returns the status of an SSM Automation execution.

    Keyword arguments:
    automation_execution_id -- the Automation execution ID
    """
    status = ''
    # Get automation execution
    response = ssm.get_automation_execution(
        AutomationExecutionId=automation_execution_id)
    ae = response['AutomationExecution']
    # Get automation execution status
    status = str(ae['AutomationExecutionStatus'])
    print('Status: {}'.format(status))
    return status

def put_job_success(job, message):
    """Notify CodePipeline of a successful job

    Args:
        job: The CodePipeline job ID
        message: A message to be logged relating to the job status

    Raises:
        Exception: Any exception thrown by .put_job_success_result()

    """
    print('Putting job success:' + job)
    print(message)
    code_pipeline.put_job_success_result(jobId=job,executionDetails={'summary': message})

def put_job_failure(job, message):
    """Notify CodePipeline of a failed job

    Args:
        job: The CodePipeline job ID
        message: A message to be logged relating to the job status

    Raises:
        Exception: Any exception thrown by .put_job_failure_result()

    """
    print('Putting job failure:' + job)
    print(message)
    code_pipeline.put_job_failure_result(jobId=job, failureDetails={'message': message, 'type': 'JobFailed'})

def continue_job_later(job, message):
    """Notify CodePipeline of a continuing job

    This will cause CodePipeline to invoke the function again with the
    supplied continuation token.

    Args:
        job: The JobID
        message: A message to be logged relating to the job status
        continuation_token: The continuation token

    Raises:
        Exception: Any exception thrown by .put_job_success_result()

    """

    # Use the continuation token to keep track of any job execution state
    # This data will be available when a new job is scheduled to continue the current execution
    continuation_token = json.dumps({'previous_job_id': job})
    print('continuation_token:' + continuation_token)
    print('Putting job continuation:' + job)
    print(message)
    code_pipeline.put_job_success_result(jobId=job, continuationToken=continuation_token)

def get_user_params(job_data):
    print(job_data)
    """Decodes the JSON user parameters and validates the required properties.

    Args:
        job_data: The job data structure containing the UserParameters string which should be a valid JSON structure

    Returns:
        The JSON parameters decoded as a dictionary.

    Raises:
        Exception: The JSON can't be decoded or a property is missing.

    """
    try:
        # Get the user parameters which contain the artifact and file settings
        user_parameters = job_data['actionConfiguration']['configuration']['UserParameters']
        print('user_parameters:' + user_parameters)
        decoded_parameters = json.loads(user_parameters)

    except Exception as e:
        # We're expecting the user parameters to be encoded as JSON
        # so we can pass multiple values. If the JSON can't be decoded
        # then fail the job with a helpful message.
        raise Exception('UserParameters could not be decoded as JSON')

    if 'ssm_document_name' not in decoded_parameters:
        # Validate that the artifact name is provided, otherwise fail the job
        # with a helpful message.
        raise Exception('Your UserParameters JSON must include the ssm_document_name')

    return decoded_parameters