# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Thin top-level entrypoint for the MiniAgentFramework.
#
# Delegates immediately to skills_catalog_builder.main() to discover all skill.md definition files,
# summarize them into a JSON catalog, and write the resulting skills_summary.md. This module exists
# so that the framework can be launched as `python MiniAgentFramework.py` from the code directory
# without callers needing to know which internal module drives the catalog build pipeline.
#
# Related modules:
#   - skills_catalog_builder.py  -- discovers skills and builds the summary document
#   - code/skills/               -- skill definition files consumed by the catalog builder
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
from skills_catalog_builder import main


# ====================================================================================================
# MARK: ENTRYPOINT
# ====================================================================================================
if __name__ == "__main__":
    main()
