from setuptools import setup

with open("README.md", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="csv-parquet-cli",
    version="1.0.0",
    author="ENERGENAI LLC",
    author_email="tiamat@tiamat.live",
    description="Convert CSV files to Apache Parquet with compression and metadata",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/toxfox69/csv-parquet-cli",
    py_modules=["csv_parquet_converter"],
    python_requires=">=3.8",
    install_requires=[
        "pyarrow>=12.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "csv-parquet=csv_parquet_converter:main",
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
        "Topic :: Database",
        "Environment :: Console",
    ],
    keywords="csv parquet converter cli apache arrow compression data",
    license="MIT",
    project_urls={
        "Bug Tracker": "https://github.com/toxfox69/csv-parquet-cli/issues",
        "Source": "https://github.com/toxfox69/csv-parquet-cli",
    },
)
