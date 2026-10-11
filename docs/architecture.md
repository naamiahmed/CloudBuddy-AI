# CloudBuddy AI — Architecture & System Design

CloudBuddy AI is an AI-powered AWS & DevOps troubleshooting assistant designed for junior cloud engineers, DevOps trainees, and IT students. It provides deterministic, structured, and read-only diagnostic guidance for cloud and container incidents without modifying customer infrastructure.

---

## 1. System Overview & Component Diagram

The following Mermaid diagram illustrates the architectural layout of CloudBuddy AI, showing how user requests flow from the browser through Streamlit, into the agent orchestrator, Bedrock Converse API, diagnostic tools, and AWS SDK provider chain.

```mermaid
flowchart TD
    subgraph Client ["Client Layer"]
        User["Junior Cloud / DevOps Engineer"]
        Browser["Modern Web Browser"]
    end

    subgraph Presentation ["Presentation Layer (Streamlit)"]
        UI["app.py (Streamlit UI)"]
        Theme["Dark Theme & Blue Accents (.streamlit/config.toml)"]
        SessionState["st.session_state (Messages, Config, Tool Logs)"]
    end

    subgraph AgentEngine ["Agent Orchestration Layer"]
        Agent["CloudBuddyAgent (agent.py)"]
        Guardrails["Advisory Guardrails (Destructive Command Blocker)"]
        ToolLoop["Bedrock Converse Tool Loop (Max Iteration Safeguard)"]
        Fallback["Deterministic Advisory Engine (Offline/Throttling Fallback)"]
    end

    subgraph Diagnostics ["Diagnostic Runbooks & Tools (tools.py)"]
        EC2Tool["get_ec2_troubleshooting_steps"]
        HTTPTool["get_http_troubleshooting_steps"]
        S3Tool["get_s3_access_denied_steps"]
        IAMTool["get_iam_troubleshooting_steps"]
        DockerTool["get_docker_troubleshooting_steps"]
        K8sTool["get_kubernetes_troubleshooting_steps"]
        CICDTool["get_cicd_troubleshooting_steps"]
        ParserTool["explain_error"]
    end

    subgraph AWSCloud ["AWS Cloud & SDK Integration"]
        Boto3Session["boto3.Session (config.py)"]
        AWSCredsChain["AWS Credential Provider Chain (CLI Profile / IAM / Env)"]
        BedrockConverse["Amazon Bedrock Runtime (Converse API)"]
        FoundationModel["Bedrock Foundation Model (Claude 3.5 Sonnet / Nova Lite)"]
    end

    %% Interactions
    User -->|Interacts with UI / Example Scenarios| Browser
    Browser -->|HTTP / WebSocket| UI
    UI <--> SessionState
    UI -->|Submits query| Agent
    Agent --> Guardrails
    Guardrails -->|Passed Safe Input| ToolLoop
    Guardrails -->|Destructive Action Blocked| UI
    
    ToolLoop -->|converse(messages, tools)| BedrockConverse
    BedrockConverse --> FoundationModel
    FoundationModel -->|stopReason = tool_use| ToolLoop
    
    ToolLoop -->|Dispatches safe tool| Diagnostics
    Diagnostics -->|Returns curated runbook| ToolLoop
    ToolLoop -->|converse(toolResults)| BedrockConverse
    FoundationModel -->|stopReason = end_turn| ToolLoop
    
    ToolLoop -.->|If Bedrock throttled / unavailable| Fallback
    Fallback -->|Directly invokes runbooks| Diagnostics
    
    Boto3Session --> AWSCredsChain
    Boto3Session --> BedrockConverse
    Agent -.-> Boto3Session
    
    ToolLoop -->|Structured 8-section guidance| UI
    Fallback -->|Structured 8-section guidance + banner| UI
```

---

## 2. Request & Execution Flow

### Standard AI Agent Flow (Bedrock Converse API with Tool Calling)
1. **User Query**: User submits an incident description (e.g. *"My EC2 instance is running, but port 80 won't open"*).
2. **Safety Guardrail Inspection**: The agent checks for destructive actions (e.g. requests to delete instances, drop databases, or widen security groups to `0.0.0.0/0`). If detected, the agent returns an advisory warning and refuses the action.
3. **Bedrock Converse Request**: The agent builds a message trajectory with the system prompt, conversation history, and tool specifications (`get_tools_spec()`).
4. **Autonomous Tool Selection**: The foundation model inspects the user inquiry and determines which diagnostic tool to invoke (e.g. `get_ec2_troubleshooting_steps`).
5. **Deterministic Tool Execution**: The agent dispatches the call strictly to the safe Python function in `tools.py`. The tool returns curated, read-only diagnostic steps with console paths, commands, expected results, and safety considerations.
6. **Tool Result Feedback**: The tool output is wrapped into a `toolResult` content block and passed back to Bedrock via `converse()`.
7. **Synthesis & Final Answer**: The model produces a beginner-friendly diagnosis formatted according to CloudBuddy's 8-section structure.

### Fallback Advisory Flow (Transparent Rule-Based Mode)
When Amazon Bedrock model inference is unavailable (e.g. model access pending in the AWS console, service throttling, or offline development):
1. The agent catches the SDK exception (`ClientError`, `NoCredentialsError`, `EndpointConnectionError`).
2. Rather than crashing or showing a generic error, the agent activates the **Fallback Advisory Engine**.
3. It identifies the operational domain (EC2, S3, HTTP, Kubernetes, Docker, IAM, CI/CD) and dispatches the exact same safe tool deterministically.
4. It formats the response using the identical 8-section layout and prepends an honest, transparent banner explaining that advisory mode is active.

---

## 3. Security Boundaries & Principles

- **No AWS Infrastructure Modification**: CloudBuddy AI is strictly advisory. No mutating AWS API calls (`Create*`, `Update*`, `Delete*`, `Authorize*`) exist in the application codebase.
- **Zero Local Shell Execution**: CloudBuddy does NOT execute shell commands on the user's computer. It presents safe commands with syntax highlighting and explains what each command does so the engineer retains complete human-in-the-loop control.
- **AWS Credential Provider Chain**: The app never stores, prompts for, or exposes AWS Secret Access Keys. It relies on standard AWS credentials (`~/.aws/credentials`, named profiles, or IAM roles).
- **Least-Privilege Recommendation**: Every runbook stresses least-privilege policies and warns against common insecure habits (such as opening ports to `0.0.0.0/0` or attaching `AdministratorAccess`).
