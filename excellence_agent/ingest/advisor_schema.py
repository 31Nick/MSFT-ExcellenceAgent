"""Azure Advisor CSV export schema constants and validation."""

# ---------------------------------------------------------------------------
# Column name constants
# ---------------------------------------------------------------------------
COL_ADV_BUSINESS_IMPACT = "Business Impact"
COL_ADV_RECOMMENDATION = "Recommendation"
COL_ADV_SUBSCRIPTION_ID = "Subscription ID"
COL_ADV_SUBSCRIPTION_NAME = "Subscription Name"
COL_ADV_RESOURCE_GROUP = "Resource Group"
COL_ADV_RESOURCE_NAME = "Resource Name"
COL_ADV_TYPE = "Type"
COL_ADV_UPDATED_DATE = "Updated Date"
COL_ADV_POTENTIAL_BENEFITS = "Potential benefits"
COL_ADV_COST_IMPLICATIONS = "Cost implications (Preview)"
COL_ADV_DESCRIPTION_CHANGES = "Description of changes"
COL_ADV_RETIREMENT_DATE = "Retirement date"
COL_ADV_RETIRING_FEATURE = "Retiring feature"

ADVISOR_COLUMNS: list[str] = [
    COL_ADV_BUSINESS_IMPACT,
    COL_ADV_RECOMMENDATION,
    COL_ADV_SUBSCRIPTION_ID,
    COL_ADV_SUBSCRIPTION_NAME,
    COL_ADV_RESOURCE_GROUP,
    COL_ADV_RESOURCE_NAME,
    COL_ADV_TYPE,
    COL_ADV_UPDATED_DATE,
    COL_ADV_POTENTIAL_BENEFITS,
    COL_ADV_COST_IMPLICATIONS,
    COL_ADV_DESCRIPTION_CHANGES,
    COL_ADV_RETIREMENT_DATE,
    COL_ADV_RETIRING_FEATURE,
]

# ---------------------------------------------------------------------------
# Minimum required columns (must exist for a valid parse)
# ---------------------------------------------------------------------------
ADVISOR_REQUIRED_COLUMNS: list[str] = [
    COL_ADV_BUSINESS_IMPACT,
    COL_ADV_RECOMMENDATION,
    COL_ADV_SUBSCRIPTION_ID,
    COL_ADV_RESOURCE_GROUP,
    COL_ADV_RESOURCE_NAME,
    COL_ADV_TYPE,
]


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------
def validate_advisor_columns(
    actual_columns: list[str],
    expected_columns: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Check that *expected_columns* are present in *actual_columns*.

    When *expected_columns* is ``None`` the full :data:`ADVISOR_COLUMNS` list
    is used.

    Returns:
        (is_valid, missing_columns) — *is_valid* is ``True`` when every
        expected column was found.
    """
    if expected_columns is None:
        expected_columns = ADVISOR_COLUMNS
    actual_set = {col.strip() for col in actual_columns}
    missing = [col for col in expected_columns if col not in actual_set]
    return (len(missing) == 0, missing)
