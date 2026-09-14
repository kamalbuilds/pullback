#!/usr/bin/env bash
# Deploys the pullback-run Lambda: least-privilege policies on the shared
# execution role, a packaged zip, the function itself, a public Function URL
# for the console, and two EventBridge Scheduler schedules. Safe to re-run;
# every step either overwrites the same-named resource or checks for it
# first.
set -euo pipefail

export AWS_PROFILE=palimpsest
export AWS_DEFAULT_REGION=us-east-1
unset AWS_BEARER_TOKEN_BEDROCK || true

REGION=us-east-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
FUNCTION_NAME=pullback-run
ROLE_NAME=pullback-exec
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
SCHEDULER_ROLE_NAME=pullback-scheduler
SCHEDULER_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${SCHEDULER_ROLE_NAME}"
TABLE_CASES=pullback-cases
TABLE_RECALLS=pullback-recalls
BUCKET=pullback-evidence-079415246611
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build"
ZIP_PATH="${REPO_ROOT}/build.zip"

echo "== account ${ACCOUNT_ID} region ${REGION} =="

echo "== least-privilege policies on ${ROLE_NAME} =="

aws iam put-role-policy --role-name "${ROLE_NAME}" --policy-name pullback-dynamodb --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PullbackTables",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
        "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
        "dynamodb:BatchWriteItem", "dynamodb:BatchGetItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:'"${REGION}"':'"${ACCOUNT_ID}"':table/'"${TABLE_CASES}"'",
        "arn:aws:dynamodb:'"${REGION}"':'"${ACCOUNT_ID}"':table/'"${TABLE_RECALLS}"'"
      ]
    }
  ]
}'

aws iam put-role-policy --role-name "${ROLE_NAME}" --policy-name pullback-s3-evidence --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PullbackEvidenceList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::'"${BUCKET}"'"
    },
    {
      "Sid": "PullbackEvidenceObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::'"${BUCKET}"'/*"
    }
  ]
}'

# Log group name is fixed by the function name, but CloudWatch requires the
# log *stream* segment of the ARN to stay wildcarded (Lambda names streams
# per invocation, unpredictably) -- the one wildcard here is unavoidable.
aws iam put-role-policy --role-name "${ROLE_NAME}" --policy-name pullback-logs --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PullbackLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:'"${REGION}"':'"${ACCOUNT_ID}"':log-group:/aws/lambda/'"${FUNCTION_NAME}"':*"
    }
  ]
}'

# ses:SendEmail has no per-recipient or per-template resource to scope to;
# identity/* is the tightest ARN pattern SES accepts (it scopes to "sending
# as an identity in this account", not "any SES action anywhere").
aws iam put-role-policy --role-name "${ROLE_NAME}" --policy-name pullback-ses --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PullbackSendClaimEmail",
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail"],
      "Resource": "arn:aws:ses:'"${REGION}"':'"${ACCOUNT_ID}"':identity/*"
    }
  ]
}'

echo "== scheduler invoke role =="
if ! aws iam get-role --role-name "${SCHEDULER_ROLE_NAME}" >/dev/null 2>&1; then
  aws iam create-role --role-name "${SCHEDULER_ROLE_NAME}" --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {"Service": "scheduler.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }
    ]
  }' >/dev/null
  echo "waiting for new IAM role to propagate..."
  sleep 8
fi
aws iam put-role-policy --role-name "${SCHEDULER_ROLE_NAME}" --policy-name pullback-invoke-lambda --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokePullbackRun",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:'"${REGION}"':'"${ACCOUNT_ID}"':function:'"${FUNCTION_NAME}"'"
    }
  ]
}'

# The Anthropic key is read from the .env the user placed, passed straight into
# the function configuration, and never printed. Without it the scheduled pass
# still runs, but only the deterministic matcher, with no identity reading.
LAMBDA_ENV="PULLBACK_RUN_AGENT=1"
if [ -f "${REPO_ROOT}/.env" ]; then
  ANTHROPIC_KEY="$(grep -m1 '^ANTHROPIC_API_KEY=' "${REPO_ROOT}/.env" | cut -d= -f2- | tr -d '"'"'"'\r')"
  if [ -n "${ANTHROPIC_KEY}" ]; then
    LAMBDA_ENV="${LAMBDA_ENV},ANTHROPIC_API_KEY=${ANTHROPIC_KEY}"
    echo "== anthropic key found in .env, the scheduled pass will read identity =="
  fi
else
  echo "== no .env, the scheduled pass will run deterministic matching only =="
fi

echo "== packaging lambda =="
rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}"
# boto3 ships in the python3.12 Lambda runtime already. Everything else the
# unattended run needs has to be vendored, including strands and anthropic:
# the scheduled pass runs the same agent a person runs locally, so the model's
# identity reading happens on the schedule too, not just when someone watches.
# 102MB unpacked, 28MB zipped, against Lambda 250MB and 50MB ceilings. Memory
# stays at 512MB because this account is capped there, so the pass is slower
# than it would otherwise be but still finishes well inside the timeout.
# Built on macOS, run on Amazon Linux. pydantic-core and friends ship compiled
# extensions, so the local arm64 wheels are useless in Lambda: without the
# explicit platform pins the function dies on "No module named
# pydantic_core._pydantic_core" at import time.
"${REPO_ROOT}/.venv/bin/pip" install --target "${BUILD_DIR}" \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 \
  --only-binary=:all: --upgrade \
  httpx strands-agents anthropic --quiet --disable-pip-version-check
