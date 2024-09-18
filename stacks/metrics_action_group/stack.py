# CDK Stack which creates a lambda function for the Bedrock Action group
import aws_cdk as cdk

from constructs import Construct
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_logs as logs,
    BundlingOptions,
    aws_secretsmanager as sm,
    CfnOutput,
    ArnFormat
)

class LambdaStack(Stack):

    def __init__(self, 
                 scope: Construct, 
                 construct_id: str,
                 secret_name: str,
                 **kwargs
                 ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        secret = sm.Secret.from_secret_name_v2(self, "Secret", secret_name)

        log_group = logs.LogGroup(self, "LogGroup",
                                      log_group_name="metrics-action-group",
                                       removal_policy=cdk.RemovalPolicy.DESTROY )

        lambda_function = _lambda.Function(
            self,
            "metrics-action-group",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.ARM_64,
            code=_lambda.Code.from_asset(
                "stacks/metrics_action_group/lambda",
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
            handler="app.lambda_handler",
            
            timeout=cdk.Duration.seconds(10),
            description="Metrics Action Group Lambda Function",
            function_name="metrics-action-group",
            tracing=_lambda.Tracing.ACTIVE,
            application_log_level_v2 = _lambda.ApplicationLogLevel.INFO,
            logging_format = _lambda.LoggingFormat.JSON,
            environment = {
                "POWERTOOLS_SERVICE_NAME": "MetricsLambdaAgent",
                "POWERTOOLS_METRICS_NAMESPACE": "MetricsLambdaAgent",
                "API_SECRET_NAME": secret.secret_name
            },
            initial_policy=[
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[log_group.log_group_arn]
                )
            ]
        )

        self.lambda_function = lambda_function
        secret.grant_read(lambda_function)
