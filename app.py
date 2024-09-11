#!/usr/bin/env python3

import aws_cdk as cdk
from helper import config
from stacks.user_interface.stack import WebAppStack
from stacks.logs_action_group.stack import LambdaStack as LogsActionGroupStack
from stacks.metrics_action_group.stack import LambdaStack as MetricsActionGroupStack
from stacks.bedrock_agent.stack import ObservabilityAssistantAgent
from stacks.vpc.stack import VpcStack
# from stacks.cognito_for_authz.stack import CognitoStack
import os


app = cdk.App()

conf = config.Config(app.node.try_get_context('environment'))

vpc_stack = VpcStack(app, "grafana-vpc")
logs_lambda_stack = LogsActionGroupStack(app, 
                                         "grafana-logs-action-group",
                                         secret_name=conf.get('LogsSecretName'),
                                         ecs_cluster=vpc_stack.ecs_cluster
)
metrics_lambda_stack = MetricsActionGroupStack(app, "grafana-metrics-action-group", secret_name=conf.get('MetricsSecretName'))
bedrock_agent_stack = ObservabilityAssistantAgent(app, 
                            "grafana-observability-assistant", 
                            knowledgebase_id=conf.get('KnowledgeBaseId'),
                            # logs_lambda=logs_lambda_stack.lambda_function,
                            metrics_lambda=metrics_lambda_stack.lambda_function,
)
streamlit_stack = WebAppStack(app, 
            "grafana-streamlit-webapp",
            knowledgebase_id=conf.get('KnowledgeBaseId'),
            bedrock_agent_id=bedrock_agent_stack.bedrock_agent_id,
            fargate_service=logs_lambda_stack.fargate_service,
            ecs_cluster=vpc_stack.ecs_cluster,
            imported_cert_arn=conf.get('SelfSignedCertARN')
)

app.synth()
