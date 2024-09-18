from aws_cdk import (
    Duration,
    Stack,
    CfnOutput,
    RemovalPolicy,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_opensearchserverless as opensearchserverless,
    Fn as Fn,
    custom_resources as cr,
    BundlingOptions,
    aws_bedrock as bedrock,
    CustomResource,
    RemovalPolicy,
)
from constructs import Construct

class AossStack(Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)
      
        ### 1. Create an opensearch serverless collection
        
        # Creating an opensearch serverless collection requires a security policy of type encryption. The policy must be a string and the resource contains the collections it is applied to.
        opensearch_serverless_encryption_policy = opensearchserverless.CfnSecurityPolicy(self, "OpenSearchServerlessEncryptionPolicy",
            name="encryption-policy",
            policy="{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/*\"]}],\"AWSOwnedKey\":true}",
            type="encryption",
            description="the encryption policy for the opensearch serverless collection"
        )

        # We also need a security policy of type network so that the collection becomes accessable. The policy must be a string and the resource contains the collections it is applied to.
        opensearch_serverless_network_policy = opensearchserverless.CfnSecurityPolicy(self, "OpenSearchServerlessNetworkPolicy",
            name="network-policy",
            policy="[{\"Description\":\"Public access for collection\",\"Rules\":[{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/*\"]},{\"ResourceType\":\"collection\",\"Resource\":[\"collection/*\"]}],\"AllowFromPublic\":true}]",
            type="network",
            description="the network policy for the opensearch serverless collection"
        )
        
        # Creating an opensearch serverless collection        
        opensearch_serverless_collection = opensearchserverless.CfnCollection(self, "OpenSearchServerless",
            name="observability-assistant-kb",
            description="An opensearch serverless vector database for the bedrock knowledgebase",
            standby_replicas="DISABLED",
            type="VECTORSEARCH"
        )

        opensearch_serverless_collection.add_dependency(opensearch_serverless_encryption_policy)
        opensearch_serverless_collection.add_dependency(opensearch_serverless_network_policy)

        self.opensearch_serverless_collection=opensearch_serverless_collection
        ### 2. Creating an IAM role and permissions that we will need later on

        
        ### 3. Create a custom resource that creates a new index in the opensearch serverless collection

        # Define the index name
        index_name = "kb-docs"
        
        # Define the Lambda function that creates a new index in the opensearch serverless collection
        create_index_lambda = _lambda.Function(
            self, "Index",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler='indexer.handler',
            code=_lambda.Code.from_asset(
                "stacks/opensearch/lambda",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    platform="linux/arm64",
                    command=[
                        "bash",
                        "-c",
                        "pip install --no-cache -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            timeout=Duration.seconds(60),
            environment={
                "COLLECTION_ENDPOINT": opensearch_serverless_collection.attr_collection_endpoint,
                "INDEX_NAME": index_name,
                "REGION": self.region,
            }
        )

        # Define IAM permission policy for the Lambda function. This function calls the OpenSearch Serverless API to create a new index in the collection and must have the "aoss" permissions. 
        create_index_lambda.role.add_to_principal_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "es:ESHttpPut", 
                "es:*", 
                "iam:CreateServiceLinkedRole", 
                "iam:PassRole", 
                "iam:ListUsers",
                "iam:ListRoles", 
                "aoss:APIAccessAll",
                "aoss:*"
            ],
            resources=["*"],
        ))   
        
        opensearch_serverless_access_policy = opensearchserverless.CfnAccessPolicy(self, "IndexerLambdaDataPolicy",
            name=f"indexer-lambda-policy",
            policy=f"[{{\"Description\":\"Access for bedrock\",\"Rules\":[{{\"ResourceType\":\"index\",\"Resource\":[\"index/{opensearch_serverless_collection.name}/*\"],\"Permission\":[\"aoss:*\"]}},{{\"ResourceType\":\"collection\",\"Resource\":[\"collection/{opensearch_serverless_collection.name}\"],\"Permission\":[\"aoss:*\"]}}],\"Principal\":[\"{create_index_lambda.role.role_arn}\"]}}]",
            type="data",
            description="the data access policy for the opensearch serverless collection"
        )

        opensearch_serverless_access_policy.add_dependency(opensearch_serverless_collection)        

        # Define the request body for the lambda invoke api call that the custom resource will use
        aossLambdaParams = {
                    "FunctionName": create_index_lambda.function_name,
                    "InvocationType": "RequestResponse"
                }
        
        # On creation of the stack, trigger the Lambda function we just defined 
        trigger_lambda_cr = cr.AwsCustomResource(self, "IndexCreateCustomResource",
            on_create=cr.AwsSdkCall(
                service="Lambda",
                action="invoke",
                parameters=aossLambdaParams,
                physical_resource_id=cr.PhysicalResourceId.of("Parameter.ARN")
                ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
                ),
            removal_policy = RemovalPolicy.DESTROY,
            timeout=Duration.seconds(120)
            )

        # Define IAM permission policy for the custom resource    
        trigger_lambda_cr.grant_principal.add_to_principal_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["lambda:*", "iam:CreateServiceLinkedRole", "iam:PassRole"],
            resources=["*"],
            )
        )  
        
        # Only trigger the custom resource after the opensearch access policy has been applied to the collection    
        trigger_lambda_cr.node.add_dependency(opensearch_serverless_access_policy)
        trigger_lambda_cr.node.add_dependency(opensearch_serverless_collection)

        