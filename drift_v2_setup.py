"""
setup.py for tiamat-drift v2 SDK

Install from local source:
    pip install -e /root/.automaton/

Install from PyPI (when published):
    pip install tiamat-drift

Usage after install:
    from drift_v2_sdk import DriftMonitor, create_monitor
"""

from setuptools import setup

setup(
    name="tiamat-drift",
    version="2.0.0",
    description="TIAMAT Drift Monitor SDK — real-time ML model drift detection via KS test",
    long_description=open("drift_v2_sdk.py").read().split('"""')[1].strip(),
    long_description_content_type="text/plain",
    author="TIAMAT",
    author_email="tiamat.entity.prime@gmail.com",
    url="https://tiamat.live/drift",
    project_urls={
        "Dashboard":     "https://tiamat.live/drift/dashboard",
        "Documentation": "https://tiamat.live/docs",
        "Source":        "https://github.com/toxfox69/tiamat-entity",
    },
    py_modules=["drift_v2_sdk"],
    python_requires=">=3.8",
    install_requires=[
        "scipy>=1.7.0",
        "numpy>=1.21.0",
        "requests>=2.25.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "torch>=2.0",
            "tensorflow>=2.10",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords=[
        "drift detection", "machine learning", "mlops", "monitoring",
        "kolmogorov smirnov", "data drift", "concept drift", "model monitoring",
    ],
    entry_points={
        "console_scripts": [
            "tiamat-drift=drift_v2_sdk:_cli_entry",
        ],
    },
)
