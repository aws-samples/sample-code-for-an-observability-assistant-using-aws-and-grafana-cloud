# CDK Stack that creates Bedrock Agent and Knowledgebases
import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    CfnOutput,
    aws_iam as iam,
    aws_bedrock as bedrock,
    ArnFormat,
    CustomResource,
    Duration,
    BundlingOptions,
    aws_opensearchserverless as opensearchserverless,
    RemovalPolicy,
    custom_resources as cr,
)
import hashlib

class ObservabilityAssistantAgent(cdk.Stack):

    def __init__(self, 
                 scope: Construct, 
                 construct_id: str,
                 metrics_lambda: _lambda.Function,
                 opensearch_serverless_collection: opensearchserverless.CfnCollection,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        index_name = "kb-docs"
        # Create a bedrock knowledgebase role. Creating it here so we can reference it in the access policy for the opensearch serverless collection
        bedrock_kb_role = iam.Role(self, 'bedrock-kb-role',
            assumed_by=iam.ServicePrincipal('bedrock.amazonaws.com'),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name('AmazonBedrockFullAccess')
            ],
        )


        # Add inline permissions to the bedrock knowledgebase execution role      
        bedrock_kb_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["aoss:APIAccessAll"],
                resources=[opensearch_serverless_collection.attr_arn],
            )
        )

        #Create a Bedrock agent execution role
        agent_role = iam.Role(
            self,
            "agent-role",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Role for Bedrock based observability assistant",
        )

        bedrock_aoss_access_policy = opensearchserverless.CfnAccessPolicy(self, "BedrockAgentAccessPolicy",
            name=f"bedrock-agent-access-policy",
            policy=f"[{{\"Description\":\"Access for bedrock\",\"Rules\":[{{\"ResourceType\":\"index\",\"Resource\":[\"index/{opensearch_serverless_collection.name}/*\"],\"Permission\":[\"aoss:*\"]}},{{\"ResourceType\":\"collection\",\"Resource\":[\"collection/{opensearch_serverless_collection.name}\"],\"Permission\":[\"aoss:*\"]}}],\"Principal\":[\"{agent_role.role_arn}\",\"{bedrock_kb_role.role_arn}\"]}}]",
            type="data",
            description="the data access policy for the opensearch serverless collection"
        )

        create_bedrock_kb_lambda = _lambda.Function(
            self, "BedrockKbLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            function_name="bedrock-kb-creator-custom-function",
            handler='knowledgebase.handler',
            timeout=Duration.minutes(5),
            code=_lambda.Code.from_asset(
                "stacks/bedrock_agent/lambda",
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
                    "bedrock:CreateDataSource",
                    "bedrock:CreateKnowledgeBase",
                    "bedrock:DeleteKnowledgeBase",
                    "bedrock:GetDataSource",
                    "bedrock:GetKnowledgeBase",
                    "bedrock:StartIngestionJob",
                    "iam:PassRole"
            ],
            resources=["*"],
        ))   


        trigger_create_kb_lambda_provider = cr.Provider(self,"BedrockKbLambdaProvider",
                                                  on_event_handler=create_bedrock_kb_lambda,
                                                  provider_function_name="custom-lambda-provider",
                                                  )
        trigger_create_kb_lambda_cr = CustomResource(self, "BedrockKbCustomResourceTrigger",
                                                  service_token=trigger_create_kb_lambda_provider.service_token,
                                                  removal_policy=RemovalPolicy.DESTROY,
                                                  resource_type="Custom::BedrockKbCustomResourceTrigger",
                                                  )
        
        trigger_create_kb_lambda_cr.node.add_dependency(bedrock_kb_role)
        trigger_create_kb_lambda_cr.node.add_dependency(opensearch_serverless_collection)
        trigger_create_kb_lambda_cr.node.add_dependency(create_bedrock_kb_lambda)
        trigger_create_kb_lambda_cr.node.add_dependency(bedrock_aoss_access_policy)
        trigger_create_kb_lambda_provider.node.add_dependency(bedrock_aoss_access_policy)

        self.knowledgebase_id = trigger_create_kb_lambda_cr.ref


        knowledgebase_arn = Stack.format_arn(self, 
                                             service="bedrock", 
                                             resource="knowledge-base", 
                                             resource_name=trigger_create_kb_lambda_cr.ref,
                                             arn_format=ArnFormat.SLASH_RESOURCE_NAME
                                             )
        
        

        # logs_lambda.grant_invoke(agent_role)
        metrics_lambda.grant_invoke(agent_role)
        model = bedrock.FoundationModel.from_foundation_model_id(self, "AnthropicClaudeV3", bedrock.FoundationModelIdentifier.ANTHROPIC_CLAUDE_3_SONNET_20240229_V1_0)
        
        #Add policy to invoke model
        agent_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[model.model_arn],
        ))

        #Add policy to retrieve from bedrock knowledgebase 
        agent_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:Retrieve"],
            resources=[knowledgebase_arn],
        ))

        # Add instructions for the bedrock agent
        with open('stacks/bedrock_agent/instructions.txt', 'r') as file:
            agent_instruction = file.read()

        #Add schema for the log action group
        with open('stacks/logs_action_group/lambda/openapi_schema.json', 'r') as file:
            log_agent_schema = file.read()

        #Add schema for the metrics action group
        with open('stacks/metrics_action_group/lambda/openapi_schema.json', 'r') as file:
            metrics_agent_schema = file.read()

        # Define advanced prompt - orchestation template - override orchestration template defaults
        with open('stacks/bedrock_agent/agent_orchestration_template.json', 'r') as file:
            orc_temp_def = file.read()

        #Create Bedrock Agent
        agent = bedrock.CfnAgent(
            self,
            "observability-assistant-agent",
            agent_name="observability-assistant-agent",
            description="Observability Assistant Agent",
            auto_prepare=True,
            agent_resource_role_arn=agent_role.role_arn,
            foundation_model=model.model_id,
            instruction=agent_instruction,
            # User input for asking clarifying questions

            knowledge_bases = [
                bedrock.CfnAgent.AgentKnowledgeBaseProperty(
                    knowledge_base_id= trigger_create_kb_lambda_cr.ref, 
                    knowledge_base_state="ENABLED",
                    description="This knowledge base can be used to understand how to generate a PromQL or LogQL."
                    )
                ],
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty
                (
                    action_group_name="logs-api-caller", 
                    description="Logs API Caller",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        custom_control="RETURN_CONTROL"
                    ),
                    action_group_state="ENABLED",
                    api_schema=bedrock.CfnAgent.APISchemaProperty(
                        payload = log_agent_schema
                    )
                ),
                bedrock.CfnAgent.AgentActionGroupProperty
                (
                    action_group_name="metrics-api-caller", 
                    description="Metrics API Caller",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=metrics_lambda.function_arn
                    ),
                    action_group_state="ENABLED",
                    api_schema=bedrock.CfnAgent.APISchemaProperty(
                        payload = metrics_agent_schema
                    )
                ),
                bedrock.CfnAgent.AgentActionGroupProperty
                (
                    action_group_name="clarifying-question", 
                    parent_action_group_signature="AMAZON.UserInput",
                    action_group_state="ENABLED",
                ),
            ],
            prompt_override_configuration=bedrock.CfnAgent.PromptOverrideConfigurationProperty(
                prompt_configurations=[bedrock.CfnAgent.PromptConfigurationProperty(
                    base_prompt_template=orc_temp_def,
                    inference_configuration=bedrock.CfnAgent.InferenceConfigurationProperty(
                        maximum_length=4096,
                        temperature=0.1,
                        top_k=250,
                        top_p=1
                    ),
                    prompt_type="ORCHESTRATION",
                    prompt_creation_mode="OVERRIDDEN"
                )]
            )
        )

        self.bedrock_agent = agent

        _lambda.CfnPermission(
            self,
            "MetricsLambdaPermissions",
            action="lambda:InvokeFunction",
            function_name=metrics_lambda.function_name,
            principal="bedrock.amazonaws.com",
            source_arn=agent.attr_agent_arn
        )

        bedrock_agent_alias = bedrock.CfnAgentAlias(
            self,
            "observability-assistant-agent-alias",
            agent_id=agent.attr_agent_id,
            agent_alias_name="observability-assistant-agent-alias",
        )

        self.bedrock_agent_alias = bedrock_agent_alias

        #Create Guardrail configs

        # Create a guardrail configuration for the bedrock agent
        cfn_guardrail = bedrock.CfnGuardrail(self, "CfnGuardrail",
            name="guardrail-observability-assistant", # TODO : Generate based on self.stack_id
            description="Guardrail configuration for the bedrock agent",
            blocked_input_messaging="I'm sorry, I can't accept your prompt, as your prompt been blocked buy Guardrails.",
            blocked_outputs_messaging="I'm sorry, I can't answer that, as the response has been blocked buy Guardrails.",
            # Filter strength for incoming user prompts and outgoing agent responses
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        input_strength="NONE",
                        output_strength="NONE",
                        type="PROMPT_ATTACK"
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        input_strength="HIGH",
                        output_strength="HIGH",
                        type="MISCONDUCT"
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        input_strength="HIGH",
                        output_strength="HIGH",
                        type="INSULTS"
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        input_strength="HIGH",
                        output_strength="HIGH",
                        type="HATE"
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        input_strength="HIGH",
                        output_strength="HIGH",
                        type="SEXUAL"
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        input_strength="HIGH",
                        output_strength="HIGH",
                        type="VIOLENCE"
                    )                    
                ]
            )
        )

        # Create a Guardrail version
        cfn_guardrail_version = bedrock.CfnGuardrailVersion(self, "MyCfnGuardrailVersion",
            guardrail_identifier=cfn_guardrail.attr_guardrail_id,
            description="This is the deployed version of the guardrail configuration",
        )

        #Enable Guardrail for the agent


        agent.guardrail_configuration = bedrock.CfnAgent.GuardrailConfigurationProperty(
            guardrail_version=cfn_guardrail_version.attr_version,
            guardrail_identifier=cfn_guardrail.attr_guardrail_arn
        )

        agent_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:ApplyGuardrail"],
            resources=[cfn_guardrail.attr_guardrail_arn],
        ))

