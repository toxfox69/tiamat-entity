# csv-json-cli

[![PyPI version](https://badge.fury.io/py/csv-json-cli.svg)](https://pypi.org/project/csv-json-cli/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A zero-dependency command-line tool to convert **CSV → JSON** and **JSON → CSV** bidirectionally.

**Features**

- Automatic type inference: `"42"` → `42`, `"true"` → `true`, `""` → `null`
- Nested JSON → CSV flattening (`user.name`, `tags[0]`)
- Configurable indent, separator, and encoding
- Reads from stdin, writes to stdout — pipeline friendly
- Pure stdlib — no third-party packages required

---

## Installation

### From PyPI

```bash
pip install csv-json-cli
```

### From source

```bash
git clone https://github.com/toxfox69/csv-json-cli.git
cd csv-json-cli
pip install -e .
```

---

## Quick start

```bash
# CSV → JSON (stdout)
csv-json-cli data.csv

# CSV → JSON (file)
csv-json-cli data.csv -o output.json

# JSON → CSV (file)
csv-json-cli data.json -o output.csv

# JSON → CSV (stdout)
csv-json-cli data.json
```

---

## Examples

### 1. CSV → JSON

**Input** (`users.csv`)

```csv
name,age,active,score
Alice,30,true,9.5
Bob,25,false,7.0
Carol,,true,
```

```bash
csv-json-cli users.csv
```

**Output**

```json
[
  {"name": "Alice", "age": 30, "active": true, "score": 9.5},
  {"name": "Bob",   "age": 25, "active": false, "score": 7.0},
  {"name": "Carol", "age": null, "active": true, "score": null}
]
```

### 2. JSON → CSV

**Input** (`orders.json`)

```json
[
  {"id": 1, "product": "Widget", "qty": 3},
  {"id": 2, "product": "Gadget", "qty": 1}
]
```

```bash
csv-json-cli orders.json -o orders.csv
```

**Output** (`orders.csv`)

```csv
id,product,qty
1,Widget,3
2,Gadget,1
```

### 3. Nested JSON → CSV (flattening)

**Input** (`nested.json`)

```json
[
  {
    "user": {"name": "Alice", "role": "admin"},
    "tags": ["python", "devops"],
    "active": true
  }
]
```

```bash
csv-json-cli nested.json -o flat.csv
```

**Output** (`flat.csv`)

```csv
user.name,user.role,tags[0],tags[1],active
Alice,admin,python,devops,True
```

Use `--flatten-sep __` to change the nesting separator:

```bash
csv-json-cli nested.json --flatten-sep __ -o flat.csv
# columns: user__name, user__role, tags[0], tags[1], active
```

### 4. Disable type inference

Keep all CSV values as raw strings:

```bash
csv-json-cli data.csv --no-infer -o output.json
```

### 5. Pipeline usage

```bash
# CSV from stdin → JSON to stdout
cat data.csv | csv-json-cli /dev/stdin --from csv | jq '.[0]'

# Chain: CSV → JSON → filter → back to CSV
csv-json-cli input.csv | jq '[.[] | select(.active == true)]' > filtered.json
csv-json-cli filtered.json -o filtered.csv
```

### 6. Options reference

```
usage: csv-json-cli [-h] [-o OUTPUT] [--from FORMAT] [--indent N]
                    [--no-infer] [--flatten-sep SEP] [--encoding ENC]
                    [--version]
                    INPUT

positional arguments:
  INPUT                  Input file (.csv or .json)

options:
  -o, --output OUTPUT    Output file (default: stdout)
  --from FORMAT          Force format: csv or json
  --indent N             JSON indent width (default: 2)
  --no-infer             Disable type inference; keep CSV values as strings
  --flatten-sep SEP      Separator for nested JSON keys (default: '.')
  --encoding ENC         File encoding (default: utf-8)
  --version              Show version and exit
```

---

## Python API

You can also use the converter as a library:

```python
from csv_json_converter import csv_to_json, json_to_csv, flatten_dict

# CSV → JSON
rows = csv_to_json("data.csv", output_path="data.json", indent=4)

# JSON → CSV
rows = json_to_csv("data.json", output_path="data.csv", flatten_sep=".")

# Flatten a dict directly
flat = flatten_dict({"user": {"name": "Alice", "age": 30}, "tags": ["x", "y"]})
# {'user.name': 'Alice', 'user.age': 30, 'tags[0]': 'x', 'tags[1]': 'y'}
```

---

## Development

```bash
# Clone and install in editable mode with dev deps
git clone https://github.com/toxfox69/csv-json-cli.git
cd csv-json-cli
pip install -e ".[dev]"

# Run tests
pytest test_converter.py -v

# Run tests with coverage
pytest test_converter.py --cov=csv_json_converter --cov-report=term-missing
```

---

## Error handling

| Scenario | Behaviour |
|----------|-----------|
| File not found | `Error: Input file not found: …` + exit 1 |
| Malformed CSV | `Error: Malformed CSV near line N: …` + exit 1 |
| Invalid JSON | `Error: Malformed JSON: …` + exit 1 |
| Empty JSON array | `Error: JSON array is empty — nothing to convert.` + exit 1 |
| Unknown extension | `Error: Cannot detect format …` + exit 2 |

---

## License

MIT © ENERGENAI LLC
