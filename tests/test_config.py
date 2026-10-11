"""Tests for configuration management and AWS credentials handling in config.py."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

from config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_LOOPS,
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    DEFAULT_TEMPERATURE,
    Config,
    get_boto3_session,
    validate_aws_and_bedrock,
)


class TestConfigDefaults:
    """Verify default configuration behavior."""

    def test_default_config_values(self):
        cfg = Config()
        assert cfg.aws_region == DEFAULT_REGION
        assert cfg.aws_profile is None
        assert cfg.bedrock_model_id == DEFAULT_MODEL_ID
        assert cfg.max_tool_loops == DEFAULT_MAX_TOOL_LOOPS
        assert cfg.temperature == DEFAULT_TEMPERATURE
        assert cfg.max_tokens == DEFAULT_MAX_TOKENS

    def test_from_env_with_custom_values(self):
        env_vars = {
            "AWS_REGION": "eu-central-1",
            "AWS_PROFILE": "test-profile",
            "BEDROCK_MODEL_ID": "amazon.nova-lite-v1:0",
            "MAX_TOOL_LOOPS": "7",
            "TEMPERATURE": "0.3",
            "MAX_TOKENS": "1000",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            cfg = Config.from_env()
            assert cfg.aws_region == "eu-central-1"
            assert cfg.aws_profile == "test-profile"
            assert cfg.bedrock_model_id == "amazon.nova-lite-v1:0"
            assert cfg.max_tool_loops == 7
            assert cfg.temperature == 0.3
            assert cfg.max_tokens == 1000

    def test_from_env_invalid_numeric_fallback(self):
        env_vars = {
            "MAX_TOOL_LOOPS": "not-a-number",
            "TEMPERATURE": "invalid-float",
            "MAX_TOKENS": "bad-tokens",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            cfg = Config.from_env()
            assert cfg.max_tool_loops == DEFAULT_MAX_TOOL_LOOPS
            assert cfg.temperature == DEFAULT_TEMPERATURE
            assert cfg.max_tokens == DEFAULT_MAX_TOKENS


class TestBoto3SessionCreation:
    """Verify boto3 session factory logic."""

    @patch("boto3.Session")
    def test_get_boto3_session(self, mock_session_cls):
        cfg = Config(aws_region="us-west-2", aws_profile="my-profile")
        get_boto3_session(cfg)
        mock_session_cls.assert_called_once_with(
            profile_name="my-profile",
            region_name="us-west-2",
        )


class TestValidationLogic:
    """Verify AWS and Bedrock connectivity validation."""

    @patch("config.get_boto3_session")
    def test_validate_success(self, mock_get_session):
        mock_session = MagicMock()
        mock_creds = MagicMock()
        mock_session.get_credentials.return_value = mock_creds

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:iam::123456789012:user/devops-trainee"
        }
        mock_bedrock = MagicMock()
        # Mock converse attribute
        mock_bedrock.converse = MagicMock()

        def client_side_effect(service, **kwargs):
            if service == "sts":
                return mock_sts
            if service == "bedrock-runtime":
                return mock_bedrock
            return MagicMock()

        mock_session.client.side_effect = client_side_effect
        mock_get_session.return_value = mock_session

        cfg = Config()
        result = validate_aws_and_bedrock(cfg)

        assert result["ok"] is True
        assert result["authenticated"] is True
        assert result["bedrock_available"] is True
        assert result["identity_arn"] == "arn:aws:iam::123456789012:user/devops-trainee"

    @patch("config.get_boto3_session")
    def test_validate_no_credentials(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.get_credentials.return_value = None
        mock_get_session.return_value = mock_session

        cfg = Config()
        result = validate_aws_and_bedrock(cfg)

        assert result["ok"] is False
        assert result["authenticated"] is False
        assert result["error_type"] == "NoCredentialsError"
        assert "No AWS credentials found" in result["error_message"]

    @patch("config.get_boto3_session")
    def test_validate_profile_not_found(self, mock_get_session):
        mock_get_session.side_effect = ProfileNotFound(profile="missing-prof")

        cfg = Config(aws_profile="missing-prof")
        result = validate_aws_and_bedrock(cfg)

        assert result["ok"] is False
        assert result["error_type"] == "ProfileNotFound"

    @patch("config.get_boto3_session")
    def test_validate_client_error(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.get_credentials.return_value = MagicMock()
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied by policy"}},
            "GetCallerIdentity",
        )
        mock_session.client.return_value = mock_sts
        mock_get_session.return_value = mock_session

        cfg = Config()
        result = validate_aws_and_bedrock(cfg)

        assert result["ok"] is False
        assert result["error_type"] == "AccessDenied"
        assert "Access Denied by policy" in result["error_message"]

    def test_security_never_leaks_keys(self):
        """Ensure no config structures leak secrets in repr or dict format."""
        cfg = Config()
        cfg_str = str(cfg)
        assert "secret" not in cfg_str.lower()
        assert "password" not in cfg_str.lower()
