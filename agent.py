"""Core agent engine for CloudBuddy AI.

Implements the Amazon Bedrock Converse API agent loop with autonomous
tool calling, loop safeguards, strict safety controls, and a transparent
deterministic fallback engine when Bedrock model access is unavailable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from config import Config, get_boto3_session
from tools import dispatch_tool, get_tools_spec

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are CloudBuddy AI, an expert and beginner-friendly AWS DevOps Troubleshooting Assistant.
Your mission is to help junior Cloud Engineers, DevOps Engineers, and IT students diagnose and resolve common cloud, container, and infrastructure problems.

Guiding Principles:
1. Explain technical concepts in clear, simple English without unnecessary jargon.
2. Structure every diagnostic recommendation with clarity and precision:
   - **Problem summary**: Plain-English description of the issue.
   - **Likely causes**: 3-5 probable root causes ranked by likelihood.
   - **Step-by-step checks**: Ordered diagnostic steps. For EVERY check explain:
     - What to check
     - Why this check matters
     - Command or AWS Console location (safe, read-only commands)
     - Expected result for a healthy system
     - Next step depending on the result
   - **Safety considerations**: Production safety warnings, least privilege, backup advice.
3. Information Completeness:
   - If the user's inquiry is missing critical details (e.g. "my website is down" without specifying EC2 vs S3 vs ECS, error code, or OS), ask friendly clarifying questions before making broad assumptions.
4. Tool Selection:
   - Use the available diagnostic tools (get_ec2_troubleshooting_steps, get_http_troubleshooting_steps, get_s3_access_denied_steps, get_iam_troubleshooting_steps, get_docker_troubleshooting_steps, get_kubernetes_troubleshooting_steps, get_cicd_troubleshooting_steps, explain_error) to retrieve structured runbooks and enrich your guidance.
5. Strict Safety & Advisory Boundaries:
   - You operate in ADVISORY MODE ONLY. You do NOT make changes to live infrastructure.
   - If a user asks you to modify, create, or delete AWS resources (e.g. "delete my EC2 instances", "add 0.0.0.0/0 to my security group"), politely decline, remind them of advisory mode, and provide the safe, verified procedure they should review manually.
   - NEVER invent or claim to have inspected real AWS resource IDs, real metrics, or live server logs. Clarify that commands must be run by the user.
   - Never print or request AWS secret keys or credentials.
"""


@dataclass
class AgentResponse:
    """Standardized response from CloudBuddy Agent."""

    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    used_bedrock: bool = False
    iterations: int = 0
    error: Optional[str] = None
    fallback_mode: bool = False


