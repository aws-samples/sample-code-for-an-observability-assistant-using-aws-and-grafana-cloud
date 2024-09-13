from constructs import Construct
from aws_cdk import (
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecs_patterns as ecs_patterns,
    Duration,
    Stack,
    aws_ecr_assets as ecr_assets,
    aws_iam as iam,
    aws_cognito as cognito,
    RemovalPolicy,
    aws_elasticloadbalancingv2 as elb,
    aws_elasticloadbalancingv2_actions as elb_actions,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_secretsmanager as secretsmanager,
    aws_certificatemanager as acm,
    CfnOutput,
    aws_bedrock as bedrock,
    aws_wafv2 as waf
)


class WebAppStack(Stack):

    def __init__(self, 
                 scope: Construct, 
                 construct_id: str,
                 bedrock_agent: bedrock.CfnAgent, 
                 bedrock_agent_alias: bedrock.CfnAgentAlias,
                 knowledgebase_id: str,
                 ecs_cluster: ecs.Cluster,
                 imported_cert_arn: str,
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
        ui_fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "streamlit-webapp",
            cluster=ecs_cluster,
            service_name="streamlit-webapp",
            memory_limit_mib=2048,
            cpu=1024,
            desired_count=1,
            load_balancer_name="streamlit-webapp",
            listener_port=443,
            # protocol=elb.ApplicationProtocol.HTTPS,
            certificate = acm.Certificate.from_certificate_arn(self, "imported-cert-arn", imported_cert_arn),
            # certificate = iam_server_certificate.attr_arn,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset("./stacks/user_interface/streamlit",platform=ecr_assets.Platform.LINUX_ARM64),
                container_port=8501,
                environment={
                    "BEDROCK_AGENT_ID": bedrock_agent.attr_agent_id,
                    "BEDROCK_AGENT_ALIAS_ID": bedrock_agent_alias.attr_agent_alias_id,
                    "KNOWLEDGEBASE_ID": knowledgebase_id,
                    "FUNCTION_CALLING_URL": fargate_service.load_balancer.load_balancer_dns_name
                },
            #Allow 
                #TODO: Log Group name
            ),
        )

        # ui_fargate_service.listener.add_certificates(id="self-signed-cert",certificates=[iam_server_certificate.attr_arn])

        # Configure Streamlit's health check
        ui_fargate_service.target_group.configure_health_check(
            enabled=True, path="/_stcore/health", healthy_http_codes="200"
        )

        # Speed up deployments
        ui_fargate_service.target_group.set_attribute(
            key="deregistration_delay.timeout_seconds",
            value="10",
        )

        # Specify the CPU architecture for the fargate service

        task_definition = ui_fargate_service.task_definition.node.default_child
        task_definition.add_override(
            "Properties.RuntimePlatform.CpuArchitecture",
            "ARM64",
        )
        task_definition.add_override(
            "Properties.RuntimePlatform.OperatingSystemFamily",
            "LINUX",
        )

        # Grant access to the fargate service IAM access to invoke Bedrock runtime API calls
        ui_fargate_service.task_definition.task_role.add_to_policy(iam.PolicyStatement( 
            effect=iam.Effect.ALLOW, 
            resources=[bedrock_agent_alias.attr_agent_alias_arn], 
            actions=[
                "bedrock:InvokeAgent"
            ])
        )


        cognito_domain_prefix = "observability-assistant-pool"
        # The code that defines your stack goes here
        user_pool = cognito.UserPool(self, "ObservabilityAssistantUserPool",
                                        user_pool_name=cognito_domain_prefix,
                                        account_recovery=cognito.AccountRecovery.NONE,
                                        # self_sign_up_enabled=True,
                                        sign_in_aliases=cognito.SignInAliases(email=True),
                                        auto_verify=cognito.AutoVerifiedAttrs(email=True),
                                        self_sign_up_enabled=False,
                                        removal_policy=RemovalPolicy.DESTROY,
                                        advanced_security_mode=cognito.AdvancedSecurityMode.ENFORCED,
                                        password_policy=cognito.PasswordPolicy(
                                            min_length=8,
                                            require_lowercase=True,
                                            require_uppercase=True,
                                            require_digits=True,
                                            require_symbols=True,
                                        )
        )

        user_pool_domain = cognito.UserPoolDomain(
            self,
            "streamlit-userpool-domain",
            user_pool=user_pool,
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=cognito_domain_prefix,
            ),
        )

        alb_dns = ui_fargate_service.load_balancer.load_balancer_dns_name
        user_pool_client = user_pool.add_client(
            "streamlit-userpool-client",
            user_pool_client_name="StreamlitAlbAuthentication",
            generate_secret=True,
            auth_flows=cognito.AuthFlow(user_password=True),
            o_auth=cognito.OAuthSettings(
                callback_urls=[
                    f"https://{alb_dns}/oauth2/idpresponse",
                    f"https://{alb_dns}",
                ],
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.EMAIL],
                logout_urls=[f"https://{alb_dns}"],
            ),
            prevent_user_existence_errors=True,
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.COGNITO
            ],
        )

        ui_fargate_service.listener.add_action(
            "authenticate-rule",
            priority=1000,
            action=elb_actions.AuthenticateCognitoAction(
                next=elb.ListenerAction.forward(
                    target_groups=[ui_fargate_service.target_group]
                ),
                user_pool=user_pool,
                user_pool_client=user_pool_client,
                user_pool_domain=user_pool_domain,
            ),
            conditions=[elb.ListenerCondition.host_headers([alb_dns])],
        )

        # Let the load balancer talk to the OIDC provider
        lb_security_group = ui_fargate_service.load_balancer.connections.security_groups[0]
        lb_security_group.add_egress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port(
                protocol=ec2.Protocol.TCP,
                string_representation="443",
                from_port=443,
                to_port=443,
            ),
            description="Outbound HTTPS traffic to the OIDC provider",
        )

        # Disallow accessing the load balancer URL directly
        cfn_listener: elb.CfnListener = ui_fargate_service.listener.node.default_child
        cfn_listener.default_actions = [
            {
                "type": "fixed-response",
                "fixedResponseConfig": {
                    "statusCode": "403",
                    "contentType": "text/plain",
                    "messageBody": "This is not a valid endpoint!",
                },
            }
        ]

        waf_protection = waf.CfnWebACL(self, "WAFProtection", 
                                       default_action=waf.CfnWebACL.DefaultActionProperty(allow={}), 
                                       scope="REGIONAL", 
                                       visibility_config=waf.CfnWebACL.VisibilityConfigProperty(
                                           cloud_watch_metrics_enabled=True, 
                                           metric_name="streamlit-waf-protection", 
                                           sampled_requests_enabled=True
                                           ), 
                                        rules=[
                                            waf.CfnWebACL.RuleProperty(
                                            name="CRSRule", 
                                            priority=0, 
                                            statement=waf.CfnWebACL.StatementProperty(
                                                managed_rule_group_statement=waf.CfnWebACL.ManagedRuleGroupStatementProperty(
                                                    vendor_name="AWS",
                                                    name="AWSManagedRulesCommonRuleSet"
                                                )
                                            ),
                                            override_action=waf.CfnWebACL.OverrideActionProperty(none={}), 
                                            visibility_config=waf.CfnWebACL.VisibilityConfigProperty(
                                                cloud_watch_metrics_enabled=True, 
                                                metric_name="streamlit-waf-protection-owasp-ruleset", 
                                                sampled_requests_enabled=True
                                            )
                                        )]
        )

        alb_waf_association = waf.CfnWebACLAssociation(self, "ALBWebACLAssociation",
                                                        resource_arn=ui_fargate_service.load_balancer.load_balancer_arn,
                                                        web_acl_arn=waf_protection.attr_arn
                                                        )
        


        