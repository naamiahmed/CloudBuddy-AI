"""Tests for CloudBuddyAgent, Bedrock Converse tool loop, and fallback diagnostic engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from agent import CloudBuddyAgent
from config import Config


class TestAgentBasics:
    """Verify basic agent initialization and input validation."""

    def test_empty_message_handling(self):
        agent = CloudBuddyAgent()
        res = agent.chat("")
        assert "Please describe" in res.content
        assert res.used_bedrock is False
        assert res.iterations == 0

        res_spaces = agent.chat("    ")
        assert "Please describe" in res_spaces.content

    def test_unsafe_infrastructure_change_request(self):
        agent = CloudBuddyAgent()
        res = agent.chat("Please delete all my ec2 instances immediately")
        assert "Advisory Mode Guardrail Triggered" in res.content
        assert "read-only advisory mode" in res.content
        assert res.used_bedrock is False

    def test_unsafe_security_group_change(self):
        agent = CloudBuddyAgent()
        res = agent.chat("modify security group to 0.0.0.0/0 on all ports")
        assert "Advisory Mode Guardrail Triggered" in res.content


class TestFallbackDiagnosticEngine:
    """Verify deterministic fallback engine behavior when Bedrock is unavailable."""

    def test_fallback_vague_input_clarification(self):
        agent = CloudBuddyAgent()
        res_text, tools = agent.run_fallback_diagnostic("it is broken help")
        assert "Clarification Needed" in res_text
        assert "Which component is failing" in res_text
        assert len(tools) == 0

    def test_fallback_ec2_diagnostic(self):
        agent = CloudBuddyAgent()
        res_text, tools = agent.run_fallback_diagnostic("My EC2 instance is running but web port 80 won't load")
        assert "Notice: Rule-Based Diagnostic Advisory Mode" in res_text
        assert "EC2 Web Connectivity" in res_text
        assert "Problem summary" in res_text
        assert "Step-by-step checks" in res_text
        assert len(tools) == 1
        assert tools[0]["tool"] == "get_ec2_troubleshooting_steps"

    def test_fallback_http_502_diagnostic(self):
        agent = CloudBuddyAgent()
        res_text, tools = agent.run_fallback_diagnostic("Getting 502 bad gateway with Nginx reverse proxy")
        assert "502 Bad Gateway" in res_text
        assert len(tools) == 1
        assert tools[0]["tool"] == "get_http_troubleshooting_steps"

    def test_fallback_s3_access_denied(self):
        agent = CloudBuddyAgent()
        res_text, tools = agent.run_fallback_diagnostic("S3 bucket returning AccessDenied on PutObject")
        assert "S3 AccessDenied" in res_text
        assert len(tools) == 1
        assert tools[0]["tool"] == "get_s3_access_denied_steps"

    def test_fallback_k8s_crashloop(self):
        agent = CloudBuddyAgent()
        res_text, tools = agent.run_fallback_diagnostic("Kubernetes pod stuck in CrashLoopBackOff")
        assert "CrashLoopBackOff" in res_text
        assert len(tools) == 1
        assert tools[0]["tool"] == "get_kubernetes_troubleshooting_steps"

    def test_fallback_docker_exit(self):
        agent = CloudBuddyAgent()
        res_text, tools = agent.run_fallback_diagnostic("Docker container killed with exit 137")
        assert "Docker" in res_text
        assert len(tools) == 1
        assert tools[0]["tool"] == "get_docker_troubleshooting_steps"

    def test_fallback_unknown_error_explanation(self):
        agent = CloudBuddyAgent()
        res_text, tools = agent.run_fallback_diagnostic("Encountered unusual network timeout error")
        assert "Problem summary" in res_text
        assert len(tools) == 1
        assert tools[0]["tool"] == "explain_error"


class TestBedrockConverseAgentLoop:
    """Verify Bedrock Converse API request/tool/result/response loop with mocks."""

    @patch("agent.CloudBuddyAgent.bedrock_client")
    def test_successful_direct_turn(self, mock_bedrock):
        """Model answers directly without tool use."""
        mock_bedrock.converse.return_value = {
            "stopReason": "end_turn",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "### Problem summary\nEverything looks normal."}],
                }
            },
        }

        agent = CloudBuddyAgent()
        res = agent.chat("How do I check my IP?")
        assert res.used_bedrock is True
        assert res.iterations == 1
        assert "Everything looks normal" in res.content
        assert len(res.tool_calls) == 0

    @patch("agent.CloudBuddyAgent.bedrock_client")
    def test_tool_use_and_return_cycle(self, mock_bedrock):
        """Model calls a tool on turn 1, then answers on turn 2."""
        turn_1_resp = {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tool_call_123",
                                "name": "get_ec2_troubleshooting_steps",
                                "input": {"issue_type": "web_unreachable"},
                            }
                        }
                    ],
                }
            },
        }
        turn_2_resp = {
            "stopReason": "end_turn",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "text": "### Problem summary\nBased on the diagnostic checks, verify your security groups."
                        }
                    ],
                }
            },
        }

        mock_bedrock.converse.side_effect = [turn_1_resp, turn_2_resp]

        agent = CloudBuddyAgent()
        res = agent.chat("My EC2 web server is not reachable")

        assert res.used_bedrock is True
        assert res.iterations == 2
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0]["tool"] == "get_ec2_troubleshooting_steps"
        assert "verify your security groups" in res.content

    @patch("agent.CloudBuddyAgent.bedrock_client")
    def test_max_tool_loops_safeguard(self, mock_bedrock):
        """Ensure agent respects max_tool_loops and does not enter an infinite loop."""
        continuous_tool_use = {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tool_call_loop",
                                "name": "explain_error",
                                "input": {"error_message": "test error"},
                            }
                        }
                    ],
                }
            },
        }
        mock_bedrock.converse.return_value = continuous_tool_use

        cfg = Config(max_tool_loops=3)
        agent = CloudBuddyAgent(config=cfg)
        res = agent.chat("Test loop protection")

        assert res.iterations == 3
        assert len(res.tool_calls) == 3
        assert res.used_bedrock is True

    @patch("agent.CloudBuddyAgent.bedrock_client")
    def test_model_throttling_fallback(self, mock_bedrock):
        """Ensure ThrottlingException triggers fallback without crashing."""
        mock_bedrock.converse.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate limit exceeded"}},
            "Converse",
        )

        agent = CloudBuddyAgent()
        res = agent.chat("EC2 website times out on port 80")

        assert res.used_bedrock is False
        assert res.fallback_mode is True
        assert "Notice: Rule-Based Diagnostic Advisory Mode" in res.content
        assert "EC2 Web Connectivity" in res.content
        assert "ThrottlingException" in res.error

    @patch("agent.CloudBuddyAgent.bedrock_client")
    def test_no_credentials_fallback(self, mock_bedrock):
        """Ensure missing AWS credentials triggers fallback seamlessly."""
        mock_bedrock.converse.side_effect = NoCredentialsError()

        agent = CloudBuddyAgent()
        res = agent.chat("502 bad gateway with Nginx")

        assert res.used_bedrock is False
        assert res.fallback_mode is True
        assert "502 Bad Gateway" in res.content
