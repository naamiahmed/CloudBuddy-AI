"""Safe, deterministic diagnostic tools for CloudBuddy AI.

Provides structured, curated troubleshooting guidance for common cloud,
container, and DevOps infrastructure issues. All tools are read-only and
advisory-only; they do NOT perform modifications to live infrastructure.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def get_ec2_troubleshooting_steps(
    issue_type: str = "web_unreachable",
    os_type: str = "linux",
) -> Dict[str, Any]:
    """Provide step-by-step troubleshooting instructions for EC2 instances.

    Args:
        issue_type: The issue category, e.g. 'web_unreachable', 'ssh_failure',
                    'high_cpu', 'status_check_failed'.
        os_type: Target operating system ('linux' or 'windows').
    """
    normalized_issue = issue_type.lower().strip()
    is_linux = "win" not in os_type.lower()

    if "ssh" in normalized_issue:
        return {
            "category": "EC2 Connectivity (SSH)",
            "problem_summary": "Unable to connect to EC2 instance via SSH (Port 22).",
            "likely_causes": [
                "Security group inbound rules do not allow Port 22 from your current client public IP.",
                "EC2 instance is in a private subnet without a Bastion host, VPN, or SSM Session Manager.",
                "Incorrect SSH key pair used (.pem file mismatch) or wrong username (e.g. ubuntu vs ec2-user).",
                "Strict file permissions on private key file (.pem file permissions too open).",
                "Instance OS firewall (UFW/iptables) or sshd service stopped.",
            ],
            "step_by_step_checks": [
                {
                    "step": 1,
                    "title": "Check Security Group Inbound Rules",
                    "what_to_check": "In AWS Console > EC2 > Security Groups, ensure inbound rule allows Port 22 (SSH) from your IP.",
                    "why_it_matters": "AWS Security Groups act as a stateful firewall. Without an inbound rule, traffic is dropped silently at the virtual NIC.",
                    "command_or_console": "AWS Console: EC2 > Instances > [Your Instance] > Security tab > Inbound rules.\nCLI: aws ec2 describe-security-groups --group-ids <sg-id> --query 'SecurityGroups[*].IpPermissions'",
                    "expected_result": "A rule with IP Protocol 'tcp', Port 22, and your current IP in CIDR format (e.g. 203.0.113.4/32).",
                    "next_step": "If missing or 0.0.0.0/0 is blocked by corporate firewall, add your specific public IP (/32).",
                },
                {
                    "step": 2,
                    "title": "Verify Key File Permissions & Default Username",
                    "what_to_check": "Ensure key file has permissions 400 (read-only by owner) and correct default user is used.",
                    "why_it_matters": "SSH clients reject keys that are accessible to other users on your local system.",
                    "command_or_console": "Linux/macOS: chmod 400 my-key.pem\nConnect command: ssh -i my-key.pem <username>@<public-ip>\n(Usernames: Ubuntu='ubuntu', Amazon Linux='ec2-user', Debian='admin', RHEL='ec2-user')",
                    "expected_result": "SSH client attempts handshake without 'Permissions 0644 for ... are too open' error.",
                    "next_step": "If permission denied persists, verify you selected the correct key pair when creating the instance.",
                },
                {
                    "step": 3,
                    "title": "Try AWS Systems Manager (SSM) Session Manager",
                    "what_to_check": "Attempt connection using AWS SSM Session Manager instead of direct SSH.",
                    "why_it_matters": "SSM connects via the SSM Agent inside the instance through AWS APIs, bypassing Port 22, public IPs, and security groups.",
                    "command_or_console": "AWS Console: EC2 > Instances > Select instance > Connect > Session Manager tab > Connect.\nCLI: aws ssm start-session --target <instance-id>",
                    "expected_result": "Interactive browser shell opens if IAM role has 'AmazonSSMManagedInstanceCore' attached and agent is running.",
                    "next_step": "If successful, you can troubleshoot OS-level sshd service (`systemctl status sshd`) directly from the SSM shell.",
                },
            ],
            "safety_considerations": (
                "Never open Port 22 to 0.0.0.0/0 (the entire internet). Restrict access to your IP (/32) "
                "or use AWS SSM Session Manager for secure, keyless access with audit logging."
            ),
        }

    # Default: web_unreachable / HTTP traffic
    return {
        "category": "EC2 Web Connectivity (HTTP/HTTPS)",
        "problem_summary": "EC2 instance is running, but web applications on Port 80 / 443 are unreachable from the browser.",
        "likely_causes": [
            "Security Group inbound rules are missing Port 80 (HTTP) or Port 443 (HTTPS).",
            "Subnet Route Table does not have a route to an Internet Gateway (0.0.0.0/0 -> igw-xxxx).",
            "Instance does not have a Public IPv4 address or Elastic IP attached.",
            "Network Access Control List (NACL) is blocking inbound traffic or outbound ephemeral return traffic (ports 1024-65535).",
            "Web server process (Nginx/Apache/custom daemon) is stopped, failed, or not listening on 0.0.0.0.",
            "Local OS firewall (UFW on Ubuntu, iptables, or firewalld) is blocking inbound HTTP ports.",
        ],
        "step_by_step_checks": [
            {
                "step": 1,
                "title": "Verify Instance State and 2/2 Status Checks",
                "what_to_check": "In AWS Console > EC2 > Instances, check if state is 'Running' and 'Status check' is '2/2 checks passed'.",
                "why_it_matters": "If System Check or Instance Check failed, the underlying AWS host or OS kernel has a problem before network packets can arrive.",
                "command_or_console": "AWS Console: EC2 > Instances > View status check column.\nCLI: aws ec2 describe-instance-status --instance-ids <instance-id>",
                "expected_result": "InstanceState: 'running', SystemStatus: 'ok', InstanceStatus: 'ok'.",
                "next_step": "If status check failed, inspect EC2 System Log (Actions > Monitor and troubleshoot > Get system log) or reboot instance.",
            },
            {
                "step": 2,
                "title": "Check Security Group Inbound Rules",
                "what_to_check": "Check the security group attached to the instance for inbound Port 80 (HTTP) and Port 443 (HTTPS).",
                "why_it_matters": "Security groups are default-deny. Without explicit Port 80/443 inbound rules, all browser requests are dropped at the hypervisor level.",
                "command_or_console": "AWS Console: EC2 > Instances > Select instance > Security tab > Inbound rules.\nCLI: aws ec2 describe-security-groups --group-ids <sg-id>",
                "expected_result": "Inbound rule: Type HTTP (Port 80) Source 0.0.0.0/0 (or your client IP) and HTTPS (Port 443).",
                "next_step": "If rules are missing, add inbound HTTP/HTTPS rules in the Security Group console.",
            },
            {
                "step": 3,
                "title": "Verify Public IP & Subnet Route Table (Internet Gateway)",
                "what_to_check": "Confirm the instance has a Public IPv4 / Elastic IP and its subnet route table points to an Internet Gateway (IGW).",
                "why_it_matters": "An instance in a private subnet without an IGW route cannot receive traffic directly from the internet, even with public security group rules.",
                "command_or_console": "AWS Console: VPC > Route tables > Select subnet route table > Routes tab.\nCLI: aws ec2 describe-route-tables --route-table-ids <rtb-id>",
                "expected_result": "Destination: 0.0.0.0/0, Target: igw-xxxxxxxx (Active). Instance has an allocated Public IPv4.",
                "next_step": "If route table lacks an IGW route, this is a private subnet. Place an Application Load Balancer in public subnets to route to it.",
            },
            {
                "step": 4,
                "title": "Inspect Inbound & Outbound Subnet Network ACLs (NACLs)",
                "what_to_check": "Check VPC > Network ACLs for the subnet. Verify inbound rules allow 80/443 and outbound allows ephemeral ports (1024-65535).",
                "why_it_matters": "Unlike Security Groups, NACLs are stateless. Return traffic must be explicitly allowed on outbound ephemeral ports (1024-65535).",
                "command_or_console": "AWS Console: VPC > Network ACLs > Check subnet association.\nCLI: aws ec2 describe-network-acls --filters Name=association.subnet-id,Values=<subnet-id>",
                "expected_result": "Inbound Rule ALLOW 80/443; Outbound Rule ALLOW ephemeral ports (1024-65535) or all traffic to 0.0.0.0/0.",
                "next_step": "Ensure rule number is lower than any DENY rule (NACLs evaluate rules in numerical order).",
            },
            {
                "step": 5,
                "title": "Verify Web Server Process Inside the Instance",
                "what_to_check": "Log into the instance via SSH or SSM and check if Nginx/Apache is running.",
                "why_it_matters": "Even if all AWS network layers are open, if the service process crashed or never started, connections will be refused.",
                "command_or_console": "Linux: sudo systemctl status nginx  # or: sudo systemctl status httpd\nWindows: Get-Service W3SVC",
                "expected_result": "Active: active (running).",
                "next_step": "If inactive or failed, run `sudo journalctl -u nginx -e --no-pager` or `sudo nginx -t` to inspect configuration errors.",
            },
            {
                "step": 6,
                "title": "Check Socket Listening Address and Port Binding",
                "what_to_check": "Ensure web server is listening on 0.0.0.0:80 (all interfaces), NOT 127.0.0.1:80 (localhost only).",
                "why_it_matters": "If bound to 127.0.0.1, the web server only accepts connections originating from inside the instance itself.",
                "command_or_console": "Linux: sudo ss -tulpn | grep -E ':80|:443'\nWindows: netstat -ano | findstr :80",
                "expected_result": "tcp LISTEN 0.0.0.0:80 or :::80.",
                "next_step": "If bound to 127.0.0.1:80, update web server config file (e.g. /etc/nginx/sites-available/default) to `listen 80;`.",
            },
            {
                "step": 7,
                "title": "Check Local OS Firewall (UFW / iptables)",
                "what_to_check": "Verify operating system firewall is not dropping incoming web traffic.",
                "why_it_matters": "OS-level firewalls run independently of AWS Security Groups.",
                "command_or_console": "Linux (Ubuntu): sudo ufw status verbose\nLinux (RHEL/CentOS): sudo firewall-cmd --list-all",
                "expected_result": "Status: inactive OR 80/tcp ALLOW in rules list.",
                "next_step": "If active without port 80/443, run `sudo ufw allow 80/tcp && sudo ufw allow 443/tcp`.",
            },
        ],
        "safety_considerations": (
            "Do not disable security groups or OS firewalls globally in production. Always make targeted "
            "allow rules for required ports. Back up web server configuration files before editing."
        ),
    }


def get_http_troubleshooting_steps(
    error_code: int = 502,
    web_server: str = "nginx",
) -> Dict[str, Any]:
    """Provide step-by-step diagnostic instructions for HTTP error codes.

    Args:
        error_code: HTTP response status code (e.g. 502, 504, 500, 403).
        web_server: Web server software ('nginx', 'apache', 'alb').
    """
    code = int(error_code)
    server = web_server.lower().strip()

    if code == 502:
        return {
            "category": "HTTP 502 Bad Gateway",
            "problem_summary": "The reverse proxy (e.g. Nginx, ALB) received an invalid response or connection reset from the upstream application server.",
            "likely_causes": [
                "Upstream application process (Node.js, Gunicorn, Python, PHP-FPM, Java) is crashed, stopped, or restarting.",
                "Nginx reverse proxy is pointing to the wrong upstream port or host (e.g. proxy_pass http://127.0.0.1:3000 vs 8080).",
                "Upstream Unix domain socket has incorrect permissions or does not exist (e.g. /var/run/app.sock).",
                "Upstream server terminated the TCP connection prematurely due to memory limit (OOM) or unhandled crash.",
                "ALB target group health check failed and deregistered all backend targets.",
            ],
            "step_by_step_checks": [
                {
                    "step": 1,
                    "title": "Check Web Server Error Logs",
                    "what_to_check": "Examine the latest error log entries in Nginx or Apache for the exact upstream error.",
                    "why_it_matters": "The web server error log specifies the exact reason (e.g. 'Connection refused', 'connect() to unix:/... failed', 'upstream prematurely closed connection').",
                    "command_or_console": "Nginx: sudo tail -n 50 /var/log/nginx/error.log\nApache: sudo tail -n 50 /var/log/apache2/error.log",
                    "expected_result": "Reveals the upstream IP/port/socket and exact failure mode.",
                    "next_step": "If 'Connection refused', verify backend application is running. If 'Permission denied', check socket file ownership.",
                },
                {
                    "step": 2,
                    "title": "Verify Backend Application Service Status",
                    "what_to_check": "Check whether the backend application service is active and running.",
                    "why_it_matters": "502 occurs when Nginx can receive requests, but the app server behind it is dead.",
                    "command_or_console": "Linux: sudo systemctl status <app-service-name> # e.g. gunicorn, php8.1-fpm, node-app\nOr: ps aux | grep -E 'python|node|gunicorn|puma'",
                    "expected_result": "Active: active (running) with recent uptime.",
                    "next_step": "If inactive or failed, restart service (`sudo systemctl restart <app>`) and inspect application logs.",
                },
                {
                    "step": 3,
                    "title": "Test Upstream Direct Connectivity Locally",
                    "what_to_check": "Bypass Nginx and send an HTTP request directly to the upstream application port using curl.",
                    "why_it_matters": "Confirms whether the upstream app itself responds properly or if the issue is in the reverse proxy configuration.",
                    "command_or_console": "curl -Iv http://127.0.0.1:<upstream-port>/ # e.g. curl -Iv http://127.0.0.1:3000/",
                    "expected_result": "HTTP/1.1 200 OK or expected application response.",
                    "next_step": "If curl gets 'Connection refused', the app is not bound to that port. Check application configuration.",
                },
                {
                    "step": 4,
                    "title": "Inspect ALB Target Group Health (If using AWS ALB)",
                    "what_to_check": "In AWS Console > EC2 > Target Groups, check target health state.",
                    "why_it_matters": "AWS Application Load Balancer returns 502 Bad Gateway if all targets fail health checks or if targets close connection with TCP RST.",
                    "command_or_console": "AWS Console: EC2 > Target Groups > Select group > Targets tab > Health status.\nCLI: aws elbv2 describe-target-health --target-group-arn <tg-arn>",
                    "expected_result": "Target Health State: 'healthy'.",
                    "next_step": "If 'unhealthy', review the configured health check path (e.g. /health) and ensure backend responds with HTTP 200.",
                },
            ],
            "safety_considerations": (
                "Do not restart production services during peak traffic without verifying fallback "
                "or draining connections. Always examine logs before restarting so error state is not lost."
            ),
        }

    if code == 504:
        return {
            "category": "HTTP 504 Gateway Timeout",
            "problem_summary": "The reverse proxy (Nginx, ALB, CloudFront) connected to the upstream server, but the upstream failed to respond within the configured timeout window.",
            "likely_causes": [
                "Slow database queries holding application worker threads.",
                "Application thread deadlock, infinite loop, or resource starvation.",
                "ALB idle timeout (default 60s) is shorter than application processing time for long requests.",
                "Third-party API call made by upstream is hung or timing out.",
                "Nginx `proxy_read_timeout` reached before backend produced HTTP response headers.",
            ],
            "step_by_step_checks": [
                {
                    "step": 1,
                    "title": "Check Upstream Processing Time & Timeouts",
                    "what_to_check": "Check Nginx `proxy_read_timeout` and compare with duration of failing requests.",
                    "why_it_matters": "If request takes 65s and proxy_read_timeout is 60s, Nginx sends 504 Gateway Timeout at exactly 60 seconds.",
                    "command_or_console": "Nginx: grep -rn 'proxy_read_timeout' /etc/nginx/\nALB: Check Idle Timeout attribute in Load Balancer details.",
                    "expected_result": "Proxy timeout should exceed maximum expected legitimate backend processing time.",
                    "next_step": "If timeout reached, determine if the backend is doing unnecessary heavy processing synchronously.",
                },
                {
                    "step": 2,
                    "title": "Inspect Backend CPU, Memory, and Database Locks",
                    "what_to_check": "Check CPU/memory usage and active database connections/slow query logs.",
                    "why_it_matters": "High CPU or database connection pool exhaustion stalls worker threads.",
                    "command_or_console": "Host: htop # or: top -b -n 1 | head -n 20\nDisk/Memory: free -m && df -h",
                    "expected_result": "Available memory and CPU load average within instance core count.",
                    "next_step": "If database is stalled, run `SHOW FULL PROCESSLIST;` (MySQL) or `pg_stat_activity` (PostgreSQL).",
                },
            ],
            "safety_considerations": (
                "Increasing timeouts is often a temporary band-aid. Offload long-running tasks (>10s) "
                "to background worker queues (e.g. AWS SQS + Celery/Lambda) rather than holding HTTP connections."
            ),
        }

    # Generic HTTP / 500 / 403
    return {
        "category": f"HTTP {code} Diagnostic",
        "problem_summary": f"HTTP status code {code} encountered on web server {server}.",
        "likely_causes": [
            "Internal server error / unhandled exception in backend application (HTTP 500).",
            "Missing environment variables or database connection failure (HTTP 500).",
            "Incorrect file system permissions on document root or missing index file (HTTP 403).",
            "Web Application Firewall (WAF) or security rule blocking request (HTTP 403).",
        ],
        "step_by_step_checks": [
            {
                "step": 1,
                "title": "Inspect Web Server and Application Error Logs",
                "what_to_check": "Check server error log for stack traces or permission errors.",
                "why_it_matters": "HTTP 500 or 403 errors always print explicit reason in local log files.",
                "command_or_console": "sudo tail -n 100 /var/log/nginx/error.log\njournalctl -xe --no-pager",
                "expected_result": "Locates stack trace or 'access forbidden by rule' notice.",
                "next_step": "Fix referenced code syntax error, missing environment variable, or file permission.",
            }
        ],
        "safety_considerations": "Do not expose detailed stack traces or debug modes in production responses.",
    }


def get_s3_access_denied_steps(
    operation: str = "GetObject",
    requester_type: str = "iam_role",
) -> Dict[str, Any]:
    """Provide step-by-step troubleshooting for S3 403 AccessDenied errors.

    Args:
        operation: The S3 API operation (e.g. 'GetObject', 'PutObject', 'ListBucket').
        requester_type: The caller identity ('iam_role', 'iam_user', 'anonymous').
    """
    op = operation.strip()
    return {
        "category": "AWS S3 AccessDenied (HTTP 403)",
        "problem_summary": f"Caller received 'AccessDenied' (HTTP 403) while performing s3:{op} on an S3 bucket or object.",
        "likely_causes": [
            "IAM Identity Policy is missing required action (s3:GetObject vs s3:ListBucket) or resource ARN.",
            "Resource ARN mismatch: 'arn:aws:s3:::my-bucket' (bucket level) vs 'arn:aws:s3:::my-bucket/*' (object level).",
            "S3 Bucket Policy contains an explicit 'Deny' that overrides allow permissions.",
            "Object is encrypted with AWS KMS (SSE-KMS), and caller lacks kms:Decrypt / kms:GenerateDataKey permission on the KMS key policy.",
            "S3 Block Public Access (BPA) is enabled at account or bucket level blocking public access.",
            "AWS Organizations Service Control Policy (SCP) is denying S3 actions in this account.",
            "Object ownership mismatch: Object was uploaded by another AWS account without 'bucket-owner-full-control'.",
            "VPC Endpoint Policy on s3 endpoint is restricting allowed actions or buckets.",
        ],
        "step_by_step_checks": [
            {
                "step": 1,
                "title": "Verify IAM Identity Policy Action and Resource ARN Format",
                "what_to_check": "Check whether the IAM policy has the exact action and correct ARN structure.",
                "why_it_matters": (
                    "Common mistake: Object operations (GetObject, PutObject) require 'arn:aws:s3:::bucket-name/*', "
                    "while bucket operations (ListBucket, GetBucketLocation) require 'arn:aws:s3:::bucket-name'."
                ),
                "command_or_console": "AWS Console: IAM > Roles/Users > [Select caller] > Permissions tab > View JSON.\nCLI: aws iam get-role-policy --role-name <name> --policy-name <pname>",
                "expected_result": (
                    "Policy has Statement allowing 's3:" + op + "' with Resource "
                    "['arn:aws:s3:::my-bucket', 'arn:aws:s3:::my-bucket/*']."
                ),
                "next_step": "If ARN is missing '/*', add both the bucket ARN and object wildcard ARN.",
            },
            {
                "step": 2,
                "title": "Inspect S3 Bucket Policy for Explicit Denies",
                "what_to_check": "In S3 Console > Buckets > [Bucket] > Permissions > Bucket policy, look for 'Effect': 'Deny'.",
                "why_it_matters": "In AWS IAM evaluation, an explicit Deny ALWAYS overrides any Allow, regardless of identity policy.",
                "command_or_console": "AWS Console: S3 > Buckets > [Name] > Permissions tab > Bucket Policy.\nCLI: aws s3api get-bucket-policy --bucket <bucket-name>",
                "expected_result": "No Deny condition matches caller's ARN, IP, or SSL condition.",
                "next_step": "Check Deny conditions such as `aws:SecureTransport`: `false` (requiring HTTPS) or IP restrictions.",
            },
            {
                "step": 3,
                "title": "Check AWS KMS Key Policy (If Bucket Uses SSE-KMS)",
                "what_to_check": "Determine default encryption on bucket. If using KMS (aws/s3 or custom CMK), check KMS key policy.",
                "why_it_matters": "Reading or writing SSE-KMS encrypted objects requires BOTH S3 permissions AND KMS permissions (kms:Decrypt / kms:GenerateDataKey).",
                "command_or_console": "AWS Console: S3 > Bucket > Properties > Default encryption.\nCLI: aws s3api get-bucket-encryption --bucket <bucket-name>",
                "expected_result": "If KMS is used, caller IAM role/user is in KMS Key Policy or has KMS action allowed in IAM policy.",
                "next_step": "If KMS access denied, grant `kms:Decrypt` (for download) or `kms:GenerateDataKey` (for upload) on key ARN.",
            },
            {
                "step": 4,
                "title": "Check Object Ownership and ACLs",
                "what_to_check": "In S3 Bucket > Permissions > Object Ownership, verify if 'Bucket owner enforced' is enabled.",
                "why_it_matters": "In multi-account setups, if another account uploads an object without granting bucket-owner-full-control, the bucket owner cannot access it.",
                "command_or_console": "AWS Console: S3 > Buckets > [Name] > Permissions > Object Ownership.",
                "expected_result": "'Bucket owner enforced' (recommended) or ACLs disabled.",
                "next_step": "Set Object Ownership to 'Bucket owner enforced' to automatically own all uploaded objects.",
            },
            {
                "step": 5,
                "title": "Check VPC Endpoint Policy (If Accessing from Private VPC)",
                "what_to_check": "If calling from an EC2/Lambda in a VPC with an S3 VPC Endpoint, check the endpoint policy.",
                "why_it_matters": "A restrictive VPC endpoint policy will block requests even if IAM and bucket policies allow it.",
                "command_or_console": "AWS Console: VPC > Endpoints > Select S3 Gateway Endpoint > Policy tab.\nCLI: aws ec2 describe-vpc-endpoints --endpoint-ids <vpce-id>",
                "expected_result": "Endpoint policy allows access to this bucket.",
                "next_step": "Add bucket ARN to VPC Endpoint allowed resources.",
            },
        ],
        "safety_considerations": (
            "Never disable 'Block Public Access' unless the bucket is intentionally hosting public assets. "
            "Never grant s3:* on all resources ('*') to troubleshoot. Follow least privilege."
        ),
    }


def get_iam_troubleshooting_steps(
    action: str = "*",
    resource_arn: str = "*",
) -> Dict[str, Any]:
    """Provide step-by-step diagnostic instructions for IAM permission issues.

    Args:
        action: The AWS action attempted (e.g. 'ec2:RunInstances', 's3:PutObject').
        resource_arn: The target resource ARN.
    """
    return {
        "category": "AWS IAM Permissions Diagnostic",
        "problem_summary": f"Permission denied when attempting action '{action}' on resource '{resource_arn}'.",
        "likely_causes": [
            "Action is missing from attached IAM managed or inline policies.",
            "Resource ARN in policy does not match the actual target resource ARN.",
            "Explicit Deny in an attached policy, SCP, or permission boundary.",
            "Permissions Boundary attached to the IAM user/role does not include the action.",
            "AWS Organizations Service Control Policy (SCP) at OU or account root is denying the action.",
            "Session policy passed during assume-role or STS federation is restricting access.",
        ],
        "step_by_step_checks": [
            {
                "step": 1,
                "title": "Decode Authorization Failure Message (If Encoded)",
                "what_to_check": "If AWS CLI or SDK returned an encoded authorization failure string, decode it with AWS STS.",
                "why_it_matters": "The encoded message gives the exact reason: which policy denied it (SCP, boundary, or identity policy).",
                "command_or_console": "aws sts decode-authorization-message --encoded-message <encoded-string> --query DecodedMessage --output text | jq .",
                "expected_result": "JSON output detailing principal, context, action, and explicit denial evaluation.",
                "next_step": "Inspect the 'matchedStatements' section to pinpoint the denying statement.",
            },
            {
                "step": 2,
                "title": "Understand the 6-Tier IAM Policy Evaluation Logic",
                "what_to_check": "Walk through AWS IAM evaluation order: 1) Explicit Deny -> 2) SCP -> 3) Resource Policy -> 4) Permissions Boundary -> 5) Session Policy -> 6) Identity Policy.",
                "why_it_matters": "An ALLOW in an identity policy is ignored if blocked by an SCP or boundary.",
                "command_or_console": "AWS Console: IAM > Policies > IAM Policy Simulator.\nCLI: aws iam simulate-principal-policy --policy-source-arn <principal-arn> --action-names " + action,
                "expected_result": "Simulation returns 'allowed' or pinpointed denial reason.",
                "next_step": "Check if an attached Permissions Boundary or Organization SCP is restricting the permission.",
            },
            {
                "step": 3,
                "title": "Check Permissions Boundary on User/Role",
                "what_to_check": "In IAM Console > Roles/Users > [Select] > Permissions boundary section.",
                "why_it_matters": "A permissions boundary sets the maximum allowed permissions. If an action is not in the boundary, it is denied.",
                "command_or_console": "AWS Console: IAM > Roles > [Role Name] > Permissions tab > Permissions boundary.\nCLI: aws iam get-role --role-name <name> --query 'Role.PermissionsBoundary'",
                "expected_result": "If present, boundary policy must include the requested action.",
                "next_step": "Update the boundary policy if authorized, or consult your AWS account administrator.",
            },
        ],
        "safety_considerations": (
            "Never attach AdministratorAccess or '*' wildcard actions to resolve a permission error. "
            "Use the principle of least privilege, granting only the specific action and resource needed."
        ),
    }


def get_docker_troubleshooting_steps(
    failure_type: str = "container_exit",
) -> Dict[str, Any]:
    """Provide step-by-step diagnostic instructions for Docker container failures.

    Args:
        failure_type: Type of failure, e.g. 'container_exit', 'port_conflict',
                      'oom_killed', 'healthcheck_failure'.
    """
    normalized = failure_type.lower().strip()
    return {
        "category": "Docker Container Failure Diagnostic",
        "problem_summary": f"Docker container failure: {failure_type}.",
        "likely_causes": [
            "Exit Code 137: Container killed by Linux Out-Of-Memory (OOM) killer or SIGKILL.",
            "Exit Code 1: Application threw an uncaught runtime exception or failed startup check.",
            "Exit Code 127: Entrypoint command or binary not found in container filesystem.",
            "Exit Code 126: Container command cannot be invoked (missing execution permission).",
            "Port conflict: Host port is already bound by another container or host daemon (e.g. 0.0.0.0:80).",
            "Missing environment variables or secret files causing immediate exit.",
        ],
        "step_by_step_checks": [
            {
                "step": 1,
                "title": "Inspect Container Exit Code and State",
                "what_to_check": "Run docker inspect to view State.ExitCode, State.OOMKilled, and State.Error.",
                "why_it_matters": "The exit code tells you whether it crashed naturally, was killed by OS memory constraints, or binary was missing.",
                "command_or_console": "docker inspect <container-id> --format 'Status: {{.State.Status}}, ExitCode: {{.State.ExitCode}}, OOMKilled: {{.State.OOMKilled}}, Error: {{.State.Error}}'",
                "expected_result": "Returns exact exit code and whether OOMKilled is true.",
                "next_step": "If OOMKilled is true (or ExitCode 137), increase container memory limit (`-m 2g`) or optimize application memory.",
            },
            {
                "step": 2,
                "title": "Inspect Container Stdout and Stderr Logs",
                "what_to_check": "View the last 100 log lines of the exited container.",
                "why_it_matters": "Containers print unhandled exceptions, missing config files, or DB connection failures to stderr.",
                "command_or_console": "docker logs --tail 100 <container-id>",
                "expected_result": "Reveals the application crash traceback or exit reason.",
                "next_step": "Address application configuration, database connection strings, or missing dependencies.",
            },
            {
                "step": 3,
                "title": "Check Port Binding Conflicts on Host",
                "what_to_check": "If error is 'bind: address already in use', find which process occupies the host port.",
                "why_it_matters": "Two containers or a host process cannot bind to the same host port on the same network interface.",
                "command_or_console": "Linux: sudo ss -tulpn | grep :<host-port>\nWindows: netstat -ano | findstr :<host-port>",
                "expected_result": "Finds PID of conflicting process.",
                "next_step": "Map container to an unused host port (`-p 8081:80`) or stop the conflicting service.",
            },
        ],
        "safety_considerations": (
            "Avoid running containers with `--privileged` in production unless required. "
            "Never store production API keys or passwords unencrypted in Dockerfile or image layers."
        ),
    }


def get_kubernetes_troubleshooting_steps(
    pod_status: str = "CrashLoopBackOff",
) -> Dict[str, Any]:
    """Provide step-by-step diagnostic instructions for Kubernetes pod issues.

    Args:
        pod_status: The pod condition or status, e.g. 'CrashLoopBackOff',
                    'ImagePullBackOff', 'Pending', 'OOMKilled'.
    """
    normalized = pod_status.strip()
    return {
        "category": f"Kubernetes Pod Troubleshooting ({normalized})",
        "problem_summary": f"Kubernetes Pod is in status '{normalized}'.",
        "likely_causes": [
            "CrashLoopBackOff: Container starts, crashes immediately, and kubelet enters exponential backoff retry.",
            "OOMKilled (Exit Code 137): Container exceeded its configured memory resource limit.",
            "Liveness Probe failure: Pod failed liveness probe and kubelet repeatedly restarts it.",
            "ImagePullBackOff: Invalid image name/tag, private registry authentication missing (imagePullSecret).",
            "Pending: Insufficient CPU/Memory on cluster nodes, node selector or taint mismatch, PVC unbound.",
            "ConfigMap/Secret missing: Pod references a non-existent ConfigMap or Secret in envFrom or volume.",
        ],
        "step_by_step_checks": [
            {
                "step": 1,
                "title": "Describe Pod Events and Termination Reason",
                "what_to_check": "Run kubectl describe pod to inspect the Events table and Last State.",
                "why_it_matters": "Events section records scheduling errors, probe failures, image pull failures, and last exit codes.",
                "command_or_console": "kubectl describe pod <pod-name> -n <namespace>",
                "expected_result": "Reveals Last State: Terminated (Reason: Error / OOMKilled, Exit Code) and recent Events.",
                "next_step": "If Reason is OOMKilled, raise `resources.limits.memory` in Pod spec. If probe failed, verify probe endpoint.",
            },
            {
                "step": 2,
                "title": "Retrieve Previous Container Logs (--previous)",
                "what_to_check": "Inspect logs of the CRASHED container instance rather than the newly restarted one.",
                "why_it_matters": "When a pod is in CrashLoopBackOff, `kubectl logs` might show nothing if the new container hasn't started yet.",
                "command_or_console": "kubectl logs <pod-name> -n <namespace> --previous",
                "expected_result": "Application stack trace or error message printed immediately prior to termination.",
                "next_step": "Fix application startup crash, missing environment variables, or database connection error.",
            },
            {
                "step": 3,
                "title": "Check Node Capacity and Resource Quotas (If Pending)",
                "what_to_check": "If Pod is Pending, check node resource pressure and cluster events.",
                "why_it_matters": "Scheduler cannot place pods if requested CPU/RAM exceeds allocatable capacity.",
                "command_or_console": "kubectl describe nodes | grep -A 5 'Allocated resources'\nkubectl get events -n <namespace> --sort-by='.metadata.creationTimestamp'",
                "expected_result": "Identifies '0/N nodes available: Insufficient memory/cpu'.",
                "next_step": "Add nodes or lower pod `resources.requests` values.",
            },
        ],
        "safety_considerations": (
            "Never delete running deployments or namespaces blindly. Before increasing memory limits, "
            "investigate potential application memory leaks."
        ),
    }


def get_cicd_troubleshooting_steps(
    failure_type: str = "workflow_failure",
) -> Dict[str, Any]:
    """Provide step-by-step diagnostic instructions for CI/CD and GitHub Actions failures.

    Args:
        failure_type: Failure category (e.g. 'aws_oidc_failure', 'workflow_failure',
                      'docker_build_failure').
    """
    return {
        "category": "CI/CD & GitHub Actions Troubleshooting",
        "problem_summary": f"CI/CD pipeline failed during: {failure_type}.",
        "likely_causes": [
            "AWS OIDC AssumeRole failure: Trust policy mismatch with repository name, branch ref, or audience (sts.amazonaws.com).",
            "Missing or mistyped repository secrets or environment variables (e.g. AWS_ROLE_ARN).",
            "Runner disk space exhausted during Docker image build or large dependencies.",
            "Architecture mismatch (building x86_64 image on arm64 runner or vice versa).",
            "GitHub Actions permission restriction: GITHUB_TOKEN lacks `id-token: write` permission for OIDC.",
        ],
        "step_by_step_checks": [
            {
                "step": 1,
                "title": "Verify GitHub Actions OIDC Permissions in Workflow YAML",
                "what_to_check": "Ensure workflow job has `permissions: id-token: write` and `contents: read`.",
                "why_it_matters": "Without `id-token: write`, GitHub will not issue the JWT token required to assume AWS IAM roles without long-lived access keys.",
                "command_or_console": "Check .github/workflows/*.yml:\npermissions:\n  id-token: write\n  contents: read",
                "expected_result": "Workflow file contains explicit id-token write permission.",
                "next_step": "Add permissions block under job or workflow root.",
            },
            {
                "step": 2,
                "title": "Check AWS IAM Role Trust Policy for GitHub OIDC",
                "what_to_check": "Verify IAM Role Trust Relationship has condition matching repository and branch.",
                "why_it_matters": "If branch is 'main' but condition expects 'refs/heads/master', AWS STS denies AssumeRoleWithWebIdentity.",
                "command_or_console": (
                    "In AWS IAM Role > Trust Relationships tab:\n"
                    "Condition StringEquals:\n"
                    "  token.actions.githubusercontent.com:aud: 'sts.amazonaws.com'\n"
                    "  token.actions.githubusercontent.com:sub: 'repo:<owner>/<repo>:ref:refs/heads/<branch>'"
                ),
                "expected_result": "Repository name and branch ref match exact casing and branch name.",
                "next_step": "Update trust relationship in AWS IAM console with exact GitHub repository path.",
            },
        ],
        "safety_considerations": (
            "Never use wildcard '*' for the sub condition in an IAM OIDC trust policy. "
            "A wildcard sub allows ANY GitHub user's workflow to assume your role."
        ),
    }


def explain_error(error_message: str) -> Dict[str, Any]:
    """Parse and explain common error messages in simple plain English.

    Args:
        error_message: The raw error message or log snippet.
    """
    clean_msg = error_message.strip()
    msg_lower = clean_msg.lower()

    explanation: Dict[str, Any] = {
        "raw_error": clean_msg,
        "identified_type": "Unknown / General Error",
        "plain_english_summary": "An unexpected error occurred during execution.",
        "why_it_happens": "Insufficient context to classify error automatically.",
        "recommended_tool": "None",
        "immediate_action": "Check application logs, verify recent configuration changes, and confirm service status.",
    }

    if "accessdenied" in msg_lower or "access denied" in msg_lower or "not authorized" in msg_lower:
        explanation.update({
            "identified_type": "AWS IAM / S3 Access Denied",
            "plain_english_summary": (
                "The AWS identity (user, role, or service) does not have permission "
                "to perform the requested operation on the target resource."
            ),
            "why_it_happens": (
                "AWS uses a default-deny security model. Access is denied if the IAM policy "
                "is missing the required action, specifies the wrong resource ARN, or an explicit "
                "Deny exists in a Bucket Policy, SCP, or Permissions Boundary."
            ),
            "recommended_tool": "get_s3_access_denied_steps or get_iam_troubleshooting_steps",
            "immediate_action": "Check the exact IAM action required, verify the resource ARN, and inspect bucket/KMS policies.",
        })
    elif "502" in msg_lower or "bad gateway" in msg_lower:
        explanation.update({
            "identified_type": "HTTP 502 Bad Gateway",
            "plain_english_summary": (
                "The web server or load balancer received an invalid response or unexpected "
                "connection closure from the backend application."
            ),
            "why_it_happens": (
                "The upstream application server (e.g. Node, Python/Gunicorn, PHP-FPM) is dead, "
                "crashed, listening on a different port, or terminated the connection prematurely."
            ),
            "recommended_tool": "get_http_troubleshooting_steps",
            "immediate_action": "Check web server error logs (/var/log/nginx/error.log) and verify backend service status.",
        })
    elif "504" in msg_lower or "gateway timeout" in msg_lower:
        explanation.update({
            "identified_type": "HTTP 504 Gateway Timeout",
            "plain_english_summary": (
                "The web server or load balancer reached its timeout limit while waiting "
                "for the backend application server to respond."
            ),
            "why_it_happens": (
                "The backend is taking too long to reply, often due to slow database queries, "
                "third-party API timeouts, or CPU/memory saturation."
            ),
            "recommended_tool": "get_http_troubleshooting_steps",
            "immediate_action": "Check backend application processing duration, database slow queries, and proxy timeout settings.",
        })
    elif "connection refused" in msg_lower or "econnrefused" in msg_lower:
        explanation.update({
            "identified_type": "Connection Refused (TCP RST)",
            "plain_english_summary": (
                "The operating system on the target host actively rejected the connection because "
                "no process is listening on the requested port."
            ),
            "why_it_happens": (
                "The target service is not running, is bound to 127.0.0.1 instead of 0.0.0.0, "
                "or the wrong port number was specified in the request."
            ),
            "recommended_tool": "get_ec2_troubleshooting_steps or get_http_troubleshooting_steps",
            "immediate_action": "Check if the daemon is running and verify listening ports using `ss -tulpn`.",
        })
    elif "crashloopbackoff" in msg_lower:
        explanation.update({
            "identified_type": "Kubernetes CrashLoopBackOff",
            "plain_english_summary": (
                "A Kubernetes pod is starting, crashing immediately, and the kubelet is waiting "
                "with an increasing delay before trying to restart it again."
            ),
            "why_it_happens": (
                "Application threw an unhandled exception at startup, failed a liveness probe, "
                "or was killed by the OS due to exceeding memory limits (OOM)."
            ),
            "recommended_tool": "get_kubernetes_troubleshooting_steps",
            "immediate_action": "Run `kubectl logs <pod-name> --previous` and `kubectl describe pod <pod-name>`.",
        })
    elif "137" in msg_lower or "oomkilled" in msg_lower or "out of memory" in msg_lower:
        explanation.update({
            "identified_type": "Out Of Memory (OOMKilled - Exit Code 137)",
            "plain_english_summary": (
                "The operating system or container runtime forcibly terminated the process "
                "because it exceeded its allocated memory limit."
            ),
            "why_it_happens": (
                "The application consumed more memory than available on the host or configured "
                "in Docker/Kubernetes container limits (`resources.limits.memory`)."
            ),
            "recommended_tool": "get_docker_troubleshooting_steps or get_kubernetes_troubleshooting_steps",
            "immediate_action": "Increase memory limits or profile the application for memory leaks.",
        })
    elif "host key verification failed" in msg_lower:
        explanation.update({
            "identified_type": "SSH Host Key Verification Failed",
            "plain_english_summary": (
                "The SSH client detected that the remote server's cryptographic fingerprint "
                "has changed compared to the entry stored in your known_hosts file."
            ),
            "why_it_happens": (
                "An EC2 instance was recreated with the same IP address, or the server was reinstalled. "
                "(In rare cases, this could indicate a man-in-the-middle attempt)."
            ),
            "recommended_tool": "get_ec2_troubleshooting_steps",
            "immediate_action": "Remove the old key entry using `ssh-keygen -R <ip-or-hostname>`.",
        })

    return explanation


# -------------------------------------------------------------------------
# Bedrock Converse Tool Definitions and Dispatcher
# -------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "toolSpec": {
            "name": "get_ec2_troubleshooting_steps",
            "description": "Get structured, step-by-step diagnostic instructions for EC2 instance connectivity, web access, and SSH failures.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "issue_type": {
                            "type": "string",
                            "description": "Category of issue, e.g. 'web_unreachable', 'ssh_failure', 'status_check_failed'.",
                        },
                        "os_type": {
                            "type": "string",
                            "description": "Operating system, e.g. 'linux' or 'windows'.",
                        },
                    },
                    "required": ["issue_type"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_http_troubleshooting_steps",
            "description": "Get step-by-step diagnostic instructions for HTTP error codes such as 502 Bad Gateway, 504 Gateway Timeout, 500, or 403.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "error_code": {
                            "type": "integer",
                            "description": "HTTP status code (e.g. 502, 504, 500, 403).",
                        },
                        "web_server": {
                            "type": "string",
                            "description": "Web server software, e.g. 'nginx', 'apache', or 'alb'.",
                        },
                    },
                    "required": ["error_code"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_s3_access_denied_steps",
            "description": "Get step-by-step diagnostic instructions for AWS S3 403 AccessDenied errors.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "description": "S3 operation attempted, e.g. 'GetObject', 'PutObject', 'ListBucket'.",
                        },
                        "requester_type": {
                            "type": "string",
                            "description": "Type of requester, e.g. 'iam_role', 'iam_user'.",
                        },
                    },
                    "required": ["operation"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_iam_troubleshooting_steps",
            "description": "Get step-by-step diagnostic instructions for AWS IAM permission errors and policy evaluation.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "The AWS action that failed, e.g. 'ec2:RunInstances', 's3:PutObject'.",
                        },
                        "resource_arn": {
                            "type": "string",
                            "description": "The target AWS resource ARN, if known.",
                        },
                    },
                    "required": ["action"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_docker_troubleshooting_steps",
            "description": "Get step-by-step diagnostic instructions for Docker container crashes, exits, and port conflicts.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "failure_type": {
                            "type": "string",
                            "description": "Failure type, e.g. 'container_exit', 'port_conflict', 'oom_killed'.",
                        }
                    },
                    "required": ["failure_type"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_kubernetes_troubleshooting_steps",
            "description": "Get step-by-step diagnostic instructions for Kubernetes pod issues (CrashLoopBackOff, ImagePullBackOff, Pending, OOMKilled).",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "pod_status": {
                            "type": "string",
                            "description": "Pod status or error, e.g. 'CrashLoopBackOff', 'ImagePullBackOff', 'Pending'.",
                        }
                    },
                    "required": ["pod_status"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_cicd_troubleshooting_steps",
            "description": "Get step-by-step diagnostic instructions for GitHub Actions and CI/CD pipeline failures.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "failure_type": {
                            "type": "string",
                            "description": "Failure type, e.g. 'aws_oidc_failure', 'workflow_failure'.",
                        }
                    },
                    "required": ["failure_type"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "explain_error",
            "description": "Parse and explain an error message, exception, or log snippet in simple, beginner-friendly English.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "error_message": {
                            "type": "string",
                            "description": "The error message or log line to explain.",
                        }
                    },
                    "required": ["error_message"],
                }
            },
        }
    },
]


def get_tools_spec() -> List[Dict[str, Any]]:
    """Return the list of tool specifications formatted for Bedrock Converse API."""
    return TOOL_DEFINITIONS


def dispatch_tool(tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a registered diagnostic tool deterministically and safely.

    Guarantees no modifications to infrastructure are ever executed.
    """
    safe_name = tool_name.strip()
    args = tool_args or {}

    try:
        if safe_name == "get_ec2_troubleshooting_steps":
            return get_ec2_troubleshooting_steps(
                issue_type=str(args.get("issue_type", "web_unreachable")),
                os_type=str(args.get("os_type", "linux")),
            )
        elif safe_name == "get_http_troubleshooting_steps":
            try:
                code = int(args.get("error_code", 502))
            except (ValueError, TypeError):
                code = 502
            return get_http_troubleshooting_steps(
                error_code=code,
                web_server=str(args.get("web_server", "nginx")),
            )
        elif safe_name == "get_s3_access_denied_steps":
            return get_s3_access_denied_steps(
                operation=str(args.get("operation", "GetObject")),
                requester_type=str(args.get("requester_type", "iam_role")),
            )
        elif safe_name == "get_iam_troubleshooting_steps":
            return get_iam_troubleshooting_steps(
                action=str(args.get("action", "*")),
                resource_arn=str(args.get("resource_arn", "*")),
            )
        elif safe_name == "get_docker_troubleshooting_steps":
            return get_docker_troubleshooting_steps(
                failure_type=str(args.get("failure_type", "container_exit")),
            )
        elif safe_name == "get_kubernetes_troubleshooting_steps":
            return get_kubernetes_troubleshooting_steps(
                pod_status=str(args.get("pod_status", "CrashLoopBackOff")),
            )
        elif safe_name == "get_cicd_troubleshooting_steps":
            return get_cicd_troubleshooting_steps(
                failure_type=str(args.get("failure_type", "workflow_failure")),
            )
        elif safe_name == "explain_error":
            return explain_error(
                error_message=str(args.get("error_message", "")),
            )
        else:
            return {
                "error": f"Unknown diagnostic tool '{safe_name}'.",
                "available_tools": [t["toolSpec"]["name"] for t in TOOL_DEFINITIONS],
            }
    except Exception as e:
        return {
            "error": f"Error executing tool '{safe_name}': {type(e).__name__} - {str(e)}"
        }
