#!/usr/bin/env python

"""Convert SAM templates to CloudFormation templates.

Known limitations: cannot transform CodeUri pointing at local directory.
"""
import argparse
import json
import logging
import platform
import subprocess
import sys
from functools import reduce
from pathlib import Path
from typing import List

import boto3

# To allow this script to be executed from other directories
sys.path.insert(0, str(Path(__file__).absolute().parent.parent))

from samtranslator.model.exceptions import InvalidDocumentException
from samtranslator.public.translator import ManagedPolicyLoader
from samtranslator.translator.transform import transform
from samtranslator.yaml_helper import yaml_parse

LOG = logging.getLogger(__name__)
iam_client = boto3.client("iam")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", nargs="?")
parser.add_argument(
    "--template-file",
    help="Location of SAM template to transform [default: template.yaml].",
    type=Path,
    default=Path("template.yaml"),
)
parser.add_argument(
    "--output-template",
    help="Location to store resulting CloudFormation template [default: transformed-template.json].",
    type=Path,
    default=Path("transformed-template.json"),
)
parser.add_argument(
    "--s3-bucket",
    help="S3 bucket to use for SAM artifacts when using the `package` command",
)
parser.add_argument(
    "--capabilities",
    help="Capabilities",
)
parser.add_argument(
    "--stack-name",
    help="Unique name for your CloudFormation Stack",
)
parser.add_argument(
    "--verbose",
    help="Enables verbose logging",
    action="store_true",
)
cli_options = parser.parse_args()

if cli_options.verbose:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig()


def execute_command(command: str, args: List[str]) -> None:
    try:
        aws_cmd = "aws" if platform.system().lower() != "windows" else "aws.cmd"
        command_with_args = [aws_cmd, "cloudformation", command, *list(args)]

        LOG.debug("Executing command: %s", command_with_args)

        subprocess.check_call(command_with_args)

        LOG.debug("Command successful")
    except subprocess.CalledProcessError as e:
        # Underlying aws command will print the exception to the user
        LOG.debug("Exception: %s", e)
        sys.exit(e.returncode)


def package(input_file_path: Path) -> Path:
    template_file = input_file_path
    package_output_template_file = Path(str(input_file_path) + "._sam_packaged_.yaml")
    s3_bucket = cli_options.s3_bucket
    args = [
        "--template-file",
        template_file,
        "--output-template-file",
        package_output_template_file,
        "--s3-bucket",
        s3_bucket,
    ]

    execute_command("package", args)

    return package_output_template_file


def transform_template(input_file_path: Path, output_file_path: Path):  # type: ignore[no-untyped-def]
    with input_file_path.open() as f:
        sam_template = yaml_parse(f)  # type: ignore[no-untyped-call]

    try:
        cloud_formation_template = transform(sam_template, {}, ManagedPolicyLoader(iam_client))
        cloud_formation_template_prettified = json.dumps(cloud_formation_template, indent=1)

        output_file_path.write_text(cloud_formation_template_prettified, encoding="utf-8")

        print("Wrote transformed CloudFormation template to: ", output_file_path)
    except InvalidDocumentException as e:
        error_message = reduce(lambda message, error: message + " " + error.message, e.causes, e.message)
        LOG.error(error_message)
        errors = (cause.message for cause in e.causes)
        LOG.error(errors)


def deploy(template_file: Path) -> None:
    capabilities = cli_options.capabilities
    stack_name = cli_options.stack_name
    args = ["--template-file", template_file, "--capabilities", capabilities, "--stack-name", stack_name]

    execute_command("deploy", args)


if __name__ == "__main__":
    input_file_path = Path(cli_options.template_file)
    output_file_path = Path(cli_options.output_template)

    if cli_options.command == "package":
        package_output_template_file = package(input_file_path)
        transform_template(package_output_template_file, output_file_path)
    elif cli_options.command == "deploy":
        package_output_template_file = package(input_file_path)
        transform_template(package_output_template_file, output_file_path)
        deploy(output_file_path)
    else:
        transform_template(input_file_path, output_file_path)
