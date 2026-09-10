# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Helpers for Mixins."""

from typing import Any

import structlog

from opensmi.core.base_ua_object import BaseUaObject


def get_logger(obj: Any, logger: structlog.stdlib.BoundLogger) -> structlog.stdlib.BoundLogger:
    """Get a logger for the given instance."""
    if isinstance(obj, BaseUaObject):
        # return logger.bind(name=obj.full_name)
        return obj.logger
    return logger.bind(obj=obj)
