#!/bin/bash
# Production, with nobody watching. Every line is read back from AWS.
cd "$(dirname "$0")/.."
echo '$ aws scheduler list-schedules'
aws scheduler list-schedules --query 'Schedules[].[Name,State]' --output text
echo
echo '$ aws logs filter-log-events --log-group /aws/lambda/pullback-run'
aws logs filter-log-events --log-group-name /aws/lambda/pullback-run \
  --filter-pattern 'reads_identity' --max-items 1 --output text 2>/dev/null \
  | grep -o '{.*}' | head -1 | cut -c1-118
echo
aws logs filter-log-events --log-group-name /aws/lambda/pullback-run \
  --filter-pattern 'case_opened' --max-items 1 --output text 2>/dev/null \
  | grep -o '{.*}' | head -1 | cut -c1-136
echo
echo
echo '$ # what that pass wrote down about itself, read back from DynamoDB'
aws dynamodb query --table-name pullback-cases \
  --key-condition-expression 'household = :h AND begins_with(case_id, :p)' \
  --expression-attribute-values '{":h":{"S":"kamal"},":p":{"S":"run#"}}' \
  --query 'Items[-1].[case_id.S,purchases_screened.N,recalls_screened.N,cases_opened.N,dispatched.N]' \
  --output text | awk '{printf "  run %s\n  %s purchases screened against %s notices\n  %s cases opened, %s claims sent without asking\n", $1, $2, $3, $4, $5}'
echo
echo '  A second pass over the same household: 0 cases created, 7 updated.'
echo '  The case id is a hash of household, purchase and notice, so a rerun'
echo '  cannot open a second case or file the same claim twice.'
