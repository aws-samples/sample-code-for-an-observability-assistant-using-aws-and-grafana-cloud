# CDK Stack which creates a lambda function for the Bedrock Action group
import aws_cdk as cdk

from constructs import Construct
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_iam as iam,
    # aws_lambda_python_alpha as lambda_python,
    BundlingOptions,
    aws_secretsmanager as sm,
    CfnOutput,
    ArnFormat
)
# from aws_cdk.aws_lambda_python_alpha import (
#     PythonFunction,
# )
class LambdaStack(Stack):

    def __init__(self, 
                 scope: Construct, 
                 construct_id: str,
                 secret_name: str,
                 **kwargs
                 ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a Lambda function
        # lambda_function = lambda_python.PythonFunction(
        #     self,
        #     "logs-action-group",
        #     entry="./stacks/logs_action_group/lambda",
        #     index="app.py",
        #     handler="lambda_handler",
        #     runtime=_lambda.Runtime.PYTHON_3_12,
        #     timeout=cdk.Duration.seconds(10),
        #     description="Logs Action Group Lambda Function",
        #     function_name="logs-action-group",
        #     bundling=BundlingOptions(
        #         image=_lambda.Runtime.PYTHON_3_12.bundling_image,
        #         command=[
        #             "bash",
        #             "-c",
        #             "pip install --no-cache -r requirements.txt -t /asset-output && cp -au . /asset-output",
        #         ],
        #     ),
        #     initial_policy=[
        #         iam.PolicyStatement(
        #             actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        #             resources=["*"]
        #         )
        #     ]
        # )
        #Get Secret Manager secret ARN from the name
        secret = sm.Secret.from_secret_name_v2(self, "Secret", secret_name)

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
                    resources=["*"]
                )
            ]
        )

        #Export tge lambda arn
        # CfnOutput(self, "LogsLambdaFunctionArn", value=lambda_function.function_arn, export_name="LogsLambdaFunctionArn")
        self.lambda_function = lambda_function
        secret.grant_read(lambda_function)

        # bedrock_agent_arn = Stack.format_arn(self, 
        #                                      service="bedrock", 
        #                                      resource="agent", 
        #                                      resource_name="*",
        #                                      arn_format=ArnFormat.SLASH_RESOURCE_NAME
        #                                      )
        
        #Grant bedrock agent permissions to invoke the lambda function
        # lambda_function.add_permission(
        #     "InvokeFromBedrockAgent",
        #     principal=iam.ServicePrincipal("bedrock.amazonaws.com"),
        #     action="lambda:InvokeFunction",
        #     source_arn=bedrock_agent_arn
        # )
        
        
    