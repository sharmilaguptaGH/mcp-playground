"""
Create a sample Datadog dashboard for authentication API observability.

This public demo shows how to build a dashboard for token endpoint traffic,
validation requests, latency, errors, client IPs, user agents, and infrastructure metrics.

Requirements:
  pip install datadog-api-client
  DD_API_KEY
  DD_APP_KEY

Usage:
  DD_API_KEY=<your-api-key> DD_APP_KEY=<your-app-key> python create_auth_observability_dashboard.py

Optional:
  DD_SITE=datadoghq.com  (default)
"""

import os
from datadog_api_client import Configuration, ApiClient
from datadog_api_client.v1.api.dashboards_api import DashboardsApi
from datadog_api_client.v1.model.dashboard import Dashboard
from datadog_api_client.v1.model.dashboard_layout_type import DashboardLayoutType
from datadog_api_client.v1.model.widget import Widget
from datadog_api_client.v1.model.widget_definition import WidgetDefinition
from datadog_api_client.v1.model.widget_layout import WidgetLayout
from datadog_api_client.v1.model.note_widget_definition import NoteWidgetDefinition
from datadog_api_client.v1.model.note_widget_definition_type import NoteWidgetDefinitionType
from datadog_api_client.v1.model.timeseries_widget_definition import TimeseriesWidgetDefinition
from datadog_api_client.v1.model.timeseries_widget_definition_type import TimeseriesWidgetDefinitionType
from datadog_api_client.v1.model.timeseries_widget_request import TimeseriesWidgetRequest
from datadog_api_client.v1.model.widget_display_type import WidgetDisplayType
from datadog_api_client.v1.model.widget_line_type import WidgetLineType
from datadog_api_client.v1.model.widget_line_width import WidgetLineWidth
from datadog_api_client.v1.model.widget_request_style import WidgetRequestStyle
from datadog_api_client.v1.model.toplist_widget_definition import ToplistWidgetDefinition
from datadog_api_client.v1.model.toplist_widget_definition_type import ToplistWidgetDefinitionType
from datadog_api_client.v1.model.toplist_widget_request import ToplistWidgetRequest
from datadog_api_client.v1.model.query_value_widget_definition import QueryValueWidgetDefinition
from datadog_api_client.v1.model.query_value_widget_definition_type import QueryValueWidgetDefinitionType
from datadog_api_client.v1.model.query_value_widget_request import QueryValueWidgetRequest
from datadog_api_client.v1.model.widget_text_align import WidgetTextAlign
from datadog_api_client.v1.model.widget_time import WidgetTime
from datadog_api_client.v1.model.dashboard_template_variable import DashboardTemplateVariable


SERVICE = os.getenv("DD_SERVICE", "sample-auth-api")
TOKEN_RESOURCE = os.getenv("DD_TOKEN_RESOURCE", "resource_name:post_/oauth/token*")
VALIDATION_RESOURCE = os.getenv("DD_VALIDATION_RESOURCE", "resource_name:post_/oauth/introspect*")
LIVE_SPAN = "4h"
ALB_NAME = os.getenv("DD_ALB_NAME", "sample-auth-alb")


def _ts_style():
    return WidgetRequestStyle(
        line_type=WidgetLineType.SOLID,
        line_width=WidgetLineWidth.NORMAL,
    )


def _time():
    return WidgetTime(live_span=LIVE_SPAN)


