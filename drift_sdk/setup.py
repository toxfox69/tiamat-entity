from setuptools import setup, find_packages

setup(
    name="tiamat-drift",
    version="0.1.0",
    author="TIAMAT",
    description="Production ML drift detection SDK",
    url="https://tiamat.live",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=["requests>=2.28.0", "numpy>=1.21.0", "scipy>=1.7.0"],
)
