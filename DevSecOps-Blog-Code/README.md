# DevSecOps in the CI/CD pipeline

Here are the steps to set up the pipeline and try this sample

1. Create your own S3 bucket in the desired region and enable versioning on the bucket 
2. Extract the files from codepipe-single-sg.zip and update the "test-stack-configuration.json" and "prod-stack-configuration.json" files with your VPC Names. Create new "codepipe-single-sg.zip" file. 
2. Upload the codepipe-single-sg.zip and codepipeline-lambda.zip files into S3 bucket
3. Run the "basic-sg-3-cfn.json" in the CloudFormation service to create the pipeline and it's execution starts automatically
