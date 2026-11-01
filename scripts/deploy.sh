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
overrides=("$@")
# Exercise 3 baseline: the DB password lives outside the repo (generated on first use) and is
# passed as a NoEcho parameter. Exercise 9 moves it to Secrets Manager.
SECRETS_FILE="$HOME/.containerized-microservices.env"
if [[ ! -f "$SECRETS_FILE" ]]; then
  umask 077
  echo "DB_PASSWORD=$(.venv/Scripts/python -c 'import secrets; print(secrets.token_urlsafe(24))')" > "$SECRETS_FILE"
  echo "Generated DB password in $SECRETS_FILE"
fi
if [[ " $* " != *" DBPassword="* ]]; then
  overrides+=("DBPassword=$(grep '^DB_PASSWORD=' "$SECRETS_FILE" | cut -d= -f2-)")
fi
args+=(--parameter-overrides "${overrides[@]}")
aws cloudformation deploy "${args[@]}"

aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].[StackStatus, Outputs[].[OutputKey, OutputValue]]' --output text | tr -d '\r'
