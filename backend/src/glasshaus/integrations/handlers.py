"""Registers the integration event consumers."""

from glasshaus.integrations.delivery import fan_out

__all__ = ["fan_out"]