class CloudBuddyAgent:
    """Agent orchestrator managing Bedrock Converse API tool calls and fallback diagnostics."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_env()
        self._session = None
        self._bedrock_client = None

    @property
    def session(self) -> boto3.Session:
        """Lazy initialized Boto3 Session."""
        if self._session is None:
            self._session = get_boto3_session(self.config)
        return self._session

    @property
    def bedrock_client(self):
        """Lazy initialized Bedrock Runtime client."""
        if self._bedrock_client is None:
            self._bedrock_client = self.session.client(
                "bedrock-runtime",
                region_name=self.config.aws_region,
            )
        return self._bedrock_client

    def chat(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentResponse:
        """Process user message through Bedrock Converse API with tool execution loop.

        Falls back seamlessly to deterministic rules if Bedrock access is unavailable.
        """
        clean_input = (user_message or "").strip()
        if not clean_input:
            return AgentResponse(
                content="Please describe the infrastructure or cloud issue you'd like help troubleshooting.",
                tool_calls=[],
                used_bedrock=False,
                iterations=0,
            )

        # Check for immediate unsafe modification requests
        is_unsafe, unsafe_msg = self._check_unsafe_infrastructure_request(clean_input)
        if is_unsafe:
            return AgentResponse(
                content=unsafe_msg,
                tool_calls=[],
                used_bedrock=False,
                iterations=0,
            )

        # Build initial messages list from history
        messages = self._format_conversation_history(conversation_history or [])
        messages.append({
            "role": "user",
            "content": [{"text": clean_input}],
        })

        tool_config = {"tools": get_tools_spec()}
        tools_executed: List[Dict[str, Any]] = []
        iteration = 0

        try:
            while iteration < self.config.max_tool_loops:
                iteration += 1

                # Call Bedrock Converse API
                response = self.bedrock_client.converse(
                    modelId=self.config.bedrock_model_id,
                    messages=messages,
                    system=[{"text": SYSTEM_PROMPT}],
                    toolConfig=tool_config,
                    inferenceConfig={
                        "temperature": self.config.temperature,
                        "maxTokens": self.config.max_tokens,
                    },
                )

                stop_reason = response.get("stopReason")
                output_message = response.get("output", {}).get("message", {})
                message_content = output_message.get("content", [])

                # Add assistant response to conversation trajectory
                messages.append({
                    "role": "assistant",
                    "content": message_content,
                })

                if stop_reason == "tool_use":
                    # Find tool use blocks
                    tool_result_blocks = []
                    for block in message_content:
                        if "toolUse" in block:
                            tool_use = block["toolUse"]
                            tool_use_id = tool_use.get("toolUseId")
                            tool_name = tool_use.get("name")
                            tool_input = tool_use.get("input", {})

                            # Execute tool safely
                            tool_result = dispatch_tool(tool_name, tool_input)
                            tools_executed.append({
                                "tool": tool_name,
                                "input": tool_input,
                                "result_preview": str(tool_result)[:150],
                            })

                            tool_result_blocks.append({
                                "toolResult": {
                                    "toolUseId": tool_use_id,
                                    "content": [{"json": tool_result}],
                                    "status": "success",
                                }
                            })

                    # Supply tool results back to Bedrock
                    messages.append({
                        "role": "user",
                        "content": tool_result_blocks,
                    })

                elif stop_reason in ("end_turn", "stop_sequence"):
                    # Model produced final answer
                    final_text = self._extract_text(message_content)
                    return AgentResponse(
                        content=final_text,
                        tool_calls=tools_executed,
                        used_bedrock=True,
                        iterations=iteration,
                    )
                else:
                    # Other stop reasons (e.g. max_tokens)
                    final_text = self._extract_text(message_content)
                    return AgentResponse(
                        content=final_text or "Analysis completed.",
                        tool_calls=tools_executed,
                        used_bedrock=True,
                        iterations=iteration,
                    )

            # Reached max tool loops
            final_text = self._extract_text(messages[-1].get("content", []))
            if not final_text:
                final_text = "I completed the diagnostic tool evaluation. Please review the recommended checks above."

            return AgentResponse(
                content=final_text,
                tool_calls=tools_executed,
                used_bedrock=True,
                iterations=iteration,
            )

        except (ClientError, EndpointConnectionError, NoCredentialsError) as aws_err:
            logger.warning(
                "Amazon Bedrock API unavailable (%s: %s). Activating Fallback Diagnostic Engine.",
                type(aws_err).__name__,
                str(aws_err),
            )
            fallback_text, fallback_tools = self.run_fallback_diagnostic(clean_input, str(aws_err))
            return AgentResponse(
                content=fallback_text,
                tool_calls=fallback_tools,
                used_bedrock=False,
                iterations=1,
                error=f"{type(aws_err).__name__}: {str(aws_err)}",
                fallback_mode=True,
            )
        except Exception as generic_err:
            logger.error("Unexpected error in agent loop: %s", str(generic_err))
            fallback_text, fallback_tools = self.run_fallback_diagnostic(clean_input, str(generic_err))
            return AgentResponse(
                content=fallback_text,
                tool_calls=fallback_tools,
                used_bedrock=False,
                iterations=1,
                error=str(generic_err),
                fallback_mode=True,
            )

    def _extract_text(self, content_blocks: List[Dict[str, Any]]) -> str:
        """Extract joined text strings from Bedrock message content blocks."""
        texts = []
        for block in content_blocks:
            if "text" in block:
                texts.append(block["text"])
        return "\n\n".join(texts).strip()

    def _format_conversation_history(
        self, history: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert session state history into Bedrock Converse API message format."""
        formatted: List[Dict[str, Any]] = []
        for item in history:
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and content:
                formatted.append({
                    "role": role,
                    "content": [{"text": str(content)}],
                })
        return formatted

    def _check_unsafe_infrastructure_request(self, message: str) -> Tuple[bool, str]:
        """Detect attempts to alter or delete infrastructure and enforce advisory mode."""
        msg_lower = message.lower()
        destructive_keywords = [
            "delete all my ec2",
            "delete my ec2",
            "terminate instance",
            "destroy my vpc",
            "terraform destroy",
            "drop database",
            "delete bucket",
            "rm -rf /",
            "modify security group to 0.0.0.0/0",
            "add 0.0.0.0/0",
            "open all ports",
        ]

        for keyword in destructive_keywords:
            if keyword in msg_lower:
                return (
                    True,
                    "🛡️ **Advisory Mode Guardrail Triggered**\n\n"
                    "CloudBuddy operates in **read-only advisory mode** and does not modify, create, "
                    "or delete AWS infrastructure or execute destructive commands.\n\n"
                    f"**Detected Request:** `{message}`\n\n"
                    "### Why this is restricted:\n"
                    "- Modifying security group rules, deleting instances, or dropping infrastructure should always be performed "
                    "with least-privilege change controls through audited Infrastructure as Code (IaC) or the AWS Management Console.\n\n"
                    "### Safe Alternative:\n"
                    "If you need to change your infrastructure, please review the AWS documentation and verify configuration changes "
                    "in a non-production environment first.",
                )

        return False, ""

    def run_fallback_diagnostic(
        self,
        user_message: str,
        reason: Optional[str] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Transparent, rule-based diagnostic engine when Bedrock model access is unavailable.

        Guarantees that CloudBuddy remains fully functional and useful without
        ever misrepresenting rule outputs as live AI generations.
        """
        msg_lower = user_message.lower()
        tools_executed: List[Dict[str, Any]] = []

        # Check for vague inquiries requiring clarification
        words = user_message.split()
        if (
            len(words) <= 5
            and any(w in msg_lower for w in ["broken", "down", "help", "not working", "test", "issue"])
            and not any(svc in msg_lower for svc in ["ec2", "s3", "502", "504", "k8s", "docker", "iam", "pod", "nginx"])
        ):
            clarification = (
                "> ℹ️ **Notice: Rule-Based Diagnostic Advisory Mode**  \n\n"
                "### 🔍 Clarification Needed\n\n"
                "To give you an accurate diagnostic plan, could you provide a few more details?\n\n"
                "1. **Which component is failing?** (e.g. EC2 instance, S3 bucket, Docker container, Kubernetes pod, GitHub Actions pipeline)\n"
                "2. **What error code or message do you see?** (e.g. HTTP 502, S3 AccessDenied, CrashLoopBackOff, Connection Refused)\n"
                "3. **What was the expected behavior?** (e.g. browser opening your website, Lambda reading a bucket)\n\n"
                "*Tip: You can also copy and paste the exact error log snippet here.*"
            )
            return clarification, []

        # Match intent to diagnostic tool
        if any(w in msg_lower for w in ["s3", "bucket", "accessdenied", "access denied", "putobject", "getobject"]):
            tool_name = "get_s3_access_denied_steps"
            tool_args = {"operation": "GetObject", "requester_type": "iam_role"}
            tool_res = dispatch_tool(tool_name, tool_args)
            tools_executed.append({"tool": tool_name, "input": tool_args, "result_preview": str(tool_res)[:150]})
            markdown = self._format_tool_result_as_advisory(tool_res)

        elif any(w in msg_lower for w in ["502", "bad gateway", "504", "gateway timeout", "nginx", "apache"]):
            code = 504 if "504" in msg_lower else 502
            tool_name = "get_http_troubleshooting_steps"
            tool_args = {"error_code": code, "web_server": "nginx"}
            tool_res = dispatch_tool(tool_name, tool_args)
            tools_executed.append({"tool": tool_name, "input": tool_args, "result_preview": str(tool_res)[:150]})
            markdown = self._format_tool_result_as_advisory(tool_res)

        elif any(w in msg_lower for w in ["ec2", "ssh", "port 80", "port 443", "unreachable", "security group", "status check"]):
            issue_type = "ssh_failure" if "ssh" in msg_lower or "port 22" in msg_lower else "web_unreachable"
            tool_name = "get_ec2_troubleshooting_steps"
            tool_args = {"issue_type": issue_type, "os_type": "linux"}
            tool_res = dispatch_tool(tool_name, tool_args)
            tools_executed.append({"tool": tool_name, "input": tool_args, "result_preview": str(tool_res)[:150]})
            markdown = self._format_tool_result_as_advisory(tool_res)

        elif any(w in msg_lower for w in ["kubernetes", "k8s", "crashloopbackoff", "pod", "imagepullbackoff", "oomkilled"]):
            pod_status = "CrashLoopBackOff"
            if "imagepull" in msg_lower:
                pod_status = "ImagePullBackOff"
            elif "pending" in msg_lower:
                pod_status = "Pending"
            tool_name = "get_kubernetes_troubleshooting_steps"
            tool_args = {"pod_status": pod_status}
            tool_res = dispatch_tool(tool_name, tool_args)
            tools_executed.append({"tool": tool_name, "input": tool_args, "result_preview": str(tool_res)[:150]})
            markdown = self._format_tool_result_as_advisory(tool_res)

        elif any(w in msg_lower for w in ["docker", "container", "exit 137", "exit code"]):
            tool_name = "get_docker_troubleshooting_steps"
            tool_args = {"failure_type": "container_exit"}
            tool_res = dispatch_tool(tool_name, tool_args)
            tools_executed.append({"tool": tool_name, "input": tool_args, "result_preview": str(tool_res)[:150]})
            markdown = self._format_tool_result_as_advisory(tool_res)

        elif any(w in msg_lower for w in ["iam", "policy", "permission denied", "unauthorized", "decode-authorization"]):
            tool_name = "get_iam_troubleshooting_steps"
            tool_args = {"action": "*", "resource_arn": "*"}
            tool_res = dispatch_tool(tool_name, tool_args)
            tools_executed.append({"tool": tool_name, "input": tool_args, "result_preview": str(tool_res)[:150]})
            markdown = self._format_tool_result_as_advisory(tool_res)

        elif any(w in msg_lower for w in ["github action", "pipeline", "ci/cd", "workflow", "oidc"]):
            tool_name = "get_cicd_troubleshooting_steps"
            tool_args = {"failure_type": "workflow_failure"}
            tool_res = dispatch_tool(tool_name, tool_args)
            tools_executed.append({"tool": tool_name, "input": tool_args, "result_preview": str(tool_res)[:150]})
            markdown = self._format_tool_result_as_advisory(tool_res)

        else:
            # Use explain_error as fallback
            tool_name = "explain_error"
            tool_args = {"error_message": user_message}
            tool_res = dispatch_tool(tool_name, tool_args)
            tools_executed.append({"tool": tool_name, "input": tool_args, "result_preview": str(tool_res)[:150]})
            markdown = (
                f"## 🛠️ Diagnostic Runbook: {tool_res.get('identified_type')}\n\n"
                f"### Problem summary\n\n"
                f"{tool_res.get('plain_english_summary')}\n\n"
                f"### Likely causes\n\n"
                f"- {tool_res.get('why_it_happens')}\n\n"
                f"### Step-by-step checks\n\n"
                f"1. **Analyze Error Signature**: Review `{tool_res.get('identified_type')}`.\n"
                f"2. **Immediate Action**: {tool_res.get('immediate_action')}\n\n"
                f"### Safety considerations\n\n"
                f"Always verify commands in a non-production environment before applying them to production servers."
            )

        # Prepend honest notice explaining fallback mode
        fallback_banner = (
            "> ℹ️ **Notice: Rule-Based Diagnostic Advisory Mode**  \n"
            "> Amazon Bedrock model inference is currently unavailable in this session (e.g. model access pending or throttling). "
            "CloudBuddy is providing deterministic diagnostic guidance from its verified DevOps runbooks.\n\n---\n\n"
        )
        return fallback_banner + markdown, tools_executed

    def _format_tool_result_as_advisory(self, tool_data: Dict[str, Any]) -> str:
        """Render a tool's structured output into CloudBuddy's standard 8-section layout."""
        lines = []

        category = tool_data.get("category")
        if category:
            lines.append(f"## 🛠️ Diagnostic Runbook: {category}\n")

        summary = tool_data.get("problem_summary", "Diagnostic investigation.")
        lines.append(f"### Problem summary\n{summary}\n")

        causes = tool_data.get("likely_causes", [])
        if causes:
            lines.append("### Likely causes")
            for c in causes:
                lines.append(f"- {c}")
            lines.append("")

        checks = tool_data.get("step_by_step_checks", [])
        if checks:
            lines.append("### Step-by-step checks\n")
            for chk in checks:
                step_num = chk.get("step", 1)
                title = chk.get("title", f"Check {step_num}")
                what = chk.get("what_to_check", "")
                why = chk.get("why_it_matters", "")
                cmd = chk.get("command_or_console", "")
                exp = chk.get("expected_result", "")
                nxt = chk.get("next_step", "")

                lines.append(f"#### Step {step_num}: {title}")
                lines.append(f"- **What to check**: {what}")
                lines.append(f"- **Why this check matters**: {why}")
                if cmd:
                    if "\n" in cmd or ";" in cmd or "aws " in cmd or "sudo " in cmd or "docker " in cmd or "kubectl " in cmd:
                        lines.append(f"- **Command or Console location**:\n```bash\n{cmd}\n```")
                    else:
                        lines.append(f"- **Command or Console location**: `{cmd}`")
                lines.append(f"- **Expected result**: {exp}")
                lines.append(f"- **Next step**: {nxt}\n")

        safety = tool_data.get("safety_considerations")
        if safety:
            lines.append(f"### Safety considerations\n{safety}\n")

        return "\n".join(lines)
