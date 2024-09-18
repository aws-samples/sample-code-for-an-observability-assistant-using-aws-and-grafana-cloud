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
import hashlib
import uuid
import datetime
# from aws_cdk.custom_resources import (
#     AwsCustomResource,
#     AwsCustomResourcePolicy,
#     PhysicalResourceId,
#     AwsSdkCall
# )

class AossStack(Stack):

    def __init__(self, scope: Construct, id: str, bedrock_agent: bedrock.CfnAgent,  **kwargs) -> None:
        super().__init__(scope, id, **kwargs)
        
        # Create a unique string to create unique resource names
        # hash_base_string = (self.account + self.region)
        # hash_base_string = hash_base_string.encode("utf8")    

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
            name="bedrock-kb",
            description="An opensearch serverless vector database for the bedrock knowledgebase",
            standby_replicas="DISABLED",
            type="VECTORSEARCH"
        )

        opensearch_serverless_collection.add_dependency(opensearch_serverless_encryption_policy)
        opensearch_serverless_collection.add_dependency(opensearch_serverless_network_policy)

        CfnOutput(self, "OpenSearchCollectionArn",
            value=opensearch_serverless_collection.attr_arn,
            export_name="OpenSearchCollectionArn"
        )

        CfnOutput(self, "OpenSearchCollectionEndpoint",
            value=opensearch_serverless_collection.attr_collection_endpoint,
            export_name="OpenSearchCollectionEndpoint"
        )

        ### 2. Creating an IAM role and permissions that we will need later on
        
        # bedrock_role_arn = bedrock_agent.agent_resource_role_arn
        # Fn.import_value("BedrockAgentRoleArn")

        # Create a bedrock knowledgebase role. Creating it here so we can reference it in the access policy for the opensearch serverless collection
        bedrock_kb_role = iam.Role(self, 'bedrock-kb-role',
            # role_name=("bedrock-kb-role-" + str(hashlib.sha384(hash_base_string).hexdigest())[:15]).lower(),
            assumed_by=iam.ServicePrincipal('bedrock.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonBedrockFullAccess'),
            #     # iam.ManagedPolicy.from_aws_managed_policy_name('AmazonOpenSearchServiceFullAccess'),
            #     # iam.ManagedPolicy.from_aws_managed_policy_name('AmazonS3FullAccess'),
            #     # iam.ManagedPolicy.from_aws_managed_policy_name('CloudWatchLogsFullAccess'),
            ],
        )

        # bedrock_kb_role.add_to_policy(
        #     iam.PolicyStatement(
        #         effect=iam.Effect.ALLOW,
        #         actions=["aoss:APIAccessAll"],
        #         resources=[bedrock_agent.foundation_model],
        #     )
        # )
        

        # Add inline permissions to the bedrock knowledgebase execution role      
        bedrock_kb_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["aoss:APIAccessAll"],
                resources=[opensearch_serverless_collection.attr_arn],
            )
        )

        # bedrock_kb_role_arn = bedrock_kb_role.role_arn
        
        # CfnOutput(self, "BedrockKbRoleArn",
        #     value=bedrock_kb_role_arn,
        #     export_name="BedrockKbRoleArn"
        # )    

        ### 3. Create a custom resource that creates a new index in the opensearch serverless collection

        # Define the index name
        index_name = "kb-docs"
        
        # Define the Lambda function that creates a new index in the opensearch serverless collection
        create_index_lambda = _lambda.Function(
            self, "Index",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler='indexer.handler',
            code=_lambda.Code.from_asset(
                "stacks/bedrock_knowledgebase/lambda",
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
        
        # Create a Lambda layer that contains the requests library, which we use to call the OpenSearch Serverless API
        # layer = _lambda.LayerVersion(
        #     self, 'py-lib-layer-for-index',
        #     code=_lambda.Code.from_asset('stack/bedrock_knowledgebase/indexer_lambda'),
        #     compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
        # )

        # # Add the layer to the search lambda function
        # create_index_lambda.add_layers(layer)
        
        # Finally we can create a complete data access policy for the collection that also includes the lambda function that will create the index. The policy must be a string and the resource contains the collections it is applied to.
        opensearch_serverless_access_policy = opensearchserverless.CfnAccessPolicy(self, "OpenSearchServerlessAccessPolicy",
            name=f"grafana-kb-data-access-policy",
            policy=f"[{{\"Description\":\"Access for bedrock\",\"Rules\":[{{\"ResourceType\":\"index\",\"Resource\":[\"index/{opensearch_serverless_collection.name}/*\"],\"Permission\":[\"aoss:*\"]}},{{\"ResourceType\":\"collection\",\"Resource\":[\"collection/{opensearch_serverless_collection.name}\"],\"Permission\":[\"aoss:*\"]}}],\"Principal\":[\"{bedrock_agent.agent_resource_role_arn}\",\"{bedrock_kb_role.role_arn}\",\"{create_index_lambda.role.role_arn}\"]}}]",
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

        create_bedrock_kb_lambda = _lambda.Function(
            self, "BedrockKbLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            function_name="bedrock-kb-creator-custom-function",
            handler='knowledgebase.handler',
            timeout=Duration.minutes(5),
            code=_lambda.Code.from_asset(
                "stacks/bedrock_knowledgebase/lambda",
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
            environment={
                "BEDROCK_KB_ROLE_ARN": bedrock_kb_role.role_arn,
                "COLLECTION_ARN": opensearch_serverless_collection.attr_arn,
                "INDEX_NAME": index_name,
                "REGION": self.region,
            }
        )

        # Define IAM permission policy for the Lambda function. This function calls the OpenSearch Serverless API to create a new index in the collection and must have the "aoss" permissions. 
        create_bedrock_kb_lambda.role.add_to_principal_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock:CreateKnowledgeBase","iam:PassRole", "bedrock:DeleteKnowledgeBase", "bedrock:CreateDataSource"
            ],
            resources=["*"],
        ))   

        #Create a IAM role to be used by Provider Lambda function
        provider_lambda_role = iam.Role(self, 'ProviderLambdaRole',
            assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSLambdaBasicExecutionRole'),
            ],
        )

        trigger_create_kb_lambda_provider = cr.Provider(self,"BedrockKbLambdaProvider",
                                                  on_event_handler=create_bedrock_kb_lambda,
                                                  provider_function_name="custom-lambda-provider")
        trigger_create_kb_lambda_cr = CustomResource(self, "BedrockKbCustomResourceTrigger",
                                                  service_token=trigger_create_kb_lambda_provider.service_token)
        
        
        # On creation of the stack, trigger the Lambda function we just defined 
        # trigger_create_kb_lambda_cr = cr.AwsCustomResource(self, "BedrockKBCustomResource",
        #     function_name=create_bedrock_kb_lambda.function_name,
        #     # on_create=cr.AwsSdkCall(
        #     #     service="Lambda",
        #     #     action="invoke",
        #     #     parameters=createKbLambdaParams,
        #     #     physical_resource_id=cr.PhysicalResourceId.of("Payload.knowledgeBase.knowledgeBaseId")
        #     #     ),
        #     # policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
        #     #     resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
        #     #     ),
        #     removal_policy = RemovalPolicy.DESTROY,
        #     timeout=Duration.seconds(120)
        #     )

        # # Define IAM permission policy for the custom resource    
        # trigger_create_kb_lambda_cr.grant_principal.add_to_principal_policy(iam.PolicyStatement(
        #     effect=iam.Effect.ALLOW,
        #     actions=["bedrock:*", "iam:CreateServiceLinkedRole", "iam:PassRole"],
        #     resources=["*"],
        #     )
        # )  

        trigger_create_kb_lambda_cr.node.add_dependency(bedrock_kb_role)
        trigger_create_kb_lambda_cr.node.add_dependency(opensearch_serverless_collection)
        trigger_create_kb_lambda_cr.node.add_dependency(create_bedrock_kb_lambda)
        trigger_create_kb_lambda_cr.node.add_dependency(opensearch_serverless_access_policy)

        # res = cr.AwsCustomResource(self,"BedrockKB",
        #                         #    role=custom_lambda_role,
        #     policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
        #         resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
        #     ),
        #     install_latest_aws_sdk=True,
        #     # policy=cr.AwsCustomResourcePolicy.from_statements(
        #     #     statements=[
        #     #         iam.PolicyStatement(
        #     #             effect=iam.Effect.ALLOW,
        #     #             actions=["bedrock:CreateKnowledgeBase"],
        #     #             resources=["*"]
        #     #         )
        #     #     ]
        #     # ),
        #     # log_retention=logs.RetentionDays.INFINITE,
        #     on_update=cr.AwsSdkCall(
        #         # physical_resource_id=cr.PhysicalResourceId.of(Date.now().to_string())),
        #         service='Bedrock-Agent',
        #         action='CreateKnowledgeBase',
        #         parameters={
        #             'Name': 'grafana-bedrock-kb-docs',
        #             'Description': 'This knowledge base can be used to understand how to generate a PromQL or LogQL.',
        #             'RoleArn': bedrock_kb_role.role_arn,
        #             'KnowledgeBaseConfiguration': {
        #                 'Type': 'VECTOR',
        #                 'VectorKnowledgeBaseConfiguration': {
        #                     'EmbeddingModelArn': f'arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v1',
        #                 },
        #             },
        #             'StorageConfiguration': {
        #                 'Type': 'OPENSEARCH_SERVERLESS',
        #                 'OpenSearchServerlessConfiguration': {
        #                     'CollectionArn': opensearch_serverless_collection.attr_arn,
        #                     'VectorIndexName': index_name,
        #                     'FieldMapping': {
        #                         'MetadataField': 'metadataField',
        #                         'TextField': 'textField',
        #                         'VectorField': 'vectorField',
        #                     },
        #                 },
        #             },
        #         },
        #         physical_resource_id=cr.PhysicalResourceId.of("Parameter.knowledgeBaseId")
        #     ),
        # )

        # res.grant_principal.add_to_principal_policy(iam.PolicyStatement(
        #     effect=iam.Effect.ALLOW,
        #     actions=["bedrock:CreateKnowledgeBase"],
        #     resources=["*"],
        #     )
        # )  

        
        # Create the bedrock knowledgebase with the role arn that is referenced in the opensearch data access policy
        # bedrock_knowledge_base = bedrock.CfnKnowledgeBase(self, "KnowledgeBaseDocs",
        #     name="grafana-bedrock-kb-docs",
        #     description="This knowledge base can be used to understand how to generate a PromQL or LogQL.",
        #     role_arn=bedrock_kb_role.role_arn,
        #     knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
        #         type="VECTOR",
        #         vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
        #             embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v1"
        #         ),
        #     ),
        #     storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
        #         type="OPENSEARCH_SERVERLESS",
        #         opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
        #             collection_arn=opensearch_serverless_collection.attr_arn,
        #             vector_index_name=index_name,
        #             field_mapping = bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
        #                 metadata_field="metadataField",
        #                 text_field="textField",
        #                 vector_field="vectorField"
        #                 )
        #             ),
        #         ),
        # )

        # bedrock_knowledge_base.apply_removal_policy(RemovalPolicy.DESTROY)

        

        # # Create the data source for the bedrock knowledge base. Chunking max tokens of 300 is bedrock's sensible default.
        # kb_data_source = bedrock.CfnDataSource(self, "PromqlDataSource",
        #     name="promql-datasource",
        #     knowledge_base_id=bedrock_knowledge_base.ref,
        #     description="The Web data source for understanding how promql statements be constructed",
        #     data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
        #         type="WEB",
        #         web_configuration = bedrock.CfnDataSource.WebDataSourceConfigurationProperty(
        #             source_configuration=bedrock.CfnDataSource.WebSourceConfigurationProperty(
        #                 url_configuration=bedrock.CfnDataSource.UrlConfigurationProperty(
        #                     seed_urls=[bedrock.CfnDataSource.SeedUrlProperty(
        #                         url="https://promlabs.com/promql-cheat-sheet/"
        #                     ),
        #                     bedrock.CfnDataSource.SeedUrlProperty(
        #                         url="https://isitobservable.io/observability/prometheus/how-to-build-a-promql-prometheus-query-language"
        #                     ),
        #                     bedrock.CfnDataSource.SeedUrlProperty(
        #                         url="https://prometheus.io/docs/prometheus/latest/querying/"
        #                     ),
        #                     bedrock.CfnDataSource.SeedUrlProperty(
        #                         url="https://grafana.com/docs/loki/latest/query/"
        #                     ),
        #                     bedrock.CfnDataSource.SeedUrlProperty(
        #                         url="https://github.com/grafana/loki/tree/main/docs/sources/query"
        #                     )]
        #                 ),
        #             ),
        #             crawler_configuration = bedrock.CfnDataSource.WebCrawlerConfigurationProperty(
        #                 crawler_limits=bedrock.CfnDataSource.WebCrawlerLimitsProperty(
        #                     rate_limit=300
        #                 ),
        #             # scope="scope"
        #             )
        #         ),
                
                
        #     ),
        #     vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
        #         chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
        #             chunking_strategy="FIXED_SIZE",
        #             fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
        #                 max_tokens=300,
        #                 overlap_percentage=20
        #             )
        #         )
        #     )
        # )

        # vector_ingestion_configuration.add_dependency(bedrock_knowledge_base)