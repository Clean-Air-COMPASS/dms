"""Compatibility exports for the renamed shared hourly PM component.

New code should import :mod:`hourly_pm_completeness`. This module remains so
existing U.S. AQI imports outside CompassAQ do not break during the rename.
"""

from .hourly_pm_completeness import *  # noqa: F401,F403
