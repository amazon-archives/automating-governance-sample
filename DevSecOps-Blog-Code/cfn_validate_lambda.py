from __future__ import print_function
from boto3.session import Session

import json
import urllib
import boto3
import zipfile
import tempfile
import botocore
import traceback
import re
import zipfile
import time

print('Loading function')

cf = boto3.client('cloudformation')
code_pipeline = boto3.client('codepipeline')

def find_artifact(artifacts, name):
    """Finds the artifact 'name' among the 'artifacts'

    Args:
        artifacts: The list of artifacts available to the function
        name: The artifact we wish to use
    Returns:
        The artifact dictionary found
    Raises:
        Exception: If no matching artifact is found

    """
    for artifact in artifacts:
        if artifact['name'] == name:
            return artifact

    raise Exception('Input artifact named "{0}" not found in event'.format(name))


def get_template(s3, artifact, file_in_zip):
    """Gets the template artifact

    Downloads the artifact from the S3 artifact store to a temporary file
    then extracts the zip and returns the file containing the CloudFormation
    template.

    Args:
        artifact: The artifact to download
        file_in_zip: The path to the file within the zip containing the template

    Returns:
        The CloudFormation template as a string

    Raises:
        Exception: Any exception thrown while downloading the artifact or unzipping it

    """
    tmp_file = tempfile.NamedTemporaryFile()
    bucket = artifact['location']['s3Location']['bucketName']
    key = artifact['location']['s3Location']['objectKey']

    with tempfile.NamedTemporaryFile() as tmp_file:
        print("Retrieving s3://" + bucket + "/" + key)
        s3.download_file(bucket, key, tmp_file.name)
        with zipfile.ZipFile(tmp_file.name, 'r') as zip:
            zip.printdir()
            return zip.read(file_in_zip)


def put_job_success(job, message):
    """Notify CodePipeline of a successful job

    Args:
        job: The CodePipeline job ID
        message: A message to be logged relating to the job status

    Raises:
        Exception: Any exception thrown by .put_job_success_result()

    """
    print('Putting job success')
    print(message)
    code_pipeline.put_job_success_result(jobId=job)

def put_job_failure(job, message):
    """Notify CodePipeline of a failed job

    Args:
        job: The CodePipeline job ID
        message: A message to be logged relating to the job status

    Raises:
        Exception: Any exception thrown by .put_job_failure_result()

    """
    print('Putting job failure')
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

    print('Putting job continuation')
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
        decoded_parameters = json.loads(user_parameters)

    except Exception as e:
        # We're expecting the user parameters to be encoded as JSON
        # so we can pass multiple values. If the JSON can't be decoded
        # then fail the job with a helpful message.
        raise Exception('UserParameters could not be decoded as JSON')

    if 'input' not in decoded_parameters:
        # Validate that the artifact name is provided, otherwise fail the job
        # with a helpful message.
        raise Exception('Your UserParameters JSON must include the artifact name')

    if 'file' not in decoded_parameters:
        # Validate that the template file is provided, otherwise fail the job
        # with a helpful message.
        raise Exception('Your UserParameters JSON must include the template file name')

    if 'output' not in decoded_parameters:
        # Validate that the template file is provided, otherwise fail the job
        # with a helpful message.
        raise Exception('Your UserParameters JSON must include the output bucket')    

    return decoded_parameters

def setup_s3_client(job_data):
    """Creates an S3 client

    Uses the credentials passed in the event by CodePipeline. These
    credentials can be used to access the artifact bucket.

    Args:
        job_data: The job data structure

    Returns:
        An S3 client with the appropriate credentials

    """
    key_id = job_data['artifactCredentials']['accessKeyId']
    key_secret = job_data['artifactCredentials']['secretAccessKey']
    session_token = job_data['artifactCredentials']['sessionToken']

    session = Session(
        aws_access_key_id=key_id,
        aws_secret_access_key=key_secret,
        aws_session_token=session_token)
    return session.client('s3', config=botocore.client.Config(signature_version='s3v4'))

