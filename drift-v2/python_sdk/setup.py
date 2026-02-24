"""Setup for tiamat-drift Python SDK"""

from setuptools import setup, find_packages

setup(
    name="tiamat-drift",
    version="2.0.0",
    description="Production ML drift monitoring for PyTorch and TensorFlow",
    author="TIAMAT",
    author_email="tiamat.entity.prime@gmail.com",
    url="https://tiamat.live/drift",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28.0",
        "numpy>=1.21.0",
        "scipy>=1.7.0"
    ],
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence"
    ]
)
