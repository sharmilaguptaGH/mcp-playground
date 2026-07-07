resource "datadog_dashboard_json" "sample_auth_token_usage" {
  dashboard = file("${path.module}/sample_auth_token_usage_dashboard.json")
}

