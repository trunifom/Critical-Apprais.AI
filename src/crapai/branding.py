"""Product naming: single source for the display name (see docs/NAMING_AND_HISTORY.md)."""

PRODUCT_NAME = "Critical Apprais.AI"
"""Display name of the product.

Use it in every user-visible text; never hard-code it and never call the product SARA.
"""

PREDECESSOR_NAMES: tuple[str, ...] = ("SARA", "SARA-App")
"""Names of the predecessor projects. Allowed only in historical or reference contexts."""

# Technical identifiers (decided in ADR 0017). The short form of the product name is "CrAp-AI";
# hyphens and capitals are not possible in package and command names, hence "crapai".
SHORT_NAME = "CrAp-AI"
PACKAGE_NAME = "crapai"
CLI_NAME = "crapai"
STATE_DIR_NAME = ".crapai"
ENV_PREFIX = "CRAPAI_"
