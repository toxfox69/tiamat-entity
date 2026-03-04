# yaml-json-cli

Bidirectional **YAML ↔ JSON** converter for the command line and Python API.

```
yaml-json-cli config.yaml -o config.json
yaml-json-cli data.json   -o data.yaml
```

---

## Features

- **YAML → JSON** — full nested-structure preservation, multi-document support
- **JSON → YAML** — block (default) or flow style output
- **Multi-document YAML** (`---` separators) → JSON array
- **YAML anchors & aliases** resolved automatically
- **Date/datetime** values serialized to ISO-8601 strings
- **stdin/stdout** pipeline support
- Configurable indent, sort-keys, encoding
- Zero mandatory dependencies beyond **PyYAML**

---

## Installation

```bash
pip install yaml-json-cli
```

Or from source:

```bash
git clone https://github.com/toxfox69/yaml-json-cli
cd yaml-json-cli
pip install .
```

---

## CLI Usage

```
yaml-json-cli INPUT [-o OUTPUT] [options]

positional arguments:
  INPUT           Input file (.yaml, .yml, or .json)

options:
  -o, --output    Output file (default: stdout)
  --from FORMAT   Force input format: yaml or json
  --indent N      JSON indent width (default: 2)
  --sort-keys     Sort mapping keys in output
  --flow-style    Compact YAML flow style (JSON-like)
  --encoding ENC  File encoding (default: utf-8)
  --version       Show version and exit
  -h, --help      Show help message
```

### Examples

```bash
# YAML → JSON (print to stdout)
yaml-json-cli config.yaml

# YAML → JSON (write to file)
yaml-json-cli config.yaml -o config.json

# JSON → YAML (write to file)
yaml-json-cli data.json -o data.yaml

# JSON → YAML (print to stdout)
yaml-json-cli data.json

# Sort keys in output
yaml-json-cli config.yaml --sort-keys -o config.json

# 4-space JSON indent
yaml-json-cli config.yaml --indent 4 -o config.json

# Compact YAML flow style
yaml-json-cli data.json --flow-style

# Multi-document YAML → JSON array
yaml-json-cli multi.yaml -o out.json

# Force format (useful for stdin or non-standard extensions)
cat config.yaml | yaml-json-cli /dev/stdin --from yaml

# Force JSON input from a .txt file
yaml-json-cli data.txt --from json -o data.yaml
```

---

## Input / Output Examples

### YAML → JSON

**Input** (`config.yaml`):
```yaml
server:
  host: localhost
  port: 8080
database:
  url: postgres://localhost/mydb
  pool_size: 10
features:
  - auth
  - logging
  - metrics
debug: false
```

**Output** (`config.json`):
```json
{
  "server": {
    "host": "localhost",
    "port": 8080
  },
  "database": {
    "url": "postgres://localhost/mydb",
    "pool_size": 10
  },
  "features": [
    "auth",
    "logging",
    "metrics"
  ],
  "debug": false
}
```

---

### JSON → YAML

**Input** (`data.json`):
```json
{
  "users": [
    {"id": 1, "name": "Alice", "active": true},
    {"id": 2, "name": "Bob",   "active": false}
  ]
}
```

**Output** (`data.yaml`):
```yaml
users:
- active: true
  id: 1
  name: Alice
- active: false
  id: 2
  name: Bob
```

---

### Multi-document YAML → JSON array

**Input** (`services.yaml`):
```yaml
name: api
port: 8080
---
name: worker
port: 9090
```

**Output**:
```json
[
  {"name": "api", "port": 8080},
  {"name": "worker", "port": 9090}
]
```

---

## Python API

```python
from yaml_json_converter import yaml_to_json, json_to_yaml

# YAML file → JSON file
data = yaml_to_json("config.yaml", "config.json")

# JSON file → YAML file
data = json_to_yaml("data.json", "data.yaml", sort_keys=True)

# From string (no file I/O)
data = yaml_to_json(text="key: value\n")
data = json_to_yaml(text='{"key": "value"}')

# Options
yaml_to_json(
    "input.yaml",
    "output.json",
    indent=4,
    sort_keys=True,
    encoding="utf-8",
)

json_to_yaml(
    "input.json",
    "output.yaml",
    sort_keys=False,
    default_flow_style=False,
    encoding="utf-8",
)
```

---

## Error Handling

The CLI exits with:

| Code | Meaning |
|------|---------|
| `0`  | Success |
| `1`  | File not found or parse error (message printed to stderr) |
| `2`  | Bad arguments (argparse) |
| `130`| Interrupted (Ctrl-C) |

The library raises:
- `FileNotFoundError` — input file missing
- `ValueError` — malformed YAML or JSON, empty document

---

## Development

```bash
pip install -e ".[dev]"
pytest test_converter.py -v
pytest test_converter.py -v --cov=yaml_json_converter --cov-report=term-missing
```

---

## License

MIT — Copyright © 2026 ENERGENAI LLC
