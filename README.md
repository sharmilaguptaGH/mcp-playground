# MCP Platform Automation Playground

A Python-based Model Context Protocol (MCP) project demonstrating how AI assistants can interact with reusable platform-engineering tools.

The project provides tools for:

- Validating Terraform-based monitoring configurations
- Generating standardized monitoring module definitions
- Generating GitHub Actions CI workflows
- Applying reusable platform and reliability guardrails
- Reducing repetitive infrastructure and CI/CD work

This repository is designed as a public technical demonstration of MCP-based platform automation.

---

## Project Goals

The goal of this project is to demonstrate how MCP tools can help engineering teams:

- Standardize infrastructure configuration
- Validate monitoring resources before deployment
- Generate repeatable CI/CD workflows
- Apply platform guardrails consistently
- Reduce manual engineering effort
- Improve developer productivity
- Integrate AI-assisted automation into existing engineering workflows

The tools return structured results so they can be called by an MCP-compatible AI client.

---

## Architecture

```text
MCP-Compatible AI Client
          |
          | Model Context Protocol
          v
MCP Platform Automation Server
          |
          +-- Monitoring Configuration Validator
          |
          +-- Monitoring Module Generator
          |
          +-- GitHub Actions Workflow Generator
```

The MCP client interprets a natural-language request, selects the appropriate tool, submits structured input, and presents the generated or validated result to the user.

---

## Available MCP Tools

### 1. Monitoring Configuration Validator

Validates an existing Terraform monitoring configuration against reusable platform standards.

The validator can check areas such as:

- Required configuration fields
- Naming conventions
- Environment metadata
- Ownership and service tags
- Notification routing
- Threshold definitions
- Missing-data behavior
- Production escalation requirements
- Infrastructure-as-Code consistency

Example request:

```text
Validate this Terraform monitoring configuration and explain any violations.
```

Example response:

```json
{
  "ok": false,
  "errors": [
    "Missing required ownership tag",
    "Production monitoring must include an escalation destination"
  ],
  "warnings": []
}
```

---

### 2. Monitoring Module Generator

Generates a standardized Terraform module definition from structured input.

The tool can generate:

- Monitor name
- Monitor type
- Query
- Alert message
- Thresholds
- Environment information
- Ownership metadata
- Notification routing
- Missing-data behavior
- Suggested Terraform file path

Example request:

```text
Generate a Terraform monitor for a backend service with warning and critical thresholds.
```

The generated output can be reviewed before being added to an Infrastructure-as-Code repository.

---

### 3. GitHub Actions Workflow Generator

Generates a starter GitHub Actions CI workflow for supported application types.

Supported examples include:

- Python
- Node.js
- .NET
- Java
- Go

Example request:

```text
Generate a GitHub Actions CI workflow for a Python project using Python 3.11.
```

Example output location:

```text
.github/workflows/ci.yml
```

The generated workflow may include:

- Repository checkout
- Language runtime setup
- Dependency installation
- Build commands
- Automated tests
- Pull-request validation
- Main-branch validation
- Manual workflow execution

Generated workflows should be reviewed and adapted to the target application before production use.

---

## Technology Stack

- Python
- Model Context Protocol
- FastMCP
- Terraform HCL parsing
- GitHub Actions
- Docker
- Kubernetes
- YAML
- Infrastructure as Code

---

## Project Structure

```text
mcp-playground/
├── server.py
├── requirements.txt
├── README.md
├── .gitignore
├── Dockerfile
├── mcp.json
├── k8-local.yaml
├── examples/
│   ├── monitor-spec.json
│   ├── monitor-example.tf
│   └── workflow-spec.json
└── tests/
    └── test_server.py
```

Your local repository may contain slightly different filenames depending on how the server and examples are organized.

---

## Prerequisites

Install the following before running the project:

- Python 3.11 or later
- Git
- An MCP-compatible client
- Docker, optional
- A local Kubernetes environment, optional

---

## Local Installation

Clone the repository:

```bash
git clone https://github.com/sharmilaguptaGH/mcp-playground.git
cd mcp-playground
```

Create a Python virtual environment:

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Run the MCP Server

Run the server directly:

```bash
python server.py
```

When used through an MCP client, the server normally runs through the standard input/output transport and does not require a separate public network endpoint.

---

## MCP Client Configuration

Example MCP client configuration:

```json
{
  "servers": {
    "mcp-platform-automation-server": {
      "type": "stdio",
      "command": "python",
      "args": [
        "${workspaceFolder}/server.py"
      ]
    }
  }
}
```

