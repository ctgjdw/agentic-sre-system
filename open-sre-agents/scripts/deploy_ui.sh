#!/usr/bin/env bash
# Build the Next.js export and sync it to the S3 UI bucket.
# Reads outputs from terraform; pass --skip-build to deploy an existing ./ui/out.

set -euo pipefail

cd "$(dirname "$0")/.."

SKIP_BUILD=0
if [[ "${1:-}" == "--skip-build" ]]; then SKIP_BUILD=1; fi

API_URL=$(cd infra && terraform output -raw sut_api_url)
UI_BUCKET=$(cd infra && terraform output -raw ui_bucket)
UI_URL=$(cd infra && terraform output -raw ui_website_url)

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  cd ui
  NEXT_PUBLIC_API_URL="$API_URL" npm run build
  cd ..
fi

aws s3 sync ui/out/ "s3://${UI_BUCKET}/" --delete

echo
echo "API : $API_URL"
echo "UI  : $UI_URL"
