from constructs import Construct
from aws_cdk import (
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecs_patterns as ecs_patterns,
    Duration,
    Stack,
    aws_ecr_assets as ecr_assets,
    aws_s3 as s3
)


class VpcStack(Stack):

    def __init__(self, 
                 scope: Construct, 
                 construct_id: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a new VPC with two subnets in two availability zones
        vpc = ec2.Vpc(
            self,
            "VPC",
            max_azs=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PUBLIC,
                    name="Public",
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name="Private",
                    cidr_mask=24,
                ),
            ],
        )

        vpc.add_flow_log("FlowLog")

        #create a ECS Cluster in the VPC

        cluster = ecs.Cluster(
            self,
            "grafana-assistant",
            vpc=vpc,
            container_insights=True,
            enable_fargate_capacity_providers=True,
            cluster_name="grafana-assistant"
        )

        self.ecs_cluster = cluster

        #Access Logs specific S3 Bucket

        # bucket = s3.Bucket(self, "AcecssLog",
        #     encryption=s3.BucketEncryption.S3_MANAGED,
        #     enforce_ssl=True
        # )

        # self.access_logs_bucket = bucket