from setuptools import setup

with open("README.md", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="yaml-json-cli",
    version="1.0.0",
    author="ENERGENAI LLC",
    author_email="tiamat@tiamat.live",
    description="Bidirectional YAML ↔ JSON converter CLI and library",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/toxfox69/yaml-json-cli",
    py_modules=["yaml_json_converter"],
    python_requires=">=3.8",
    install_requires=[
        "pyyaml>=6.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "yaml-json-cli=yaml_json_converter:main",
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Utilities",
        "Topic :: Text Processing :: Markup",
        "Environment :: Console",
    ],
    keywords="yaml json converter cli data transformation",
    license="MIT",
    project_urls={
        "Bug Tracker": "https://github.com/toxfox69/yaml-json-cli/issues",
        "Source": "https://github.com/toxfox69/yaml-json-cli",
    },
)
