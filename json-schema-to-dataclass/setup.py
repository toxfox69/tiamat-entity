from setuptools import setup

setup(
    name="schema-to-dataclass",
    version="1.0.0",
    description="JSON Schema → Python Dataclass Generator",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="TIAMAT / ENERGENAI LLC",
    python_requires=">=3.10",
    py_modules=["schema_to_dataclass"],
    entry_points={
        "console_scripts": [
            "schema_to_dataclass=schema_to_dataclass:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Topic :: Software Development :: Code Generators",
    ],
)
