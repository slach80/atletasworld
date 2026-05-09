#!/bin/bash
# Sync reusable changes from atletasworld → hustle template
# Called automatically on session close

set -e

ATLETAS="/home/slach/Projects/atletasworld"
HUSTLE="/home/slach/Projects/hustle"

echo "🔄 Syncing reusable changes to hustle template..."
echo ""

# Get list of changed files in current session
cd "$ATLETAS"
CHANGED_FILES=$(git diff --name-only HEAD~5..HEAD | grep -E "models\.py|api\.py|utils\.py" || true)

if [ -z "$CHANGED_FILES" ]; then
    echo "ℹ️  No model/API changes detected in recent commits"
    exit 0
fi

echo "📋 Detected changes in:"
echo "$CHANGED_FILES" | sed 's/^/  - /'
echo ""

# Extract commit messages from recent session
RECENT_COMMITS=$(git log --oneline HEAD~5..HEAD --pretty=format:"- %s")

# Create a sync report
SYNC_REPORT="$HUSTLE/sync-report-$(date +%Y%m%d).md"

cat > "$SYNC_REPORT" << EOF
# Hustle Template Sync - $(date +%Y-%m-%d)

## Changes from atletasworld

$RECENT_COMMITS

## Files to Review for Porting

$CHANGED_FILES

## Manual Steps Required

1. **Review models.py changes**:
   - Check if \`ClientPackage\`, \`Booking\`, or \`SessionType\` models were updated
   - Port logic to hustle/modules/booking_models.py
   - Replace atletasworld-specific FKs with placeholders

2. **Review API changes**:
   - Check booking API endpoints in src/bookings/api.py
   - Port to hustle/modules/booking_api.py
   - Remove atletasworld-specific business logic

3. **Update hustle CHANGELOG.md**:
   - Document new features/fixes
   - Note any breaking changes

4. **Test hustle template**:
   - Ensure placeholder models work
   - Verify no hard-coded atletasworld references

## Next Steps

\`\`\`bash
cd $HUSTLE
# Review sync report
cat sync-report-$(date +%Y%m%d).md

# Make changes, then commit
git add -A
git commit -m "sync: port changes from atletasworld"
git push
\`\`\`

EOF

echo "✅ Sync report created: $SYNC_REPORT"
echo ""
echo "📌 Next: Review the report and manually port reusable changes"
echo "   cd $HUSTLE && cat sync-report-$(date +%Y%m%d).md"
