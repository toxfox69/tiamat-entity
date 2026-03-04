"""Tests for schema_to_dataclass — 15 test cases covering all major features."""

import json
import sys
import textwrap
import unittest
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from schema_to_dataclass import (
    DataclassGenerator,
    to_class_name,
    safe_field_name,
    main,
)


class TestHelpers(unittest.TestCase):
    def test_to_class_name_snake_case(self):
        self.assertEqual(to_class_name("user_profile"), "UserProfile")

    def test_to_class_name_kebab(self):
        self.assertEqual(to_class_name("api-response"), "ApiResponse")

    def test_to_class_name_already_pascal(self):
        self.assertEqual(to_class_name("MyModel"), "MyModel")

    def test_to_class_name_leading_digit(self):
        result = to_class_name("3d_model")
        self.assertFalse(result[0].isdigit(), "Class name must not start with digit")

    def test_safe_field_name_keyword(self):
        self.assertEqual(safe_field_name("class"), "field_class")

    def test_safe_field_name_hyphen(self):
        self.assertEqual(safe_field_name("first-name"), "first_name")


class TestScalarTypes(unittest.TestCase):
    def setUp(self):
        self.gen = DataclassGenerator("MyModel")

    def _generate(self, schema):
        return self.gen.generate(schema, "MyModel")

    def test_string_field(self):
        code = self._generate({
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        })
        self.assertIn("name: str", code)

    def test_integer_field(self):
        code = self._generate({
            "type": "object",
            "properties": {"age": {"type": "integer"}},
            "required": ["age"],
        })
        self.assertIn("age: int", code)

    def test_number_field(self):
        code = self._generate({
            "type": "object",
            "properties": {"score": {"type": "number"}},
            "required": ["score"],
        })
        self.assertIn("score: float", code)

    def test_boolean_field(self):
        code = self._generate({
            "type": "object",
            "properties": {"active": {"type": "boolean"}},
            "required": ["active"],
        })
        self.assertIn("active: bool", code)

    def test_all_scalar_types_together(self):
        code = self._generate({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "score": {"type": "number"},
                "active": {"type": "boolean"},
            },
            "required": ["name", "age", "score", "active"],
        })
        self.assertIn("name: str", code)
        self.assertIn("age: int", code)
        self.assertIn("score: float", code)
        self.assertIn("active: bool", code)


class TestOptionalFields(unittest.TestCase):
    def setUp(self):
        self.gen = DataclassGenerator("User")

    def test_optional_field_has_none_default(self):
        code = self.gen.generate({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "bio": {"type": "string"},
            },
            "required": ["name"],
        }, "User")
        self.assertIn("bio: Optional[str] = None", code)
        self.assertIn("from typing import Optional", code)

    def test_required_field_has_no_default(self):
        code = self.gen.generate({
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }, "User")
        # Required field must appear without "= None"
        self.assertIn("name: str", code)
        self.assertNotIn("name: str = None", code)


class TestNestedObjects(unittest.TestCase):
    def setUp(self):
        self.gen = DataclassGenerator()

    def test_nested_object_generates_class(self):
        code = self.gen.generate({
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"},
                        "city": {"type": "string"},
                    },
                }
            },
        }, "Person")
        self.assertIn("class Address:", code)
        self.assertIn("class Person:", code)
        self.assertIn("address: Optional[Address]", code)

    def test_doubly_nested_object(self):
        code = self.gen.generate({
            "type": "object",
            "properties": {
                "company": {
                    "type": "object",
                    "properties": {
                        "hq": {
                            "type": "object",
                            "properties": {"country": {"type": "string"}},
                        }
                    },
                }
            },
        }, "Employee")
        self.assertIn("class Hq:", code)
        self.assertIn("class Company:", code)
        self.assertIn("class Employee:", code)


class TestArrays(unittest.TestCase):
    def setUp(self):
        self.gen = DataclassGenerator()

    def test_array_of_strings(self):
        code = self.gen.generate({
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
            "required": ["tags"],
        }, "Post")
        self.assertIn("tags: List[str]", code)
        self.assertIn("from typing import", code)

    def test_array_of_objects(self):
        code = self.gen.generate({
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                    },
                }
            },
            "required": ["items"],
        }, "Order")
        self.assertIn("List[", code)
        self.assertIn("class Item", code)

    def test_optional_array(self):
        code = self.gen.generate({
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }, "Post")
        self.assertIn("Optional[List[str]]", code)


class TestDocstrings(unittest.TestCase):
    def test_schema_description_in_docstring(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "description": "Represents a user account.",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }, "Account")
        self.assertIn("Represents a user account.", code)

    def test_format_in_docstring(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "properties": {
                "email": {"type": "string", "format": "email"},
            },
            "required": ["email"],
        }, "Contact")
        self.assertIn("email", code)
        self.assertIn("RFC 5322 email address", code)

    def test_constraints_in_docstring(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "properties": {
                "age": {"type": "integer", "minimum": 0, "maximum": 150},
            },
            "required": ["age"],
        }, "Person")
        self.assertIn("minimum=0", code)
        self.assertIn("maximum=150", code)


