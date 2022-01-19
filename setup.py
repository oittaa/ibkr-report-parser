import os
from setuptools import setup, find_packages  # type: ignore

NAME = "ibkr-report-parser"
PACKAGES = find_packages()

DESCRIPTION = "Interactive Brokers (IBKR) Report Parser for MyTax (vero.fi)"
URL = "https://github.com/oittaa/ibkr-report-parser"
LONG_DESCRIPTION = open(os.path.join(os.path.dirname(__file__), "README.md")).read()

AUTHOR = "Oittaa"
AUTHOR_EMAIL = ""
GITHUB_REF = os.environ.get("GITHUB_REF")
PREFIX = "refs/tags/"

if GITHUB_REF and GITHUB_REF.startswith(PREFIX):
    prefix_len = len(PREFIX)
    VERSION = GITHUB_REF[prefix_len:]
else:
    VERSION = "0.0.0.dev0"

setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    url=URL,
    author=AUTHOR,
    author_email=AUTHOR_EMAIL,
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    keywords=[
        "Interactive Brokers",
        "IBKR",
        "OmaVero",
        "MyTax",
        "vero.fi",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Other Audience",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    scripts=["bin/ibkr-report-parser", "bin/ibkr-report-parser.py"],
    setup_requires=[
        "wheel",
    ],
    install_requires=["flask==2.0.2"],
    extras_require={
        "aws": ["boto3==1.20.38"],
        "docker": ["gunicorn==20.1.0"],
        "gcp": ["google-cloud-storage==2.0.0"],
    },
    python_requires=">=3.7",
)
