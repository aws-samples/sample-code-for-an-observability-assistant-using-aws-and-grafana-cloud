from constructs import Construct
from aws_cdk import (
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecs_patterns as ecs_patterns,
    Duration,
    Stack,
    aws_ecr_assets as ecr_assets,
    aws_iam as iam
)


class WebAppStack(Stack):

    def __init__(self, 
                 scope: Construct, 
                 construct_id: str,
                 bedrock_agent_id: str, 
                 knowledgebase_id: str,
                 ecs_cluster: ecs.Cluster,
                 fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # # Create a fargate task definition
        # task_definition = ecs.FargateTaskDefinition(self, "grafana-assistant-task")
        # task_definition.add_container(
        #     "grafana-assistant-container",
        #     image=ecs.ContainerImage.from_asset("./src/streamlit-app", platform=ecr_assets.Platform.LINUX_ARM64),
        #     port_mappings=[ecs.PortMapping(container_port=8501)],
        #     capa
        # )

        # Use ECS Pattern to create a load balanced Fargate service
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "streamlit-webapp",
            cluster=ecs_cluster,
            service_name="streamlit-webapp",
            memory_limit_mib=2048,
            cpu=1024,
            desired_count=1,
            load_balancer_name="streamlit-webapp",
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset("./stacks/user_interface/streamlit",platform=ecr_assets.Platform.LINUX_ARM64),
                container_port=8501,
                environment={
                    "BEDROCK_AGENT_ID": bedrock_agent_id,
                    "KNOWLEDGEBASE_ID": knowledgebase_id,
                    "FUNCTION_CALLING_URL": fargate_service.load_balancer.load_balancer_dns_name
                },
                #TODO: Log Group name
            ),
        )
        # Configure Streamlit's health check
        fargate_service.target_group.configure_health_check(
            enabled=True, path="/_stcore/health", healthy_http_codes="200"
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
            resources=["*"], 
            actions=[
                "bedrock:InvokeAgent"
            ])
        )
