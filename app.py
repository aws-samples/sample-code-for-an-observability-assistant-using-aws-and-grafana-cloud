#!/usr/bin/env python3

import aws_cdk as cdk
from helper import config
from stacks.user_interface.stack import WebAppStack
from stacks.roc_action_group.stack import RoCStack
from stacks.metrics_action_group.stack import LambdaStack as MetricsActionGroupStack
from stacks.bedrock_agent.stack import ObservabilityAssistantAgent
from stacks.vpc.stack import VpcStack
from stacks.opensearch.stack import AossStack
from cdk_nag import ( AwsSolutionsChecks, NagSuppressions )
import os


app = cdk.App()

conf = config.Config(app.node.try_get_context('environment'))

vpc_stack = VpcStack(app, "grafana-vpc")
roc_action_group_stack = RoCStack(app, 
                                         "grafana-roc-action-group",
                                         loki_secret_name=conf.get('LogsSecretName'),
                                         prom_secret_name=conf.get('MetricsSecretName'),
                                        #  secret_name=conf.get('LogsSecretName'),
                                         ecs_cluster=vpc_stack.ecs_cluster
)
# metrics_lambda_stack = MetricsActionGroupStack(app, "grafana-metrics-action-group", secret_name=conf.get('MetricsSecretName'))

knowledgebase_stack = AossStack(app, "grafana-knowledgebase")
bedrock_agent_stack = ObservabilityAssistantAgent(app, 
                            "grafana-observability-assistant", 
                            # knowledgebase_id=conf.get('KnowledgeBaseId'),
                            opensearch_serverless_collection=knowledgebase_stack.opensearch_serverless_collection,
                            # metrics_lambda=metrics_lambda_stack.lambda_function,
                            urls_to_crawl=conf.get('WebUrlsToCrawl')
)
streamlit_stack = WebAppStack(app, 
            "grafana-streamlit-webapp",
            knowledgebase_id=bedrock_agent_stack.knowledgebase_id,
            bedrock_agent = bedrock_agent_stack.bedrock_agent,
            bedrock_agent_alias= bedrock_agent_stack.bedrock_agent_alias,
            # bedrock_agent_id=bedrock_agent_stack.bedrock_agent_id,
            fargate_service=roc_action_group_stack.fargate_service,
            ecs_cluster=vpc_stack.ecs_cluster,
            imported_cert_arn=conf.get('SelfSignedCertARN')
)

cdk.Aspects.of(app).add(AwsSolutionsChecks())
NagSuppressions.add_stack_suppressions(vpc_stack, [{"id":"AwsSolutions-S1", "reason":"Bucket itself is used for access logging."}])
NagSuppressions.add_stack_suppressions(streamlit_stack, [{"id":"AwsSolutions-ELB2", "reason":"Getting blocked by https://github.com/aws/aws-cdk/issues/25007 with no resolution"}])
NagSuppressions.add_stack_suppressions(roc_action_group_stack, [{"id":"AwsSolutions-ELB2", "reason":"Getting blocked by https://github.com/aws/aws-cdk/issues/25007 with no resolution"}])
NagSuppressions.add_stack_suppressions(streamlit_stack, [{"id":"AwsSolutions-EC23", "reason":"This is by design and protected by WAF"}])
# NagSuppressions.add_stack_suppressions(logs_lambda_stack, [{"id":"AwsSolutions-EC23", "reason":"False Warning already implemented to limit to VPC Only CIDRs"}])
NagSuppressions.add_stack_suppressions(roc_action_group_stack, [{"id":"AwsSolutions-ECS2", "reason":"Only Secret Name is noted, this is by design"}])
NagSuppressions.add_stack_suppressions(streamlit_stack, [{"id":"AwsSolutions-ECS2", "reason":"Only Secret Name is noted, this is by design"}])
# NagSuppressions.add_stack_suppressions(metrics_lambda_stack, [{"id":"AwsSolutions-IAM4", "reason":"not coded in this solution"}])
NagSuppressions.add_stack_suppressions(roc_action_group_stack, [{"id":"AwsSolutions-IAM5", "reason":"not coded in this solution"}])
# NagSuppressions.add_stack_suppressions(metrics_lambda_stack, [{"id":"AwsSolutions-IAM5", "reason":"not coded in this solution"}])
NagSuppressions.add_stack_suppressions(bedrock_agent_stack, [{"id":"AwsSolutions-IAM5", "reason":"not coded in this solution"}])
NagSuppressions.add_stack_suppressions(streamlit_stack, [{"id":"AwsSolutions-IAM5", "reason":"not coded in this solution"}])
NagSuppressions.add_stack_suppressions(knowledgebase_stack, [{"id":"AwsSolutions-IAM5", "reason":"Premissive permissions required as per aoss documentation."}])
NagSuppressions.add_stack_suppressions(bedrock_agent_stack, [{"id":"AwsSolutions-IAM4", "reason":"Policies are set by Custom Resource."}])
NagSuppressions.add_stack_suppressions(knowledgebase_stack, [{"id":"AwsSolutions-IAM4", "reason":"Policies are set by Custom Resource."}])
NagSuppressions.add_stack_suppressions(bedrock_agent_stack, [{"id":"AwsSolutions-S1", "reason":"Not required"}])
NagSuppressions.add_stack_suppressions(bedrock_agent_stack, [{"id":"AwsSolutions-L1", "reason":"Not controlled or created by this solution"}])

app.synth()
