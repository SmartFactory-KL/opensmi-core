# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Common functionality for both server and client."""

from importlib import metadata

from .async_task_mixin import AsyncTaskMixin as AsyncTaskMixin
from .enums import LifecycleState as LifecycleState
from .lifecycle_mixin import LifecycleMixin as LifecycleMixin
from .lifecycle_mixin import lifecycle as lifecycle
from .logging import LogFormat as LogFormat
from .logging import setup_logging as setup_logging
from .paths import ObjectPath as ObjectPath
from .signal import Signal as Signal
from .ua import OPC_UA_NS as OPC_UA_NS
from .ua import LocalizedText as LocalizedText
from .ua import NodeIdDefinition as NodeIdDefinition
from .ua import QualifiedName as QualifiedName
from .ua_enums import MachineryItemState as MachineryItemState
from .ua_enums import MachineryOperationMode as MachineryOperationMode
from .ua_enums import SkillState as SkillState
from .unit_all import Unit as Unit

__version__ = metadata.version("OpenSMI-Core")
