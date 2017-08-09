# Blue-Green deployments of infrastrcture and Application using SSM System Manager and Code* Services

Here are the steps to set up this sample

<b> <u> Part1: </u></b> CloudFormation template will create the initial Java based web application environment in a VPC. It also creates all the required components of Systems Manager Automation, CodeCommit, CodeBuild, and CodeDeploy to support the blue/green deployments of the infrastructure and application resulting from ongoing code releases. Here are the initial set of resources that would be created from this part1 CloudFromation stack:

	1.	A Java based web application running on EC2 instances loaded with CodeDeploy agents in an auto scaling group behind an elastic load balancer
	2.	Systems Manager Automation document that patches the supplied base AMI and create the golden AMI.
	3.	CodeCommit Repository to securely store code and files for your application.
	4.	CodeBuild project with configuration details on how AWS CodeBuild builds your source code
	5.	CodeDeploy DeploymentGroup with auto scaling group details of the web application EC2 instances
	6.	CodeDeploy application with deployment group with “automatically copy Auto Scaling group” setting
	7.	This part will also create the following Lambda functions: 
		a.	A function to get the Amazon provided SourceAMI ID based on region and architecture 
		b.	A function to update the Systems Manager parameter with the golden AMI ID 
		c.	A function to update the CodeBuild deployment group with necessary blue-green configurations (currently cloudformation does not have support for creating a deployment group with blue-green deployment configurations)

<b> <u> Part3: </u></b> CloudFormation template will create the AWS CodePipeline and all the requirements components with the following steps:

	1.	Source: Pipeline gets triggered from any changes to the codecommit repository
	2.	BuildGoldenAMI: This Lambda step executes the Systems Manager automation document to build the Golan AMI. Once the golden AMI is successfully created, a new launch configuration with the new AMI details will be updated into the Auto scaling group of the Application deployment group. 
	3.	Build: This builds the deployable application build artifact using the buildspec file of the application. 
	4.	Deploy: This steps clones the existing auto scaling group, launches  the new instances with the new AMI, deploys the application changes, reroutes the traffic from Elastic Load Balancer to the new instances and terminates the old auto scaling group. 