find "${BUILD_DIR}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
# dist-info stays: anthropic resolves its own dependency versions through
# importlib.metadata at import time, so stripping metadata to save a few MB
# kills the function with PackageNotFoundError instead.
cp -R "${REPO_ROOT}/agent" "${BUILD_DIR}/agent"
find "${BUILD_DIR}/agent" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp "${REPO_ROOT}/infra/lambda_handler.py" "${BUILD_DIR}/lambda_handler.py"
# agent.engine.scan.load_household() reads data/household.json relative to
# the repo root; only that one file is needed in the zip (the multi-MB raw
# feed dumps in data/ are not read by anything this Lambda imports).
mkdir -p "${BUILD_DIR}/data"
cp "${REPO_ROOT}/data/household.json" "${BUILD_DIR}/data/household.json"
cp "${REPO_ROOT}/data/cpsc_2026.json" "${BUILD_DIR}/data/cpsc_2026.json"
( cd "${BUILD_DIR}" && zip -r -q "${ZIP_PATH}" . -x '*.pyc' )
echo "package: ${ZIP_PATH} ($(du -h "${ZIP_PATH}" | cut -f1))"

echo "== deploying function ${FUNCTION_NAME} =="
if aws lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "${FUNCTION_NAME}" --zip-file "fileb://${ZIP_PATH}" >/dev/null
  aws lambda wait function-updated --function-name "${FUNCTION_NAME}"
  aws lambda update-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --role "${ROLE_ARN}" \
    --runtime python3.12 \
    --handler lambda_handler.handler \
    --timeout 900 \
    --memory-size 512 \
    --environment "Variables={${LAMBDA_ENV}}" >/dev/null
  aws lambda wait function-updated --function-name "${FUNCTION_NAME}"
else
  aws lambda create-function \
    --function-name "${FUNCTION_NAME}" \
    --runtime python3.12 \
    --role "${ROLE_ARN}" \
    --handler lambda_handler.handler \
    --timeout 900 \
    --memory-size 512 \
    --environment "Variables={${LAMBDA_ENV}}" \
    --zip-file "fileb://${ZIP_PATH}" >/dev/null
  aws lambda wait function-active --function-name "${FUNCTION_NAME}"
fi

echo "== function url =="
# AuthType NONE: the web console is a static frontend with no AWS
# credentials to sign a SigV4 request, so IAM auth on the Function URL is
# not an option here. Public invoke is scoped to this one function only.
if ! aws lambda get-function-url-config --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  aws lambda create-function-url-config \
    --function-name "${FUNCTION_NAME}" \
    --auth-type NONE \
    --cors '{"AllowOrigins":["*"],"AllowMethods":["*"],"AllowHeaders":["*"]}' >/dev/null
fi
if ! aws lambda get-policy --function-name "${FUNCTION_NAME}" 2>/dev/null | grep -q FunctionURLAllowPublicAccess; then
  aws lambda add-permission \
    --function-name "${FUNCTION_NAME}" \
    --statement-id FunctionURLAllowPublicAccess \
    --action lambda:InvokeFunctionUrl \
    --principal '*' \
    --function-url-auth-type NONE >/dev/null
fi
FUNCTION_URL=$(aws lambda get-function-url-config --function-name "${FUNCTION_NAME}" --query FunctionUrl --output text)

echo "== schedules =="
LAMBDA_ARN=$(aws lambda get-function --function-name "${FUNCTION_NAME}" --query 'Configuration.FunctionArn' --output text)

create_or_update_schedule() {
  local name="$1" expr="$2" state="$3"
  local target='{"Arn":"'"${LAMBDA_ARN}"'","RoleArn":"'"${SCHEDULER_ROLE_ARN}"'"}'
  if aws scheduler get-schedule --name "$name" >/dev/null 2>&1; then
    aws scheduler update-schedule \
      --name "$name" \
      --schedule-expression "$expr" \
      --state "$state" \
      --flexible-time-window '{"Mode":"OFF"}' \
      --target "$target" >/dev/null
  else
    aws scheduler create-schedule \
      --name "$name" \
      --schedule-expression "$expr" \
      --state "$state" \
      --flexible-time-window '{"Mode":"OFF"}' \
      --target "$target" >/dev/null
  fi
}

# Every day, always on: the loop the pitch depends on.
create_or_update_schedule pullback-daily "rate(1 day)" ENABLED
# Every 15 minutes, created disabled: flip it on during a demo to show the
# unattended loop running on camera without waiting a day for it.
create_or_update_schedule pullback-frequent "rate(15 minutes)" DISABLED

echo ""
echo "Function URL: ${FUNCTION_URL}"
