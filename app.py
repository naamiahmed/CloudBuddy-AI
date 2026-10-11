"""CloudBuddy AI — Streamlit Frontend Application.

A beginner-friendly AWS DevOps Troubleshooting Assistant providing structured,
advisory-only diagnostic guidance for cloud, container, and infrastructure issues.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import streamlit as st

from agent import CloudBuddyAgent
from config import RECOMMENDED_MODELS, Config, validate_aws_and_bedrock
from tools import TOOL_DEFINITIONS

# Page configuration
st.set_page_config(
    page_title="CloudBuddy AI — AWS DevOps Troubleshooting Agent",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Dark Theme CSS with subtle blue accents
CUSTOM_CSS = """
<style>
/* Main app dark styling */
.stApp {
    background-color: #0b0f17;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
}

/* Sidebar styling */
[data-testid="stSidebar"] {
    background-color: #111827;
    border-right: 1px solid #1f2937;
}

/* Header & Accent elements */
h1, h2, h3, h4 {
    color: #f8fafc;
    font-weight: 600;
}

.stChatMessage {
    background-color: #161e2e;
    border: 1px solid #1e293b;
    border-radius: 8px;
    margin-bottom: 12px;
}

/* Badges and tags */
.badge-advisory {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    background-color: #1e3a5f;
    color: #38bdf8;
    border: 1px solid #0284c7;
    margin-bottom: 8px;
}

.badge-connected {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
    background-color: #064e3b;
    color: #34d399;
}

.badge-warning {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
    background-color: #451a03;
    color: #fbbf24;
}

/* Example prompts card */
.prompt-card {
    background-color: #131d2e;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 10px;
    cursor: pointer;
    transition: border-color 0.15s ease-in-out;
}
.prompt-card:hover {
    border-color: #38bdf8;
}

/* Code blocks */
code {
    color: #38bdf8 !important;
}

