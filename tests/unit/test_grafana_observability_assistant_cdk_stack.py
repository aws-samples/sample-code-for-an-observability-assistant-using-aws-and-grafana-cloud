import aws_cdk as core
import aws_cdk.assertions as assertions
from grafana_observability_assistant_cdk.grafana_observability_assistant_cdk_stack import GrafanaObservabilityAssistantCdkStack


def test_sqs_queue_created():
    app = core.App()
    stack = GrafanaObservabilityAssistantCdkStack(app, "grafana-observability-assistant-cdk")
    template = assertions.Template.from_stack(stack)

    template.has_resource_properties("AWS::SQS::Queue", {
        "VisibilityTimeout": 300
    })


def test_sns_topic_created():
    app = core.App()
    stack = GrafanaObservabilityAssistantCdkStack(app, "grafana-observability-assistant-cdk")
    template = assertions.Template.from_stack(stack)

    template.resource_count_is("AWS::SNS::Topic", 1)