def get_rules():
    # Find table
    client = boto3.client('dynamodb')
    resource = boto3.resource('dynamodb')
    response = client.list_tables()
    logTable = ""
    for i in range(len(response['TableNames'])):
        if "lab3DDBRules" in response['TableNames'][i]:
            logTable = response['TableNames'][i]

    # Verify that rules are created and if not, create them
    response = client.scan(
        TableName=logTable,
        AttributesToGet=[
            'rule',
        ]
    )
    if len(response['Items']) == 0:
        add_rules(logTable)
        time.sleep(45)

    # Get all rules from DDB.
    # Rules have rule, ruledata, type and weight
    rules = dict()
    sgRules = []
    ec2Rules = []

    for n in range(len(response['Items'])):
        rule = client.get_item(
            TableName=logTable,
            Key={
                'rule': {'S':response['Items'][n]['rule']['S']}
            },
            ConsistentRead=True
        )['Item']
        if rule['category']['S'] == "SecurityGroup":
            sgRules.append(rule)
        elif rule['category']['S'] == "EC2Instance":
            ec2Rules.append(rule)
    rules['sgRules'] = sgRules
    rules['ec2Rules'] = ec2Rules
    return rules


def add_rules(logTable):
    client = boto3.client('dynamodb')
    client.put_item(
        TableName=logTable,
        Item={
            'rule' : {'S': "IngressOpenToWorld"},
            'category' : {'S': "SecurityGroup"},
            'ruletype' : {'S': "regex"},
            'ruledata' : {'S': "^.*Ingress.*((0\.){3}0\/0)"},
            'riskvalue' : {'N': "100"},
            'active' : {'S': "Y"}
        }
    )

    client.put_item(
        TableName=logTable,
        Item={
            'rule' : {'S': "SSHOpenToWorld"},
            'category' : {'S': "SecurityGroup"},
            'ruletype' : {'S': "regex"},
            'ruledata' : {'S': "^.*Ingress.*(([fF]rom[pP]ort|[tT]o[pP]ort).\s*:\s*u?.(22).*[cC]idr[iI]p.\s*:\s*u?.((0\.){3}0\/0)|[cC]idr[iI]p.\s*:\s*u?.((0\.){3}0\/0).*([fF]rom[pP]ort|[tT]o[pP]ort).\s*:\s*u?.(22))"},
            'riskvalue' : {'N': "100"},
            'active' : {'S': "Y"}
        }
    )
    client.put_item(
        TableName=logTable,
        Item={
            'rule' : {'S': "AllowHttp"},
            'category' : {'S': "SecurityGroup"},
            'ruletype' : {'S': "regex"},
            'ruledata' : {'S': "^.*Ingress.*[fF]rom[pP]ort.\s*:\s*u?.(80)"},
            'riskvalue' : {'N': "3"},
            'active' : {'S': "N"}
        }
    )
    client.put_item(
        TableName=logTable,
        Item={
            'rule' : {'S': "ForbiddenAMIs"},
            'category' : {'S': "EC2Instance"},
            'ruletype' : {'S': "regex"},
            'ruledata' : {'S': "^.*ImageId.\s*:\s*u?.(ami-7a11e211|ami-08111162|ami-f6035893)"},
            'riskvalue' : {'N': "10"},
            'active' : {'S': "N"}
        }
    )