For Windows environments using a project virtual environment:

```json
{
  "servers": {
    "mcp-platform-automation-server": {
      "type": "stdio",
      "command": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
      "args": [
        "${workspaceFolder}\\server.py"
      ]
    }
  }
}
```

Restart or reload the MCP client after updating its configuration.

---

## Example Prompts

### Validate a monitoring resource

```text
Validate this Terraform monitoring configuration and identify missing
tags, notification rules, or invalid missing-data settings.
```

### Generate a monitoring module

```text
Generate a Terraform monitoring module for a backend API latency alert.

Use:
- Warning threshold: 750 milliseconds
- Critical threshold: 1000 milliseconds
- Service: sample-api
- Environment: production
```

### Generate a CI workflow

```text
Generate a GitHub Actions CI workflow for a .NET application.

The workflow should:
- Run on pull requests
- Build the application
- Run tests
- Use an Ubuntu runner
```

---

## Running with Docker

Build the image:

```bash
docker build -t mcp-platform-automation-server .
```

Run the container:

```bash
docker run --rm -i mcp-platform-automation-server
```

The interactive option is required when using the standard input/output MCP transport.

---

## Local Kubernetes Deployment

The repository may include a sample Kubernetes manifest for local experimentation.

Apply it using:

```bash
kubectl apply -f k8-local.yaml
```

Check the deployment:

```bash
kubectl get deployments
kubectl get pods
kubectl get services
```

View logs:

```bash
kubectl logs deployment/mcp-platform-automation-server
```

The Kubernetes configuration is provided as a demonstration and should be reviewed before use in another environment.

---

## Testing

Run the automated tests:

```bash
pytest -q
```

Tests should cover:

- Valid monitoring configurations
- Missing required fields
- Invalid metadata
- Notification-routing rules
- Threshold validation
- Monitoring module generation
- GitHub Actions workflow generation

---

## Design Principles

### Structured tool inputs

The MCP tools accept structured inputs rather than relying exclusively on unstructured prompts.

### Deterministic validation

Validation rules are implemented in code so the same input produces consistent results.

### Human review

Generated infrastructure and CI/CD files should be reviewed before they are committed or deployed.

### Least privilege

An MCP tool should receive only the permissions required for its intended task.

### Clear tool boundaries

Each tool performs a focused task with explicit inputs and outputs.

### Auditability

Generated and validated results can be reviewed, tested, version-controlled, and approved through normal engineering workflows.

---

## Security and Public Repository Safety

This repository is intended for public demonstration and intentionally excludes:

- Credentials
- API keys
- Access tokens
- Passwords
- Private hostnames
- Internal repository addresses
- Proprietary organization names
- Customer information
- Production configuration
- Organization-specific environment settings

All examples use generic names and sample values.

Do not commit sensitive configuration or confidential source code to this repository.

Before publishing changes, review the repository with:

```bash
git grep -n -i "password"
git grep -n -i "secret"
git grep -n -i "token"
git grep -n -i "apikey"
git grep -n -i "private"
```

Also review the Git history because removing sensitive text from the latest files does not automatically remove it from previous commits.

---

## Current Limitations

This project is a technical demonstration and not a complete production platform.

Potential future improvements include:

- Additional automated tests
- JSON Schema validation
- Policy-as-code integration
- Pull-request comment generation
- Git repository integration
- Expanded CI/CD templates
- Additional Infrastructure-as-Code generators
- Approval workflows for generated changes
- Audit logging
- Role-based tool permissions
- Improved error handling
- OpenTelemetry instrumentation

---

## Future Enhancements

Planned ideas include:

- Generate complete CI/CD workflows for additional technology stacks
- Validate Kubernetes manifests
- Validate Terraform plans
- Generate reusable infrastructure modules
- Create pull-request summaries
- Suggest remediation for failed compliance checks
- Add policy-as-code validation
- Integrate runbook-based troubleshooting workflows
- Add human approval before write operations
- Support containerized and remote MCP transports

---

## What This Project Demonstrates

This project demonstrates practical experience with:

- MCP server development
- Python automation
- Infrastructure validation
- Terraform automation
- CI/CD workflow generation
- Platform guardrails
- Developer tooling
- AI-assisted engineering
- Structured tool design
- DevOps and SRE automation
- Docker and Kubernetes deployment concepts

---

## Author

**Sharmila Gupta**

GitHub: `https://github.com/sharmilaguptaGH`
