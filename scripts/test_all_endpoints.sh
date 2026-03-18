#!/bin/bash
# Test all API endpoints for the OCMRI Billing Reconciliation System
# Usage: bash scripts/test_all_endpoints.sh

BASE="http://localhost:8000"
PASS=0
FAIL=0
WARN=0

check() {
  local desc="$1"
  local url="$2"
  local method="${3:-GET}"

  if [ "$method" = "GET" ]; then
    response=$(curl -s -o /tmp/api_response.json -w "%{http_code}" "$url" 2>/dev/null)
  elif [ "$method" = "POST" ]; then
    response=$(curl -s -o /tmp/api_response.json -w "%{http_code}" -X POST "$url" 2>/dev/null)
  elif [ "$method" = "PATCH" ]; then
    response=$(curl -s -o /tmp/api_response.json -w "%{http_code}" -X PATCH "$url" -H "Content-Type: application/json" -d "$4" 2>/dev/null)
  fi

  body_preview=$(cat /tmp/api_response.json 2>/dev/null | python3 -c "import sys; s=sys.stdin.read(); print(s[:120])" 2>/dev/null)

  if [ "$response" = "200" ]; then
    echo "  PASS [$response] $desc"
    PASS=$((PASS+1))
  elif [ "$response" = "201" ] || [ "$response" = "204" ]; then
    echo "  PASS [$response] $desc"
    PASS=$((PASS+1))
  elif [ "$response" = "422" ]; then
    echo "  WARN [$response] $desc (validation error)"
    WARN=$((WARN+1))
  else
    echo "  FAIL [$response] $desc -> $body_preview"
    FAIL=$((FAIL+1))
  fi
}

echo "==========================================="
echo " OCMRI API Endpoint Test Suite"
echo "==========================================="

echo ""
echo "--- Health ---"
check "Health check" "$BASE/health"

echo ""
echo "--- Import (F-01/F-02) ---"
check "Import status" "$BASE/api/import/status"
check "Import history" "$BASE/api/import/history"
check "EOB scan preview" "$BASE/api/import/scan-eobs/preview"

echo ""
echo "--- Matching (F-03) ---"
check "Match summary" "$BASE/api/matching/summary"
check "Unmatched claims" "$BASE/api/matching/unmatched"
check "Matched claims" "$BASE/api/matching/matched"
check "Diagnose claim #1" "$BASE/api/matching/diagnose/1"

echo ""
echo "--- Denials (F-04) ---"
check "Denial summary" "$BASE/api/denials/summary"
check "Denial list" "$BASE/api/denials?page=1"
check "Denial queue" "$BASE/api/denials/queue?limit=20"

echo ""
echo "--- Underpayments (F-05) ---"
check "Underpayment summary" "$BASE/api/underpayments/summary"
check "Underpayment list" "$BASE/api/underpayments?page=1"

echo ""
echo "--- Filing Deadlines (F-06) ---"
check "Filing alerts" "$BASE/api/filing-deadlines/alerts"
check "Filing list" "$BASE/api/filing-deadlines?page=1"

echo ""
echo "--- Secondary Follow-Up (F-07) ---"
check "Secondary summary" "$BASE/api/secondary-followup/summary"
check "Secondary list" "$BASE/api/secondary-followup?page=1"

echo ""
echo "--- ERA Payments ---"
check "ERA payments list" "$BASE/api/era/payments"

echo ""
echo "--- Analytics (F-08 to F-16) ---"
check "Patient search (by name)" "$BASE/api/analytics/patients/search?q=SMITH"
check "Patient search (by ID)" "$BASE/api/analytics/patients/search?q=4001"
check "Patient detail" "$BASE/api/analytics/patients/SMITH,%20JOHN/detail"
check "Payer alerts" "$BASE/api/analytics/payer-alerts"
check "Payer monitor list" "$BASE/api/analytics/payer-monitor"
check "Payer carrier detail" "$BASE/api/analytics/payer-monitor/M%2FM"
check "Physicians list" "$BASE/api/analytics/physicians?limit=15"
check "Physician detail" "$BASE/api/analytics/physicians/JHANGIANI"
check "PSMA dashboard" "$BASE/api/analytics/psma"
check "Gado analytics" "$BASE/api/analytics/gado"
check "Denial analytics" "$BASE/api/analytics/denial-analytics"
check "Duplicates" "$BASE/api/analytics/duplicates"

echo ""
echo "--- Insights (F-19) ---"
check "Recommendations" "$BASE/api/insights/recommendations"
check "Knowledge graph" "$BASE/api/insights/graph"
check "Session report" "$BASE/api/insights/report"

echo ""
echo "--- Pipeline (F-21) ---"
check "Pipeline suggestions" "$BASE/api/analytics/pipeline-suggestions?timeout=30000"
check "Pipeline notes" "$BASE/api/analytics/pipeline-notes"

echo ""
echo "--- Tasks (F-22) ---"
check "Today's tasks" "$BASE/api/tasks/today"
check "Task templates" "$BASE/api/tasks/templates"
check "Task history" "$BASE/api/tasks/history?days=14"

echo ""
echo "==========================================="
echo " Results: PASS=$PASS  FAIL=$FAIL  WARN=$WARN"
echo "==========================================="
