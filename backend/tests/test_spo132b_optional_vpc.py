"""SPO-132b: optional vpc_id for an account with no default VPC.

These tests read the Terraform files. They do not init Terraform and they
do not call AWS.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "infra" / "aws"
VARIABLES = TF / "variables.tf"
NETWORK = TF / "network.tf"
OUTPUTS = TF / "outputs.tf"
EXAMPLE = TF / "terraform.tfvars.example"

VPC_PATTERN = re.compile(r"vpc-[0-9a-f]{8,17}")
PLACEHOLDER = "vpc-0123456789abcdef0"
VALIDATION = (
    'var.vpc_id == null || can(regex("^vpc-[0-9a-f]{8,17}$", var.vpc_id))'
)


def _brace_block(text: str, header: str) -> str:
    start = text.index(header)
    open_at = text.index("{", start)
    depth = 0
    for index in range(open_at, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"unclosed block: {header}")


class TestVpcIdVariable:
    def test_default_null_and_regex_validation(self) -> None:
        block = _brace_block(VARIABLES.read_text(), 'variable "vpc_id"')
        assert "type        = string" in block
        assert "default     = null" in block
        assert VALIDATION in block
        assert "error_message" in block
        # "" is not null. The condition rejects it. Do not treat it as unset.
        assert 'var.vpc_id == ""' not in block
        assert "coalesce" not in block


class TestNetworkSelection:
    def test_default_true_only_inside_the_null_conditional(self) -> None:
        text = NETWORK.read_text()
        assert 'data "aws_vpc" "selected"' in text
        assert "default = var.vpc_id == null ? true : null" in text
        bare = [
            line.strip()
            for line in text.splitlines()
            if re.fullmatch(r"default\s*=\s*true", line.strip())
        ]
        assert bare == []
        assert 'data "aws_vpc" "default"' not in text
        assert ("data.aws_vpc." + "default") not in text

    def test_subnet_lookups_follow_the_selected_vpc(self) -> None:
        text = NETWORK.read_text()
        selected = _brace_block(text, 'data "aws_subnets" "selected"')
        public = _brace_block(text, 'data "aws_subnets" "public"')
        assert 'name   = "vpc-id"' in selected
        assert "data.aws_vpc.selected.id" in selected
        assert 'name   = "vpc-id"' in public
        assert "data.aws_vpc.selected.id" in public
        assert 'name   = "map-public-ip-on-launch"' in public
        assert 'values = ["true"]' in public
        assert 'data "aws_subnets" "default"' not in text

    def test_locals_feed_the_security_groups_and_subnet_group(self) -> None:
        text = NETWORK.read_text()
        locals_block = _brace_block(text, "locals {")
        assert "vpc_id            = data.aws_vpc.selected.id" in locals_block
        assert "subnet_ids        = data.aws_subnets.selected.ids" in locals_block
        assert "public_subnet_ids = data.aws_subnets.public.ids" in locals_block

        subnet_group = _brace_block(text, 'resource "aws_db_subnet_group" "this"')
        app = _brace_block(text, 'resource "aws_security_group" "app"')
        rds = _brace_block(text, 'resource "aws_security_group" "rds"')
        assert "subnet_ids  = local.subnet_ids" in subnet_group
        assert "Default VPC" not in subnet_group
        assert "vpc_id      = local.vpc_id" in app
        assert "vpc_id      = local.vpc_id" in rds
        assert "data.aws_vpc" not in app
        assert "data.aws_vpc" not in rds
        assert "data.aws_subnets" not in subnet_group

    def test_managed_resource_addresses_are_unchanged(self) -> None:
        text = NETWORK.read_text()
        addresses = re.findall(r'^resource "([^"]+)" "([^"]+)"', text, re.M)
        assert addresses == [
            ("aws_db_subnet_group", "this"),
            ("aws_security_group", "app"),
            ("aws_security_group", "rds"),
        ]


class TestExampleAndOutputs:
    def test_example_has_only_the_commented_placeholder(self) -> None:
        text = EXAMPLE.read_text()
        assert f'# vpc_id = "{PLACEHOLDER}"' in text
        assert "Leave vpc_id unset to use the default VPC" in text
        assert "MapPublicIpOnLaunch=true" in text
        assert (
            "aws ec2 describe-vpcs --query "
            "'Vpcs[].{id:VpcId,cidr:CidrBlock,default:IsDefault,"
            "name:Tags[?Key==`Name`]|[0].Value}' --output table"
        ) in text
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            assert "vpc_id" not in line
            assert "vpc-" not in line
        assert VPC_PATTERN.findall(text) == [PLACEHOLDER]

    def test_outputs_expose_the_locals(self) -> None:
        text = OUTPUTS.read_text()
        vpc = _brace_block(text, 'output "vpc_id"')
        public = _brace_block(text, 'output "public_subnet_ids"')
        assert "value       = local.vpc_id" in vpc
        assert "value       = local.public_subnet_ids" in public


class TestDocs:
    def test_three_docs_name_the_missing_default_vpc_section(self) -> None:
        for relative in (
            "infra/aws/README.md",
            "docs/deployment/aws.md",
            "docs/deployment/aws-steps-zh-TW.md",
        ):
            text = (ROOT / relative).read_text()
            assert "## If your account has no default VPC" in text
            assert "no matching EC2 VPC found" in text
            assert PLACEHOLDER in text
            assert "terraform plan" in text


TERRAFORM = shutil.which("terraform")


def _console(vpc_assignment: str | None, expression: str = "var.vpc_id") -> subprocess.CompletedProcess[str]:
    """Evaluate an expression in terraform console. Does not call AWS.

    Terraform 1.9 still exits 0 when variable validation fails, and it may
    print the rejected value on stdout. Callers must look at stderr.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tfvars = Path(tmp) / "console.tfvars"
        lines = [
            'bucket_name   = "sportslab-data-example-us-east-2"',
            'allowed_cidrs = ["198.51.100.10/32"]',
        ]
        if vpc_assignment is not None:
            lines.append(vpc_assignment)
        tfvars.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return subprocess.run(
            [TERRAFORM, "console", "-no-color", f"-var-file={tfvars}"],
            input=expression + "\n",
            cwd=TF,
            check=False,
            capture_output=True,
            text=True,
        )


@pytest.mark.skipif(TERRAFORM is None, reason="terraform is not on PATH")
class TestVpcIdConsole:
    def test_unset_is_null_and_does_not_error(self) -> None:
        result = _console(None)
        combined = result.stdout + result.stderr
        assert "Error: Invalid value for variable" not in combined
        assert "tostring(null)" in result.stdout

    def test_valid_ids_are_accepted(self) -> None:
        for value in ("vpc-01234567", "vpc-0123456789abcdef0"):
            result = _console(f'vpc_id = "{value}"')
            combined = result.stdout + result.stderr
            assert "Error: Invalid value for variable" not in combined, combined
            assert f'"{value}"' in result.stdout

    def test_invalid_ids_are_rejected(self) -> None:
        rejected = (
            'vpc_id = ""',
            'vpc_id = "subnet-123"',
            'vpc_id = "vpc-XYZ"',
            'vpc_id = "vpc-0123456"',
            'vpc_id = "vpc-0123456789abcdef01"',
            'vpc_id = "vpc-ABCDEF01234567890"',
        )
        for assignment in rejected:
            result = _console(assignment)
            assert "Error: Invalid value for variable" in result.stderr
            assert "empty string is not null" in result.stderr
