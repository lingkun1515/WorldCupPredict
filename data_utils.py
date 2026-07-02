"""Data loading utilities with validation."""
import json
import os
import logging

logger = logging.getLogger("wcp")


def load_json_validated(path, schema=None, default=None):
    """Load a JSON file with validation and error handling.

    Returns default on any error (missing file, corrupt JSON, schema mismatch).
    """
    if default is None:
        default = {}
    if not os.path.exists(path):
        logger.warning("File not found: %s", path)
        return default
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error("Corrupted JSON in %s: %s", path, e)
        return default
    except OSError as e:
        logger.error("Cannot read %s: %s", path, e)
        return default
    if schema and not _validate_schema(data, schema):
        logger.error("Schema validation failed for %s", path)
        return default
    return data


def _validate_schema(data, schema):
    """Simple structural validation (check types/keys)."""
    if isinstance(schema, type):
        return isinstance(data, schema)
    if isinstance(schema, dict) and isinstance(data, dict):
        return all(k in data and _validate_schema(data[k], v) for k, v in schema.items())
    if isinstance(schema, list) and isinstance(data, list):
        if not schema:
            return True
        return all(_validate_schema(item, schema[0]) for item in data)
    return True