pre {
    background-color: #080d16 !important;
    border: 1px solid #1e293b !important;
    border-radius: 6px !important;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def init_session_state():
    """Initialize Streamlit session state variables."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "config" not in st.session_state:
        st.session_state.config = Config.from_env()
    if "agent" not in st.session_state:
        st.session_state.agent = CloudBuddyAgent(config=st.session_state.config)
    if "connection_status" not in st.session_state:
        st.session_state.connection_status = None


def render_sidebar():
    """Render the application sidebar with settings, diagnostics, and status."""
    with st.sidebar:
        st.markdown(
            "## ☁️ CloudBuddy AI\n"
            "<span class='badge-advisory'>🛡️ ADVISORY ONLY</span>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Your intelligent AWS DevOps troubleshooting partner for diagnosing "
            "cloud, container, and infrastructure incidents."
        )

        st.markdown("---")

        # Action: New Chat
        if st.button("🔄 New Chat", use_container_width=True, type="secondary"):
            st.session_state.messages = []
            st.rerun()

        st.markdown("---")

        # Configuration Section
        st.markdown("### ⚙️ AWS & Bedrock Config")

        current_cfg: Config = st.session_state.config

        region_options = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1", "custom"]
        current_region_idx = (
            region_options.index(current_cfg.aws_region)
            if current_cfg.aws_region in region_options
            else 0
        )
        selected_region = st.selectbox(
            "AWS Region",
            region_options,
            index=current_region_idx,
            help="AWS Region hosting Amazon Bedrock runtime.",
        )
        if selected_region == "custom":
            custom_reg = st.text_input("Custom Region", value=current_cfg.aws_region)
            region_to_use = custom_reg.strip()
        else:
            region_to_use = selected_region

        profile_input = st.text_input(
            "AWS Profile (Optional)",
            value=current_cfg.aws_profile or "",
            placeholder="default / production",
            help="Named AWS CLI profile. Leave blank for default credential chain.",
        )

        selected_model = st.selectbox(
            "Bedrock Model ID",
            RECOMMENDED_MODELS,
            index=0,
            help="Select Amazon Bedrock foundation model.",
        )

        # Update config if modified
        profile_val = profile_input.strip() if profile_input.strip() else None
        if (
            region_to_use != current_cfg.aws_region
            or profile_val != current_cfg.aws_profile
            or selected_model != current_cfg.bedrock_model_id
        ):
            new_cfg = Config(
                aws_region=region_to_use,
                aws_profile=profile_val,
                bedrock_model_id=selected_model,
                max_tool_loops=current_cfg.max_tool_loops,
                temperature=current_cfg.temperature,
                max_tokens=current_cfg.max_tokens,
            )
            st.session_state.config = new_cfg
            st.session_state.agent = CloudBuddyAgent(config=new_cfg)
            st.session_state.connection_status = None

        # Test Connectivity Button
        if st.button("🔍 Check AWS & Bedrock", use_container_width=True):
            with st.spinner("Validating AWS credentials and Bedrock runtime..."):
                status = validate_aws_and_bedrock(st.session_state.config)
                st.session_state.connection_status = status

        # Display Connectivity Status
        if st.session_state.connection_status:
            status = st.session_state.connection_state = st.session_state.connection_status
            if status.get("authenticated") and status.get("bedrock_available"):
                st.markdown(
                    "<span class='badge-connected'>● AWS Credentials Active</span>",
                    unsafe_allow_html=True,
                )
                if status.get("identity_arn"):
                    st.caption(f"**Identity:** `{status['identity_arn']}`")
            elif status.get("authenticated"):
                st.markdown(
                    "<span class='badge-warning'>● AWS OK / Bedrock Pending</span>",
                    unsafe_allow_html=True,
                )
                if status.get("error_message"):
                    st.caption(f"_{status['error_message']}_")
            else:
                st.markdown(
                    "<span class='badge-warning'>● AWS Not Connected</span>",
                    unsafe_allow_html=True,
                )
                if status.get("error_message"):
                    st.caption(f"_{status['error_message']}_")

        st.markdown("---")

        # Diagnostic Categories List
        st.markdown("### 🧰 Available Runbooks")
        tool_names = [t["toolSpec"]["name"] for t in TOOL_DEFINITIONS]
        for name in tool_names:
            clean_name = name.replace("get_", "").replace("_steps", "").replace("_", " ").title()
            st.markdown(f"• `{clean_name}`")

        st.markdown("---")

        # Advisory Mode Notice
        st.markdown(
            "#### 🛡️ Advisory Mode Notice\n"
            "CloudBuddy is **read-only and advisory-only**. It will **never** alter your AWS infrastructure, "
            "delete resources, or execute shell commands on your machine.\n\n"
            "**Important:** Always review recommendations and test commands in a safe environment "
            "before modifying production systems."
        )


def render_welcome_screen():
    """Render the welcome view with onboarding information and example prompt triggers."""
    st.markdown(
        """
        # 👋 Welcome to CloudBuddy AI
        ### Your beginner-friendly AWS & DevOps Troubleshooting Partner
        
        Got a broken cloud service, mystery HTTP error, or failing container? CloudBuddy analyzes the symptoms,
        walks you through step-by-step diagnostic checks, explains **why** each step matters, and provides
        safe read-only commands to run.
        """
    )

    st.info(
        "💡 **Advisory Mode Active**: CloudBuddy gives you verified diagnostic guidance without touching "
        "or modifying your AWS resources.",
        icon="🛡️",
    )

    st.markdown("### 🚀 Try an example scenario:")

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "🌐 EC2 is running, but website on Port 80 won't open",
            use_container_width=True,
            key="ex1",
        ):
            submit_message(
                "My EC2 instance is in 'running' state, but when I try to open the website in my browser, "
                "it times out and won't connect. How do I troubleshoot this?"
            )

        if st.button(
            "🔒 S3 PutObject returning 403 AccessDenied",
            use_container_width=True,
            key="ex2",
        ):
            submit_message(
                "My application running on EC2 is getting 'AccessDenied' HTTP 403 when trying to upload "
                "a file to an S3 bucket with PutObject. How do I fix the IAM or bucket policy?"
            )

        if st.button(
            "🛑 Unsafe request test (Delete all EC2 instances)",
            use_container_width=True,
            key="ex3",
        ):
            submit_message("Please delete all my EC2 instances and open security group to 0.0.0.0/0.")

    with col2:
        if st.button(
            "💥 Nginx returning HTTP 502 Bad Gateway",
            use_container_width=True,
            key="ex4",
        ):
            submit_message(
                "Users are seeing '502 Bad Gateway' on our Nginx web server reverse-proxying to a backend app. "
                "What are the steps to diagnose and resolve this?"
            )

        if st.button(
            "🔄 Kubernetes Pod stuck in CrashLoopBackOff",
            use_container_width=True,
            key="ex5",
        ):
            submit_message(
                "My Kubernetes deployment has pods stuck in CrashLoopBackOff status. "
                "How do I find out what is causing the container to crash?"
            )

        if st.button(
            "❓ Incomplete problem description ('Website is broken')",
            use_container_width=True,
            key="ex6",
        ):
            submit_message("My website is broken. Help!")


def submit_message(prompt_text: str):
    """Submit a user prompt to the agent and trigger an app rerun."""
    st.session_state.messages.append({"role": "user", "content": prompt_text})
    st.rerun()


def main():
    """Main application loop."""
    init_session_state()
    render_sidebar()

    # If no messages yet, show welcome screen
    if not st.session_state.messages:
        render_welcome_screen()

    # Render conversation history
    for msg in st.session_state.messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])
        fallback_mode = msg.get("fallback_mode", False)

        with st.chat_message(role):
            if role == "assistant" and tool_calls:
                with st.expander(
                    f"🛠️ Diagnostic Tools Consulted ({len(tool_calls)})",
                    expanded=False,
                ):
                    for tc in tool_calls:
                        st.markdown(f"**Tool:** `{tc.get('tool')}`")
                        if tc.get("input"):
                            st.json(tc.get("input"))
            st.markdown(content)

    # If the last message is from the user, generate the assistant's reply
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        user_query = st.session_state.messages[-1]["content"]

        with st.chat_message("assistant"):
            with st.spinner("Investigating symptoms and consulting diagnostic runbooks..."):
                # Call CloudBuddyAgent
                agent_resp = st.session_state.agent.chat(
                    user_message=user_query,
                    conversation_history=st.session_state.messages[:-1],
                )

                # Show tool calls if any
                if agent_resp.tool_calls:
                    with st.expander(
                        f"🛠️ Diagnostic Tools Consulted ({len(agent_resp.tool_calls)})",
                        expanded=False,
                    ):
                        for tc in agent_resp.tool_calls:
                            st.markdown(f"**Tool:** `{tc.get('tool')}`")
                            if tc.get("input"):
                                st.json(tc.get("input"))

                st.markdown(agent_resp.content)

                # Store assistant response in session state
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": agent_resp.content,
                    "tool_calls": agent_resp.tool_calls,
                    "fallback_mode": agent_resp.fallback_mode,
                })

    # Chat input box
    user_input = st.chat_input(
        placeholder="Describe an infrastructure issue (e.g. 'EC2 website times out', '502 Bad Gateway', 'S3 AccessDenied')..."
    )

    if user_input:
        submit_message(user_input)


if __name__ == "__main__":
    main()
