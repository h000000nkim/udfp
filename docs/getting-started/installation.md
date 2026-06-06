# Installation

## Requirements

- Python 3.11 or higher

## Install from PyPI

=== "Basic"

    ```bash
    pip install udfp
    ```

=== "With MCP server"

    ```bash
    pip install udfp[mcp]
    ```

=== "Development"

    ```bash
    pip install udfp[dev]
    ```

## Dependencies

UDF installs the following core dependencies automatically:

| Package | Purpose |
|---------|---------|
| `pydantic>=2.0` | Data validation and schema models |
| `olefile>=0.46` | HWP (OLE2 Compound File) parsing |
| `pdfminer.six` | PDF text extraction |
| `pypdf>=3.0` | PDF page handling |
| `lxml>=4.9.0` | XML/HWPX/DOCX parsing |

## Optional Dependencies

| Group | Packages | Purpose |
|-------|----------|---------|
| `mcp` | `mcp>=1.1.3` | MCP server for Claude/LLM integration |
| `dev` | pytest, ruff, mypy | Development and testing |
| `screenshot` | selenium, Pillow | Document screenshot capture |

## Verify Installation

```python
import udf
print(udf.__version__)
```

```bash
udf info
```

## Development Setup

```bash
git clone https://github.com/h000000nkim/udfp.git
cd udfp
pip install -e ".[dev]"
```

Run the test suite to confirm everything works:

```bash
pytest
```
