#!/usr/bin/env bash

echo ""
echo "phase d — utilization & signal validation"
echo "-----------------------------------------"
echo ""

echo "pre-flight (answer honestly):"
echo ""

read -p "1) am i adding execution, routing, or automation? (yes/no): " q1
read -p "2) am i changing architectural boundaries? (yes/no): " q2
read -p "3) am i introducing new authority? (yes/no): " q3

echo ""

if [[ "$q1" == "yes" || "$q2" == "yes" || "$q3" == "yes" ]]; then
  echo "⚠️  hard stop."
  echo "this work does NOT belong in phase d."
  echo "write why before proceeding."
  exit 1
fi

echo "ok. phase d work permitted."
echo ""

echo "select today’s work bucket (pick 1–2 max):"
echo ""
echo "A) retrospective analysis"
echo "B) signal quality review"
echo "C) interpretation & semantics"
echo "D) hygiene (non-capability)"
echo "E) infra reliability (non-intelligent)"
echo ""

read -p "enter letters (e.g. A or A,C): " buckets

echo ""
echo "you selected: $buckets"
echo ""

echo "reminders:"
echo "- no automated agency runs"
echo "- no writes to runs/ except listener"
echo "- no boundary violations"
echo "- end day with a ledger entry"
echo ""

echo "phase d check complete. proceed deliberately."
echo ""
