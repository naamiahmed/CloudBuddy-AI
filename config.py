"""Configuration manager for CloudBuddy AI.

Handles AWS configuration, Bedrock model selection, and credentials
resolution following standard AWS SDK provider chain without ever storing
or exposing sensitive credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
    ProfileNotFound,
)
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

# Common supported Bedrock model IDs
RECOMMENDED_MODELS = [
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-pro-v1:0",
    "amazon.titan-text-express-v1",
]

DEFAULT_MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
DEFAULT_REGION = "us-east-1"
DEFAULT_MAX_TOOL_LOOPS = 5
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 2048


@dataclass
class Config:
    """Runtime configuration for CloudBuddy AI."""

    aws_region: str = DEFAULT_REGION
    aws_profile: Optional[str] = None
    bedrock_model_id: str = DEFAULT_MODEL_ID
    max_tool_loops: int = DEFAULT_MAX_TOOL_LOOPS
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls) -> Config:
        """Create configuration loaded from environment variables."""
        # Check AWS region from standard AWS env vars or default
        region = (
            os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or os.getenv("CLOUDBUDDY_AWS_REGION")
        )

        profile = os.getenv("AWS_PROFILE") or os.getenv("CLOUDBUDDY_AWS_PROFILE")
        if profile and profile.strip() == "":
            profile = None

        model_id = (
            os.getenv("BEDROCK_MODEL_ID")
            or os.getenv("CLOUDBUDDY_BEDROCK_MODEL_ID")
            or DEFAULT_MODEL_ID
        )

        try:
            max_loops = int(os.getenv("MAX_TOOL_LOOPS", str(DEFAULT_MAX_TOOL_LOOPS)))
        except ValueError:
            max_loops = DEFAULT_MAX_TOOL_LOOPS

        try:
            temp = float(os.getenv("TEMPERATURE", str(DEFAULT_TEMPERATURE)))
        except ValueError:
            temp = DEFAULT_TEMPERATURE

        try:
            tokens = int(os.getenv("MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
        except ValueError:
            tokens = DEFAULT_MAX_TOKENS

        # If region not set in env, inspect current default session region
        if not region:
            try:
                session = boto3.Session(profile_name=profile)
                region = session.region_name or DEFAULT_REGION
            except Exception:
                region = DEFAULT_REGION

        return cls(
            aws_region=region,
            aws_profile=profile,
            bedrock_model_id=model_id,
            max_tool_loops=max_loops,
            temperature=temp,
            max_tokens=tokens,
        )


def get_boto3_session(config: Config) -> boto3.Session:
    """Create a boto3 Session respecting configured profile and region."""
    kwargs: Dict[str, Any] = {}
    if config.aws_profile:
        kwargs["profile_name"] = config.aws_profile
    if config.aws_region:
        kwargs["region_name"] = config.aws_region
    return boto3.Session(**kwargs)


def validate_aws_and_bedrock(config: Config) -> Dict[str, Any]:
    """Validate AWS credentials and Bedrock runtime connectivity.

    Never exposes secret keys or credentials in output.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "authenticated": False,
        "region": config.aws_region,
        "model_id": config.bedrock_model_id,
        "identity_arn": None,
        "error_type": None,
        "error_message": None,
        "bedrock_available": False,
        "advisory_mode": True,
    }

    try:
        session = get_boto3_session(config)
        credentials = session.get_credentials()

        if credentials is None:
            result["error_type"] = "NoCredentialsError"
            result["error_message"] = (
                "No AWS credentials found. Please configure credentials via "
                "'aws configure', environment variables (AWS_ACCESS_KEY_ID), "
                "or an IAM instance profile."
            )
            return result

        result["authenticated"] = True

        # Check caller identity via STS to verify valid credentials
        sts_client = session.client("sts")
        identity = sts_client.get_caller_identity()
        result["identity_arn"] = identity.get("Arn")

        # Check Bedrock runtime client creation
        bedrock_runtime = session.client("bedrock-runtime", region_name=config.aws_region)
        if hasattr(bedrock_runtime, "converse"):
            result["bedrock_available"] = True
            result["ok"] = True
            result["error_message"] = None
        else:
            result["error_type"] = "UnsupportedBoto3Version"
            result["error_message"] = (
                "The installed Boto3 version does not support Bedrock Converse API. "
                "Please update boto3."
            )

    except ProfileNotFound as e:
        result["error_type"] = "ProfileNotFound"
        result["error_message"] = f"AWS profile '{config.aws_profile}' was not found: {e}"
    except (NoCredentialsError, PartialCredentialsError) as e:
        result["error_type"] = "CredentialsError"
        result["error_message"] = f"Incomplete or missing AWS credentials: {e}"
    except ClientError as e:
        err_code = e.response.get("Error", {}).get("Code", "ClientError")
        err_msg = e.response.get("Error", {}).get("Message", str(e))
        result["error_type"] = err_code
        result["error_message"] = f"AWS ClientError [{err_code}]: {err_msg}"
    except Exception as e:
        result["error_type"] = type(e).__name__
        result["error_message"] = f"Unexpected validation error: {str(e)}"

    return result
