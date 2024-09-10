#!/usr/bin/env python3

import aws_cdk as cdk

from grafana_observability_assistant_cdk.grafana_observability_assistant_cdk_stack import GrafanaObservabilityAssistantCdkStack


app = cdk.App()
GrafanaObservabilityAssistantCdkStack(app, "GrafanaObservabilityAssistantCdkStack")

app.synth()
