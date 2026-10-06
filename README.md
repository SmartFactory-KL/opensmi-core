![OpenSMI Logo](https://smartfactory.de/wp-content/uploads/2026/09/Logo_OpenSMI.png)

[![Docs](https://img.shields.io/badge/docs-online-blue)](https://smartfactory-kl.github.io/opensmi-core/)
[![PyPI version](https://img.shields.io/pypi/v/opensmi-core.svg)](https://pypi.org/project/opensmi-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/opensmi-core.svg)](https://pypi.org/project/opensmi-core/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

# OpenSMI Core

Core functionality for other OpenSMI packages such as:

- [OpenSMI Client](https://github.com/SmartFactory-KL/opensmi-client)
- [OpenSMI Server](https://github.com/SmartFactory-KL/opensmi-server)

## Features

- (Nested) Configuration parsing into dataclasses from TOML files (See [config.py](src/opensmi/core/config.py))
- Lifecycle management via mixin and `@lifecycle` decorators, allowing explicit ordering 
  (See [lifecycle_mixin.py](src/opensmi/core/lifecycle_mixin.py))
- Simple callbacks via `Signal` (similar to [aiosignal](https://pypi.org/project/aiosignal/), but without freezing)
  (See [signal.py](src/opensmi/core/signal.py))
- [asyncua](https://pypi.org/project/asyncua/) (OPC UA) helpers 
  - Node helper functions (See [ua_node_util.py](src/opensmi/core/ua_node_util.py))
  - SubscriptionManager (See [subscription_manager.py](src/opensmi/core/subscription_manager.py))
- Enums for OpenSMI machine, component and skill states
- All [UN/CEFACT-Rec20](https://unece.org/trade/documents/2021/06/uncefact-rec20-0) units as a type-checkable enum. 
  (See [unit_all.py](src/opensmi/core/unit_all.py))
- [Structured Logging](https://pypi.org/project/structlog/) configuration (See [logging.py](src/opensmi/core/logging.py))

> [!warning]
> This library is currently pre-1.0 — expect refactoring outside above-mentioned functionality.

## Installation

Requires Python 3.11+.

```bash
pip install opensmi-core
```

## Project Status

OpenSMI began as a closed-source project at [SmartFactory-KL](https://smartfactory.de/), in active use in our model
factory since 2020. Its OPC UA information model has been refined across many iterations of research and
demonstrator use. The framework was open-sourced in 2026 following substantial refactoring and cleanup.

## License

[MIT License](LICENSE)