class TestUnionTypes(unittest.TestCase):
    def test_anyof_with_null(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "properties": {
                "value": {"anyOf": [{"type": "string"}, {"type": "null"}]}
            },
            "required": ["value"],
        }, "Wrapper")
        self.assertIn("Optional[str]", code)

    def test_anyof_multiple_types(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "properties": {
                "id": {"anyOf": [{"type": "string"}, {"type": "integer"}]}
            },
            "required": ["id"],
        }, "Item")
        self.assertIn("Union[", code)

    def test_type_array_with_null(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "properties": {
                "count": {"type": ["integer", "null"]}
            },
            "required": ["count"],
        }, "Stats")
        self.assertIn("Optional[int]", code)


class TestDefinitions(unittest.TestCase):
    def test_definitions_resolved(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "definitions": {
                "Address": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                }
            },
            "properties": {
                "home": {"$ref": "#/definitions/Address"}
            },
        }, "Person")
        self.assertIn("class Address:", code)
        self.assertIn("Optional[Address]", code)

    def test_defs_resolved(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "$defs": {
                "Tag": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                }
            },
            "properties": {
                "tag": {"$ref": "#/$defs/Tag"}
            },
            "required": ["tag"],
        }, "Post")
        self.assertIn("class Tag:", code)
        self.assertIn("tag: Tag", code)


class TestDefaultValues(unittest.TestCase):
    def test_string_default(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": "active"},
            },
            "required": ["status"],
        }, "Record")
        self.assertIn("'active'", code)

    def test_integer_default(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "properties": {
                "retries": {"type": "integer", "default": 3},
            },
            "required": ["retries"],
        }, "Config")
        self.assertIn("= 3", code)


class TestFreeFormDict(unittest.TestCase):
    def test_object_without_properties(self):
        gen = DataclassGenerator()
        code = gen.generate({
            "type": "object",
            "properties": {
                "metadata": {"type": "object"},
            },
        }, "Record")
        self.assertIn("Dict[str, Any]", code)


class TestCLI(unittest.TestCase):
    def test_cli_writes_file(self):
        schema = {
            "type": "object",
            "title": "Widget",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        with TemporaryDirectory() as tmpdir:
            schema_path = Path(tmpdir) / "widget.json"
            schema_path.write_text(json.dumps(schema))
            out_path = Path(tmpdir) / "Widget.py"
            ret = main([str(schema_path), "-o", str(out_path)])
            self.assertEqual(ret, 0)
            self.assertTrue(out_path.exists())
            content = out_path.read_text()
            self.assertIn("class Widget:", content)

    def test_cli_stdout(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "number"}},
            "required": ["x"],
        }
        with TemporaryDirectory() as tmpdir:
            schema_path = Path(tmpdir) / "point.json"
            schema_path.write_text(json.dumps(schema))
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                main([str(schema_path), "--stdout", "-c", "Point"])
            finally:
                sys.stdout = old_stdout
            self.assertIn("class Point:", captured.getvalue())

    def test_cli_infers_class_from_title(self):
        schema = {
            "type": "object",
            "title": "BlogPost",
            "properties": {"title": {"type": "string"}},
        }
        with TemporaryDirectory() as tmpdir:
            schema_path = Path(tmpdir) / "blog.json"
            schema_path.write_text(json.dumps(schema))
            out_path = Path(tmpdir) / "BlogPost.py"
            main([str(schema_path), "-o", str(out_path)])
            self.assertIn("class BlogPost:", out_path.read_text())


class TestOutputIsValidPython(unittest.TestCase):
    """Compile generated code to ensure it's syntactically valid."""

    def _assert_valid_python(self, schema, class_name):
        gen = DataclassGenerator()
        code = gen.generate(schema, class_name)
        try:
            compile(code, "<generated>", "exec")
        except SyntaxError as e:
            self.fail(f"Generated code has syntax error: {e}\n\n{code}")

    def test_simple_schema_is_valid_python(self):
        self._assert_valid_python({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "email": {"type": "string", "format": "email"},
            },
            "required": ["name"],
        }, "User")

    def test_complex_schema_is_valid_python(self):
        self._assert_valid_python({
            "type": "object",
            "description": "E-commerce order",
            "properties": {
                "id": {"type": "integer"},
                "customer": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string", "format": "email"},
                    },
                    "required": ["name", "email"],
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sku": {"type": "string"},
                            "qty": {"type": "integer"},
                            "price": {"type": "number"},
                        },
                        "required": ["sku", "qty", "price"],
                    },
                },
                "status": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                },
            },
            "required": ["id", "customer", "items"],
        }, "Order")


if __name__ == "__main__":
    unittest.main(verbosity=2)