def build_widgets():
    widgets = []
    y = 0

    # ── Row 0: Header ──────────────────────────────────────────────
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                NoteWidgetDefinition(
                    type=NoteWidgetDefinitionType.NOTE,
                    content=(
                        "# Sample Auth API — Token Usage\n"
                        "Service: **sample_auth_api** &nbsp;|&nbsp; "
                        "Endpoints: `/identity/connect/token`, `/identity/connect/accesstokenvalidation`\n\n"
                        "| Env | Hostname | Hosts |\n"
                        "|---|---|---|\n"
                        "| Production | auth.example.com | PROD-HOST* |\n"
                        "| Stage | stage-auth.example.com | STAGE-HOST* |\n"
                        "| QA | qa-auth.example.com | QA-HOST* |\n"
                        "| Development | dev-auth.example.com | DEV-HOST* |"
                    ),
                    background_color="vivid_blue",
                    font_size="14",
                    text_align=WidgetTextAlign.LEFT,
                    show_tick=False,
                )
            ),
            layout=WidgetLayout(x=0, y=y, width=12, height=2),
        )
    )
    y += 2

    # ── Row 1: Summary query-value cards ───────────────────────────
    envs_colors = [
        ("production", "vivid_red"),
        ("stage", "vivid_orange"),
        ("qa", "vivid_yellow"),
        ("development", "vivid_green"),
    ]
    for i, (env, color) in enumerate(envs_colors):
        widgets.append(
            Widget(
                definition=WidgetDefinition(
                    QueryValueWidgetDefinition(
                        type=QueryValueWidgetDefinitionType.QUERY_VALUE,
                        title=f"{env.capitalize()} — Token Requests",
                        title_size="16",
                        title_align=WidgetTextAlign.LEFT,
                        time=_time(),
                        requests=[
                            QueryValueWidgetRequest(
                                q=(
                                    f"sum:trace.aspnet.request.hits"
                                    f"{{{TOKEN_RESOURCE},service:{SERVICE},env:{env}}}.as_count()"
                                ),
                                aggregator="sum",
                            )
                        ],
                        precision=0,
                    )
                ),
                layout=WidgetLayout(x=i * 3, y=y, width=3, height=2),
            )
        )
    y += 2

    # ── Row 2: Token issuance by env (timeseries) ──────────────────
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                TimeseriesWidgetDefinition(
                    type=TimeseriesWidgetDefinitionType.TIMESERIES,
                    title="Token Issuance Requests — All Environments",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        TimeseriesWidgetRequest(
                            q=(
                                f"sum:trace.aspnet.request.hits"
                                f"{{{TOKEN_RESOURCE},service:{SERVICE},$env}} by {{env}}.as_count()"
                            ),
                            display_type=WidgetDisplayType.BARS,
                            style=_ts_style(),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=0, y=y, width=6, height=3),
        )
    )

    # Token validation by env
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                TimeseriesWidgetDefinition(
                    type=TimeseriesWidgetDefinitionType.TIMESERIES,
                    title="Token Validation Requests — All Environments",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        TimeseriesWidgetRequest(
                            q=(
                                f"sum:trace.aspnet.request.hits"
                                f"{{{VALIDATION_RESOURCE},service:{SERVICE},$env}} by {{env}}.as_count()"
                            ),
                            display_type=WidgetDisplayType.BARS,
                            style=_ts_style(),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=6, y=y, width=6, height=3),
        )
    )
    y += 3

    # ── Row 3: Who is calling — top hosts (callers) ────────────────
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                ToplistWidgetDefinition(
                    type=ToplistWidgetDefinitionType.TOPLIST,
                    title="Top Hosts Serving Token Requests",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        ToplistWidgetRequest(
                            q=(
                                f"top(sum:trace.aspnet.request.hits"
                                f"{{{TOKEN_RESOURCE},service:{SERVICE},$env}} by {{host}}.as_count(), 20, 'sum', 'desc')"
                            ),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=0, y=y, width=6, height=4),
        )
    )

    # Top client IPs hitting the token endpoint (via http.client_ip tag if available)
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                ToplistWidgetDefinition(
                    type=ToplistWidgetDefinitionType.TOPLIST,
                    title="Top Client IPs — Token Endpoint",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        ToplistWidgetRequest(
                            q=(
                                f"top(sum:trace.aspnet.request.hits"
                                f"{{{TOKEN_RESOURCE},service:{SERVICE},$env}} by {{http.client_ip}}.as_count(), 20, 'sum', 'desc')"
                            ),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=6, y=y, width=6, height=4),
        )
    )
    y += 4

    # ── Row 4: Per-environment host breakdown ──────────────────────
    for i, (env, _) in enumerate(envs_colors):
        col = (i % 2) * 6
        row_offset = (i // 2) * 3
        widgets.append(
            Widget(
                definition=WidgetDefinition(
                    TimeseriesWidgetDefinition(
                        type=TimeseriesWidgetDefinitionType.TIMESERIES,
                        title=f"{env.capitalize()} — Token Requests by Host",
                        title_size="16",
                        title_align=WidgetTextAlign.LEFT,
                        time=_time(),
                        requests=[
                            TimeseriesWidgetRequest(
                                q=(
                                    f"sum:trace.aspnet.request.hits"
                                    f"{{{TOKEN_RESOURCE},service:{SERVICE},env:{env}}} by {{host}}.as_count()"
                                ),
                                display_type=WidgetDisplayType.BARS,
                                style=_ts_style(),
                            )
                        ],
                    )
                ),
                layout=WidgetLayout(x=col, y=y + row_offset, width=6, height=3),
            )
        )
    y += 6

    # ── Row 5: Errors ──────────────────────────────────────────────
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                TimeseriesWidgetDefinition(
                    type=TimeseriesWidgetDefinitionType.TIMESERIES,
                    title="Token Endpoint Errors by Environment",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        TimeseriesWidgetRequest(
                            q=(
                                f"sum:trace.aspnet.request.errors"
                                f"{{{TOKEN_RESOURCE},service:{SERVICE},$env}} by {{env}}.as_count()"
                            ),
                            display_type=WidgetDisplayType.BARS,
                            style=_ts_style(),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=0, y=y, width=6, height=3),
        )
    )

    # Latency
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                TimeseriesWidgetDefinition(
                    type=TimeseriesWidgetDefinitionType.TIMESERIES,
                    title="Token Endpoint Avg Latency by Environment",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        TimeseriesWidgetRequest(
                            q=(
                                f"avg:trace.aspnet.request.duration"
                                f"{{{TOKEN_RESOURCE},service:{SERVICE},$env}} by {{env}}"
                            ),
                            display_type=WidgetDisplayType.LINE,
                            style=_ts_style(),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=6, y=y, width=6, height=3),
        )
    )
    y += 3

    # ── Row 6: HTTP status code breakdown ──────────────────────────
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                ToplistWidgetDefinition(
                    type=ToplistWidgetDefinitionType.TOPLIST,
                    title="Token Requests by HTTP Status Code",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        ToplistWidgetRequest(
                            q=(
                                f"top(sum:trace.aspnet.request.hits"
                                f"{{{TOKEN_RESOURCE},service:{SERVICE},$env}} by {{http.status_code}}.as_count(), 10, 'sum', 'desc')"
                            ),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=0, y=y, width=6, height=3),
        )
    )

    # User-agent breakdown
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                ToplistWidgetDefinition(
                    type=ToplistWidgetDefinitionType.TOPLIST,
                    title="Token Requests by User-Agent",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        ToplistWidgetRequest(
                            q=(
                                f"top(sum:trace.aspnet.request.hits"
                                f"{{{TOKEN_RESOURCE},service:{SERVICE},$env}} by {{http.useragent}}.as_count(), 20, 'sum', 'desc')"
                            ),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=6, y=y, width=6, height=3),
        )
    )
    y += 3

    # ── Row 7: ALB Metrics (Classic Cloud Non-HA) ──────────────────
    widgets.append(
        Widget(
            definition=WidgetDefinition(
                NoteWidgetDefinition(
                    type=NoteWidgetDefinitionType.NOTE,
                    content="## ALB / Infrastructure Metrics\nAWS ALB request counts for Sample Auth API load balancers.",
                    background_color="gray",
                    font_size="14",
                    text_align=WidgetTextAlign.LEFT,
                    show_tick=False,
                )
            ),
            layout=WidgetLayout(x=0, y=y, width=12, height=1),
        )
    )
    y += 1

    widgets.append(
        Widget(
            definition=WidgetDefinition(
                TimeseriesWidgetDefinition(
                    type=TimeseriesWidgetDefinitionType.TIMESERIES,
                    title="ALB Request Count — Prod Portal ALB",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        TimeseriesWidgetRequest(
                            q=f"sum:aws.applicationelb.request_count{{name:{ALB_NAME}}}.as_count()",
                            display_type=WidgetDisplayType.BARS,
                            style=_ts_style(),
                        )
                    ],
                )
            ),
            layout=WidgetLayout(x=0, y=y, width=6, height=3),
        )
    )

    widgets.append(
        Widget(
            definition=WidgetDefinition(
                TimeseriesWidgetDefinition(
                    type=TimeseriesWidgetDefinitionType.TIMESERIES,
                    title="ALB 4xx/5xx Errors — Prod Portal ALB",
                    title_size="16",
                    title_align=WidgetTextAlign.LEFT,
                    time=_time(),
                    requests=[
                        TimeseriesWidgetRequest(
                            q="sum:aws.applicationelb.httpcode_elb_4xx{name:ue1pporapp-alb-prod}.as_count()",
                            display_type=WidgetDisplayType.LINE,
                            style=_ts_style(),
                        ),
                        TimeseriesWidgetRequest(
                            q="sum:aws.applicationelb.httpcode_elb_5xx{name:ue1pporapp-alb-prod}.as_count()",
                            display_type=WidgetDisplayType.LINE,
                            style=_ts_style(),
                        ),
                    ],
                )
            ),
            layout=WidgetLayout(x=6, y=y, width=6, height=3),
        )
    )

    return widgets


def main():
    configuration = Configuration()
    # Uses DD_API_KEY / DD_APP_KEY / DD_SITE env vars automatically

    template_variables = [
        DashboardTemplateVariable(
            name="env",
            prefix="env",
            default="*",
        ),
    ]

    dashboard = Dashboard(
        title="Sample Auth API — Token Usage Observability"
        description=(
            "Sample dashboard for tracking authentication API traffic, token issuance, "
            "validation requests, caller hosts, client IPs, user agents, latency, errors, "
            "and related infrastructure metrics."
        ),
        layout_type=DashboardLayoutType.ORDERED,
        widgets=build_widgets(),
        template_variables=template_variables,
        is_read_only=False,
    )

    with ApiClient(configuration) as api_client:
        api = DashboardsApi(api_client)
        resp = api.create_dashboard(body=dashboard)
        print(f"Dashboard created: {resp.url}")
        print(f"Dashboard ID:      {resp.id}")


if __name__ == "__main__":
    main()


