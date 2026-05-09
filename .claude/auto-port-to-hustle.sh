#!/bin/bash
# Automatically port reusable changes from atletasworld → hustle
# Intelligently extracts generic logic and updates hustle modules

set -e

ATLETAS="/home/slach/Projects/atletasworld"
HUSTLE="/home/slach/Projects/hustle"

echo "🚀 Auto-porting changes to hustle template..."
echo ""

cd "$ATLETAS"

# Get recent commits (last 5)
COMMITS=$(git log --oneline -5 --pretty=format:"%h %s")
echo "📝 Recent commits:"
echo "$COMMITS" | sed 's/^/  /'
echo ""

# Track if we made any changes
CHANGES_MADE=0

# ============================================================================
# 1. Port booking model changes
# ============================================================================
if git diff HEAD~5..HEAD -- src/bookings/models.py | grep -q "^[+-]"; then
    echo "🔧 Detected changes in bookings/models.py"

    # Extract model methods (exclude migrations, imports)
    BOOKING_CHANGES=$(git diff HEAD~5..HEAD -- src/bookings/models.py | \
        grep -E "^\+[[:space:]]*(def |class |@property)" | \
        sed 's/^+//' || true)

    if [ -n "$BOOKING_CHANGES" ]; then
        echo "  → New/modified methods detected"
        echo "$BOOKING_CHANGES" | head -5 | sed 's/^/    /'

        # Create update notes for hustle
        cat >> "$HUSTLE/UPDATES_PENDING.md" << EOF

## Booking Models Update ($(date +%Y-%m-%d))

New methods/properties added in atletasworld:

\`\`\`python
$BOOKING_CHANGES
\`\`\`

**Action**: Review and add to \`hustle/modules/booking_models.py\`

EOF
        CHANGES_MADE=1
    fi
fi

# ============================================================================
# 2. Port API changes
# ============================================================================
if git diff HEAD~5..HEAD -- src/bookings/api.py | grep -q "^[+-]"; then
    echo "🔧 Detected changes in bookings/api.py"

    # Extract new viewset methods
    API_CHANGES=$(git diff HEAD~5..HEAD -- src/bookings/api.py | \
        grep -E "^\+[[:space:]]*(def |class |@action)" | \
        sed 's/^+//' || true)

    if [ -n "$API_CHANGES" ]; then
        echo "  → New API endpoints detected"

        cat >> "$HUSTLE/UPDATES_PENDING.md" << EOF

## API Updates ($(date +%Y-%m-%d))

New endpoints/methods:

\`\`\`python
$API_CHANGES
\`\`\`

**Action**: Review and add to \`hustle/modules/booking_api.py\`

EOF
        CHANGES_MADE=1
    fi
fi

# ============================================================================
# 3. Port client model changes (ClientPackage, Player, etc.)
# ============================================================================
if git diff HEAD~5..HEAD -- src/clients/models.py | grep -q "^[+-]"; then
    echo "🔧 Detected changes in clients/models.py"

    # Check if ClientPackage was modified
    if git diff HEAD~5..HEAD -- src/clients/models.py | grep -q "class ClientPackage"; then
        echo "  → ClientPackage model updated"

        # Extract the player field addition
        PACKAGE_CHANGES=$(git diff HEAD~5..HEAD -- src/clients/models.py | \
            grep -A5 -B5 "player.*ForeignKey\|player.*models\.ForeignKey" || true)

        if [ -n "$PACKAGE_CHANGES" ]; then
            cat >> "$HUSTLE/UPDATES_PENDING.md" << EOF

## ClientPackage Model Update ($(date +%Y-%m-%d))

Player-specific package support added:

\`\`\`python
$PACKAGE_CHANGES
\`\`\`

**Action**: Add to \`hustle/models.py\` ClientPackage model

EOF
            CHANGES_MADE=1
        fi
    fi
fi

# ============================================================================
# 4. Auto-update hustle CHANGELOG.md
# ============================================================================
if [ $CHANGES_MADE -eq 1 ]; then
    cd "$HUSTLE"

    # Check if UPDATES_PENDING.md exists
    if [ -f "UPDATES_PENDING.md" ]; then
        echo ""
        echo "✅ Update notes written to: $HUSTLE/UPDATES_PENDING.md"
        echo ""
        echo "📋 Summary:"
        grep "^## " "$HUSTLE/UPDATES_PENDING.md" | tail -5 | sed 's/^/  /'
        echo ""
        echo "🔗 Next steps:"
        echo "   1. cd $HUSTLE"
        echo "   2. Review: cat UPDATES_PENDING.md"
        echo "   3. Port changes manually"
        echo "   4. Update CHANGELOG.md"
        echo "   5. git commit && git push"
    fi
else
    echo "ℹ️  No reusable model/API changes detected"
fi

echo ""
echo "✨ Sync check complete"
