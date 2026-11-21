"""SPO-140: environment-aware names without a second applied stack.

These tests read the Terraform files and, when terraform is installed,
evaluate name_prefix. They do not init a backend and they do not call AWS.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "infra" / "aws"

TERRAFORM = shutil.which("terraform")


def _active_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


class TestEnvironmentVariable:
    def test_dev_is_the_default_and_prod_is_the_only_other_value(self) -> None:
        text = (TF / "variables.tf").read_text()
        start = text.index('variable "environment"')
        block = text[start : text.index('variable "tags"', start)]
        assert "default     = \"dev\"" in block
        assert 'contains(["dev", "prod"], var.environment)' in block


class TestDevNamesStay:
    def test_name_prefix_suffixes_only_when_not_dev(self) -> None:
        text = (TF / "locals.tf").read_text()
        assert (
            'name_prefix     = var.environment == "dev" ? var.project : '
            '"${var.project}-${var.environment}"'
        ) in text

    def test_applied_resources_still_use_the_same_arguments(self) -> None:
        rds = (TF / "rds.tf").read_text()
        s3 = (TF / "s3.tf").read_text()
        network = (TF / "network.tf").read_text()
        assert 'identifier     = "${local.name_prefix}-postgres"' in rds
        assert "engine         = \"postgres\"" in rds
        assert "engine_version = var.engine_version" in rds
        assert "bucket        = var.bucket_name" in s3
        assert 'name        = "${local.name_prefix}-rds"' in network
        assert 'name        = "${local.name_prefix}-app"' in network
        assert "vpc_id      = local.vpc_id" in network
        assert 'resource "aws_vpc"' not in network
        assert 'resource "aws_vpc"' not in (TF / "versions.tf").read_text()
        for name in ("rds.tf", "s3.tf", "network.tf", "iam.tf"):
            for line in _active_lines((TF / name).read_text()):
                assert "name_prefix =" not in line or "local.name_prefix" in line

    def test_example_sets_dev_and_does_not_rename_the_bucket(self) -> None:
        text = (TF / "terraform.tfvars.example").read_text()
        assert 'environment = "dev"' in text
        assert 'bucket_name = "sportslab-data-ACCOUNT-us-east-2"' in text
        assert 'environment = "prod"' not in text


class TestStateKeyPerEnvironment:
    def test_backend_block_stays_commented(self) -> None:
        active = "\n".join(_active_lines((TF / "versions.tf").read_text()))
        assert 'backend "' not in active
        assert "Environment = var.environment" in active

    def test_example_keys_differ_by_environment(self) -> None:
        dev = (TF / "backend-dev.hcl.example").read_text()
        prod = (TF / "backend-prod.hcl.example").read_text()
        assert 'key     = "sportslab/dev/aws.tfstate"' in dev
        assert 'key     = "sportslab/prod/aws.tfstate"' in prod
        assert "REPLACE_WITH_STATE_BUCKET" in dev
        assert "REPLACE_WITH_STATE_BUCKET" in prod


def _console(environment: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        tfvars = Path(tmp) / "console.tfvars"
        tfvars.write_text(
            "\n".join(
                [
                    'bucket_name   = "sportslab-data-example-us-east-2"',
                    'allowed_cidrs = ["198.51.100.10/32"]',
                    f'environment   = "{environment}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return subprocess.run(
            [TERRAFORM, "console", "-no-color", f"-var-file={tfvars}"],
            input="local.name_prefix\n",
            cwd=TF,
            check=False,
            capture_output=True,
            text=True,
        )


@pytest.mark.skipif(TERRAFORM is None, reason="terraform is not on PATH")
class TestNamePrefixConsole:
    def test_dev_prefix_is_the_project(self) -> None:
        result = _console("dev")
        assert result.returncode == 0, result.stderr
        assert '"sportslab"' in result.stdout
        assert "sportslab-dev" not in result.stdout

    def test_prod_prefix_is_suffixed(self) -> None:
        result = _console("prod")
        assert result.returncode == 0, result.stderr
        assert '"sportslab-prod"' in result.stdout

    def test_other_environments_are_rejected(self) -> None:
        result = _console("staging")
        assert "Error: Invalid value for variable" in result.stderr
        assert "environment must be dev or prod." in result.stderr
