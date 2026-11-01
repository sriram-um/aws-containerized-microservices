#!/usr/bin/env bash
# Lint and deploy template.yaml as stack "containerized-microservices".
# Usage: scripts/deploy.sh [ParamKey=Value ...]     e.g. scripts/deploy.sh EnableCompute=false
. "$(dirname "$0")/lib.sh"
check_identity
cd "$REPO_ROOT"

# cfn-lint runs on its own (not piped) so a lint failure stops the script
.venv/Scripts/cfn-lint template.yaml
echo "cfn-lint OK"

args=(--stack-name "$STACK_NAME" --template-file template.yaml
      --capabilities CAPABILITY_NAMED_IAM
      --tags project=containerized-microservices
      --no-fail-on-empty-changeset)
if [[ $# -gt 0 ]]; then
  args+=(--parameter-overrides "$@")
fi
aws cloudformation deploy "${args[@]}"

aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].[StackStatus, Outputs[].[OutputKey, OutputValue]]' --output text | tr -d '\r'
