"""APRL v2 Excel report schema constants and validation."""

# ---------------------------------------------------------------------------
# Sheet names
# ---------------------------------------------------------------------------
SHEET_IMPACTED_RESOURCES = "4.ImpactedResourcesAnalysis"
SHEET_PLATFORM_ISSUES = "5.PlatformIssuesAnalysis"

# Header row (0-based index) — data starts at row 12.
HEADER_ROW = 11

# ---------------------------------------------------------------------------
# Column name constants — Impacted Resources (sheet 4)
# ---------------------------------------------------------------------------
COL_REVIEW_STATUS = "REQUIRED ACTIONS / REVIEW STATUS"
COL_VALIDATION_CATEGORY = "ValidationCategory"
COL_RESOURCE_TYPE = "Resource Type"
COL_SUBSCRIPTION_ID = "subscriptionId"
COL_RESOURCE_GROUP = "resourceGroup"
COL_LOCATION = "location"
COL_NAME = "name"
COL_ID = "id"
COL_CUSTOM1 = "custom1"
COL_CUSTOM2 = "custom2"
COL_CUSTOM3 = "custom3"
COL_CUSTOM4 = "custom4"
COL_CUSTOM5 = "custom5"
COL_RECOMMENDATION_TITLE = "Recommendation Title"
COL_IMPACT = "Impact"
COL_RECOMMENDATION_CONTROL = "Recommendation Control"
COL_POTENTIAL_BENEFIT = "Potential Benefit"
COL_LEARN_MORE_LINK = "Learn More Link"
COL_LONG_DESCRIPTION = "Long Description"
COL_GUID = "Guid"
COL_CATEGORY = "Category"
COL_SOURCE = "Source"
COL_WAF_PILLAR = "WAF Pillar"
COL_PLATFORM_ISSUE_TRACKING_ID = "Platform Issue TrackingId"
COL_RETIREMENT_TRACKING_ID = "Retirement TrackingId"
COL_SUPPORT_REQUEST_NUMBER = "Support Request Number"
COL_NOTES = "Notes"
COL_CHECK_NAME = "checkName"

IMPACTED_RESOURCES_COLUMNS: list[str] = [
    COL_REVIEW_STATUS,
    COL_VALIDATION_CATEGORY,
    COL_RESOURCE_TYPE,
    COL_SUBSCRIPTION_ID,
    COL_RESOURCE_GROUP,
    COL_LOCATION,
    COL_NAME,
    COL_ID,
    COL_CUSTOM1,
    COL_CUSTOM2,
    COL_CUSTOM3,
    COL_CUSTOM4,
    COL_CUSTOM5,
    COL_RECOMMENDATION_TITLE,
    COL_IMPACT,
    COL_RECOMMENDATION_CONTROL,
    COL_POTENTIAL_BENEFIT,
    COL_LEARN_MORE_LINK,
    COL_LONG_DESCRIPTION,
    COL_GUID,
    COL_CATEGORY,
    COL_SOURCE,
    COL_WAF_PILLAR,
    COL_PLATFORM_ISSUE_TRACKING_ID,
    COL_RETIREMENT_TRACKING_ID,
    COL_SUPPORT_REQUEST_NUMBER,
    COL_NOTES,
    COL_CHECK_NAME,
]

# ---------------------------------------------------------------------------
# Column name constants — Platform Issues (sheet 5)
# ---------------------------------------------------------------------------
COL_PI_REVIEW_STATUS = COL_REVIEW_STATUS  # shared name
COL_PI_TRACKING_ID = "Tracking ID"
COL_PI_EVENT_TYPE = "Event Type"
COL_PI_EVENT_SOURCE = "Event Source"
COL_PI_STATUS = "Status"
COL_PI_TITLE = "Title"
COL_PI_LEVEL = "Level"
COL_PI_EVENT_LEVEL = "Event Level"
COL_PI_START_TIME = "Start Time"
COL_PI_MITIGATION_TIME = "Mitigation Time"
COL_PI_IMPACTED_SERVICE = "Impacted Service"
COL_PI_WHAT_HAPPENED = "What happened"
COL_PI_WHAT_WENT_WRONG = "What went wrong and why"
COL_PI_HOW_RESPONDED = "How did we respond"
COL_PI_LESS_LIKELY = "How are we making incidents like this less likely or less impactful"
COL_PI_LESS_IMPACTFUL = "How can customers make incidents like this less impactful"

PLATFORM_ISSUES_COLUMNS: list[str] = [
    COL_PI_REVIEW_STATUS,
    COL_PI_TRACKING_ID,
    COL_PI_EVENT_TYPE,
    COL_PI_EVENT_SOURCE,
    COL_PI_STATUS,
    COL_PI_TITLE,
    COL_PI_LEVEL,
    COL_PI_EVENT_LEVEL,
    COL_PI_START_TIME,
    COL_PI_MITIGATION_TIME,
    COL_PI_IMPACTED_SERVICE,
    COL_PI_WHAT_HAPPENED,
    COL_PI_WHAT_WENT_WRONG,
    COL_PI_HOW_RESPONDED,
    COL_PI_LESS_LIKELY,
    COL_PI_LESS_IMPACTFUL,
]

# ---------------------------------------------------------------------------
# Minimum required columns (must exist for a valid parse)
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS: list[str] = [
    COL_REVIEW_STATUS,
    COL_RESOURCE_TYPE,
    COL_SUBSCRIPTION_ID,
    COL_RESOURCE_GROUP,
    COL_NAME,
    COL_ID,
    COL_RECOMMENDATION_TITLE,
    COL_IMPACT,
    COL_CATEGORY,
    COL_WAF_PILLAR,
]


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------
def validate_columns(
    actual_columns: list[str],
    expected_columns: list[str],
) -> tuple[bool, list[str]]:
    """Check that *expected_columns* are present in *actual_columns*.

    Returns:
        (is_valid, missing_columns) — *is_valid* is ``True`` when every
        expected column was found.
    """
    actual_set = {col.strip() for col in actual_columns}
    missing = [col for col in expected_columns if col not in actual_set]
    return (len(missing) == 0, missing)