def evaluate_template(rules, template):
    # Validate rules and increase risk value
    risk = 0
    # Extract Security Group Resources
    sgResources = []
    ec2Resources = []
    failedRules = []
    jsonTemplate = json.loads(template)
    print(json.dumps(jsonTemplate, sort_keys=True, indent=4, separators=(',', ': ')))
    print(rules)
    for key in jsonTemplate['Resources'].keys():
        if "SecurityGroup" in jsonTemplate['Resources'][key]['Type']:
            sgResources.append(jsonTemplate['Resources'][key])
        elif "EC2::Instance" in jsonTemplate['Resources'][key]['Type']:
            ec2Resources.append(jsonTemplate['Resources'][key])

    for n in range(len(sgResources)):
        for m in range(len(rules['sgRules'])):
            if rules['sgRules'][m]['active']['S'] == "Y":
                if re.match(rules['sgRules'][m]['ruledata']['S'], str(sgResources[n])):
                    risk = risk + int(rules['sgRules'][m]['riskvalue']['N'])
                    failedRules.append(str(rules['sgRules'][m]['rule']['S']))
                    print("Matched rule: " + str(rules['sgRules'][m]['rule']['S']))
                    print("Resource: " + str(sgResources[n]))
                    print("Riskvalue: " + rules['sgRules'][m]['riskvalue']['N'])
                    print("")

    for n in range(len(ec2Resources)):
        for m in range(len(rules['ec2Rules'])):
            if rules['ec2Rules'][m]['active']['S'] == "Y":
                if re.match(rules['ec2Rules'][m]['ruledata']['S'], str(ec2Resources[n])):
                    risk = risk + int(rules['ec2Rules'][m]['riskvalue']['N'])
                    failedRules.append(str(rules['ec2Rules'][m]['rule']['S']))
                    print("Matched rule: " + str(rules['ec2Rules'][m]['rule']['S']))
                    print("Resource: " + str(ec2Resources[n]))
                    print("Riskvalue: " + rules['ec2Rules'][m]['riskvalue']['N'])
                    print("")
    print("Risk value: " +str(risk))
    return risk, failedRules

def s3_next_step(s3, bucket, risk, failedRules, template, job_id):
    # Store data in temporary physical file
    s3Client = boto3.client('s3', config=botocore.client.Config(signature_version='s3v4'))
    tmp_file = tempfile.NamedTemporaryFile()
    tmp_zip = tempfile.NamedTemporaryFile()
    for item in template:
        tmp_file.write(item)
    tmp_file.flush()
    # Process file based on risk value
    if risk < 5:
        with zipfile.ZipFile(tmp_zip.name, 'w') as zip:
            zip.write(tmp_file.name, "valid.template.json")
            zip.close()
            s3Client.upload_file( # Add encryption support
                tmp_zip.name,
                bucket,
                'valid.template.zip')
        tmp_file.close()
        put_job_success(job_id, 'Job succesful, minimal or no risk detected.')
    elif 5 <= risk < 50:
        with zipfile.ZipFile(tmp_zip.name, 'w') as zip:
            zip.write(tmp_file.name, "flagged.template.json")
            zip.close()
            s3Client.upload_file( # Add encryption support
                tmp_zip.name,
                bucket,
                'flagged.template.zip')
        tmp_file.close()
        put_job_success(job_id, 'Job succesful, medium risk detected, manual approval needed.')
    elif risk >= 50:
        tmp_file.close()
        print("High risk file, fail pipeline")
        put_job_failure(job_id, 'Function exception: Failed filters ' + str(failedRules))
    return 0


def lambda_handler(event, context):
    """The Lambda function handler

    Validate input template for security vulnerables.  Route as appropriate based on risk assesment.

    Args:
        event: The event passed by Lambda
        context: The context passed by Lambda

    """
    try:
        # Print the entire event for tracking
        print("Received event: " + json.dumps(event, indent=2))

        # Extract the Job ID
        job_id = event['CodePipeline.job']['id']

        # Extract the Job Data
        job_data = event['CodePipeline.job']['data']

        # Extract the params
        params = get_user_params(job_data)

        # Get the list of artifacts passed to the function
        input_artifacts = job_data['inputArtifacts']

        input_artifact = params['input']
        template_file = params['file']
        output_bucket = params['output']

        # Get the artifact details
        input_artifact_data = find_artifact(input_artifacts, input_artifact)

        # Get S3 client to access artifact with
        s3 = setup_s3_client(job_data)

        # Get the JSON template file out of the artifact
        template = get_template(s3, input_artifact_data, template_file)
        print("Template: " + template)

        # Get validation rules from DDB
        rules = get_rules()

        # Validate template from risk perspective. FailedRules can be used if you wish to expand the script to report failed items
        risk, failedRules = evaluate_template(rules, template)

        # Based on risk, store the template in the correct S3 bucket for future process
        s3_next_step(s3, output_bucket, risk, failedRules, template, job_id)

    except Exception as e:
        # If any other exceptions which we didn't expect are raised
        # then fail the job and log the exception message.
        print('Function failed due to exception.')
        print(e)
        traceback.print_exc()
        put_job_failure(job_id, 'Function exception: ' + str(e))

    print('Function complete.')
    return "Complete."
