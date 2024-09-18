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
)
import hashlib

class ObservabilityAssistantAgent(cdk.Stack):

    def __init__(self, 
                 scope: Construct, 
                 construct_id: str,
                #  logs_lambda:  _lambda.Function,
                 metrics_lambda: _lambda.Function,
                 knowledgebase_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # The code that defines your stack goes here

        knowledgebase_arn = Stack.format_arn(self, 
                                             service="bedrock", 
                                             resource="knowledge-base", 
                                             resource_name=knowledgebase_id,
                                             arn_format=ArnFormat.SLASH_RESOURCE_NAME
                                             )
        
        #Create a Bedrock agent execution role
        agent_role = iam.Role(
            self,
            "agent-role",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Role for Bedrock based observability assistant",
            # role_name="bedrock-agent-role",
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
                    knowledge_base_id= knowledgebase_id, #TODO: Create this as well lateron
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
                    # description="Metrics API Caller",
                    # action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                    #     lambda_=metrics_lambda.function_arn
                    # ),
                    action_group_state="ENABLED",
                    # api_schema=bedrock.CfnAgent.APISchemaProperty(
                    #     payload = metrics_agent_schema
                    # )
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

        # _lambda.CfnPermission(
        #     self,
        #     "LogsLambdaPermissions",
        #     action="lambda:InvokeFunction",
        #     function_name=logs_lambda.function_name,
        #     principal="bedrock.amazonaws.com",
        #     source_arn=agent.attr_agent_arn
        # )

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
            # description="Observability Assistant Agent Alias"
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

