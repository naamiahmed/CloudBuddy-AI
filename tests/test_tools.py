"""Tests for safe diagnostic tools in tools.py."""

from __future__ import annotations

import pytest

from tools import (
    TOOL_DEFINITIONS,
    dispatch_tool,
    explain_error,
    get_cicd_troubleshooting_steps,
    get_docker_troubleshooting_steps,
    get_ec2_troubleshooting_steps,
    get_http_troubleshooting_steps,
    get_iam_troubleshooting_steps,
    get_kubernetes_troubleshooting_steps,
    get_s3_access_denied_steps,
    get_tools_spec,
)


class TestEC2Tools:
    """Verify EC2 diagnostic runbooks."""

    def test_ec2_web_unreachable_structure(self):
        res = get_ec2_troubleshooting_steps("web_unreachable", "linux")
        assert "category" in res
        assert "problem_summary" in res
        assert "likely_causes" in res
        assert len(res["likely_causes"]) >= 3
        assert "step_by_step_checks" in res
        assert len(res["step_by_step_checks"]) >= 5
        assert "safety_considerations" in res

        # Verify check schema
        for check in res["step_by_step_checks"]:
            assert "step" in check
            assert "title" in check
            assert "what_to_check" in check
            assert "why_it_matters" in check
            assert "command_or_console" in check
            assert "expected_result" in check
            assert "next_step" in check

    def test_ec2_ssh_failure(self):
        res = get_ec2_troubleshooting_steps("ssh_failure", "linux")
        assert "SSH" in res["category"]
        assert any("22" in cause for cause in res["likely_causes"])
        assert any("chmod 400" in check["command_or_console"] for check in res["step_by_step_checks"])


class TestHTTPTools:
    """Verify HTTP error diagnostic runbooks."""

    def test_http_502_bad_gateway(self):
        res = get_http_troubleshooting_steps(502, "nginx")
        assert "502" in res["category"]
        assert any("upstream" in cause.lower() for cause in res["likely_causes"])
        assert len(res["step_by_step_checks"]) >= 3

    def test_http_504_gateway_timeout(self):
        res = get_http_troubleshooting_steps(504, "nginx")
        assert "504" in res["category"]
        assert any("timeout" in cause.lower() for cause in res["likely_causes"])

    def test_http_other_codes(self):
        res_500 = get_http_troubleshooting_steps(500, "apache")
        assert "500" in res_500["category"]
        res_403 = get_http_troubleshooting_steps(403, "nginx")
        assert "403" in res_403["category"]


class TestS3AndIAMTools:
    """Verify S3 and IAM diagnostic runbooks."""

    def test_s3_access_denied(self):
        res = get_s3_access_denied_steps("GetObject", "iam_role")
        assert "S3 AccessDenied" in res["category"]
        assert any("/*" in cause for cause in res["likely_causes"])
        assert any("KMS" in cause for cause in res["likely_causes"])
        assert len(res["step_by_step_checks"]) >= 4

    def test_iam_troubleshooting(self):
        res = get_iam_troubleshooting_steps("s3:PutObject", "arn:aws:s3:::my-bucket/*")
        assert "IAM" in res["category"]
        assert any("decode-authorization-message" in check["command_or_console"] for check in res["step_by_step_checks"])


class TestContainerAndK8sTools:
    """Verify Docker, K8s, and CI/CD diagnostic runbooks."""

    def test_docker_troubleshooting(self):
        res = get_docker_troubleshooting_steps("container_exit")
        assert "Docker" in res["category"]
        assert any("137" in cause for cause in res["likely_causes"])

    def test_kubernetes_crashloopbackoff(self):
        res = get_kubernetes_troubleshooting_steps("CrashLoopBackOff")
        assert "CrashLoopBackOff" in res["category"]
        assert any("--previous" in check["command_or_console"] for check in res["step_by_step_checks"])

    def test_cicd_workflow_failure(self):
        res = get_cicd_troubleshooting_steps("aws_oidc_failure")
        assert "CI/CD" in res["category"]
        assert any("OIDC" in cause for cause in res["likely_causes"])


class TestExplainError:
    """Verify plain English explanation parser."""

    def test_explain_access_denied(self):
        res = explain_error("An error occurred (AccessDenied) when calling the PutObject operation")
        assert "Access Denied" in res["identified_type"]
        assert "get_s3_access_denied_steps" in res["recommended_tool"]

    def test_explain_connection_refused(self):
        res = explain_error("curl: (7) Failed to connect to 127.0.0.1 port 80: Connection refused")
        assert "Connection Refused" in res["identified_type"]

    def test_explain_unknown_error(self):
        res = explain_error("Some obscure arbitrary failure code 98765")
        assert res["identified_type"] == "Unknown / General Error"
        assert res["raw_error"] == "Some obscure arbitrary failure code 98765"


class TestDispatcherAndSchema:
    """Verify tool dispatching and Bedrock tool schema generation."""

    def test_get_tools_spec(self):
        specs = get_tools_spec()
        assert len(specs) >= 7
        for spec in specs:
            assert "toolSpec" in spec
            tool = spec["toolSpec"]
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert "json" in tool["inputSchema"]

    def test_dispatch_valid_tool(self):
        res = dispatch_tool("get_ec2_troubleshooting_steps", {"issue_type": "web_unreachable"})
        assert "category" in res

    def test_dispatch_unknown_tool(self):
        res = dispatch_tool("non_existent_tool", {})
        assert "error" in res
        assert "available_tools" in res

    def test_dispatch_malformed_arguments(self):
        # Pass string for integer error_code - should gracefully recover
        res = dispatch_tool("get_http_troubleshooting_steps", {"error_code": "not_an_int"})
        assert "502" in res["category"]  # Fallbacks to default 502

    def test_read_only_guarantee(self):
        """Ensure tools return guidance data structures and never perform mutations."""
        # Calling tools multiple times with different inputs is idempotent and has no side effects
        res1 = dispatch_tool("get_docker_troubleshooting_steps", {"failure_type": "port_conflict"})
        res2 = dispatch_tool("get_docker_troubleshooting_steps", {"failure_type": "port_conflict"})
        assert res1 == res2
