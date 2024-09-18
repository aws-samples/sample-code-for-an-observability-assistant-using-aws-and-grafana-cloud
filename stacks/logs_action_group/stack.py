# CDK Stack which creates a lambda function for the Bedrock Action group
import aws_cdk as cdk

from constructs import Construct
from aws_cdk.aws_elasticloadbalancingv2 import ApplicationProtocol, Protocol, SslPolicy
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_ecr_assets as ecr_assets,
    aws_ec2 as ec2,
    BundlingOptions,
    aws_secretsmanager as sm,
    CfnOutput,
    ArnFormat,
    aws_logs as logs
)
class LambdaStack(Stack):

    def __init__(self, 
                 scope: Construct, 
                 construct_id: str,
                 secret_name: str,
                 ecs_cluster: ecs.Cluster,
                 **kwargs
                 ) -> None:
        super().__init__(scope, construct_id, **kwargs)

       
        #Get Secret Manager secret ARN from the name
        secret = sm.Secret.from_secret_name_v2(self, "Secret", secret_name)

        application_image = ecs.AssetImage.from_asset(
                                            directory="stacks/logs_action_group/lambda",
                                            platform=ecr_assets.Platform.LINUX_ARM64
                                            )  
        
        log_group = logs.LogGroup(self, "LogGroup",
                                      log_group_name="logs-action-group",
                                       removal_policy=cdk.RemovalPolicy.DESTROY )

        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "logs-action-group-fargate",
            service_name="logs-action-group",
            cluster=ecs_cluster,
            memory_limit_mib=2048,
            cpu=1024,
            desired_count=1,
            public_load_balancer=False,
            load_balancer_name="logs-action-group",
            open_listener=False,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=application_image,
                container_port=80,
                log_driver=ecs.LogDriver.aws_logs(log_group=log_group,mode=ecs.AwsLogDriverMode.NON_BLOCKING, stream_prefix='logs-action-group'),
                environment={
                    "POWERTOOLS_SERVICE_NAME": "LogsLambdaAgent",
                    "POWERTOOLS_METRICS_NAMESPACE": "LogsLambdaAgent",
                    "API_SECRET_NAME": secret.secret_name
                },
            ),
        )

        fargate_service.target_group.configure_health_check(
            enabled=True, path="/health", healthy_http_codes="200"
        )

        # Speed up deployments
        fargate_service.target_group.set_attribute(
            key="deregistration_delay.timeout_seconds",
            value="10",
        )

        # Specify the CPU architecture for the fargate service

        task_definition = fargate_service.task_definition.node.default_child
        task_definition.add_override(
            "Properties.RuntimePlatform.CpuArchitecture",
            "ARM64",
        )
        task_definition.add_override(
            "Properties.RuntimePlatform.OperatingSystemFamily",
            "LINUX",
        )

        # Grant access to the fargate service IAM access to invoke Bedrock runtime API calls
        fargate_service.task_definition.task_role.add_to_policy(iam.PolicyStatement( 
            effect=iam.Effect.ALLOW, 
            resources=[log_group.log_group_arn], 
            actions=[
                "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
            ])
        )
        secret.grant_read(fargate_service.task_definition.task_role)
        fargate_service.load_balancer.connections.security_groups[0].add_ingress_rule(peer=ec2.Peer.ipv4(ecs_cluster.vpc.vpc_cidr_block), connection=ec2.Port.tcp(80))
        self.fargate_service = fargate_service