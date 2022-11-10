#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Note: To use the 'upload' functionality of this file, you must:
#   $ pip install twine

import io
import os
import shutil
import sys
from pathlib import Path
from shutil import rmtree
from typing import List
import ccimport
from ccimport.extension import ExtCallback, CCImportBuild, CCImportExtension
from setuptools import Command, find_packages, setup
from setuptools.extension import Extension
from ccimport import compat
import subprocess 
import re 

# Package meta-data.
NAME = 'package'
RELEASE_NAME = NAME
DESCRIPTION = 'sample project for ccimport'
URL = ''
EMAIL = ''
AUTHOR = 'Yan Yan'
REQUIRES_PYTHON = '>=3.7'
VERSION = "0.1.0"

# What packages are required for this module to be executed?
REQUIRED = ["pybind11>=2.6.0"]

# What packages are optional?
EXTRAS = {
    # 'fancy feature': ['django'],
}

# The rest you shouldn't have to touch too much :)
# ------------------------------------------------
# Except, perhaps the License and Trove Classifiers!
# If you do change the License, remember to change the Trove Classifier for that!

here = os.path.abspath(os.path.dirname(__file__))
sys.path.append(str(Path(__file__).parent))

# Import the README and use it as the long-description.
# Note: this will only work if 'README.md' is present in your MANIFEST.in file!
try:
    with io.open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
        long_description = '\n' + f.read()
except FileNotFoundError:
    long_description = DESCRIPTION

# Load the package's __version__.py module as a dictionary.
about = {}
if not VERSION:
    with open('version.txt', 'r') as f:
        version = f.read().strip()
else:
    version = VERSION
cwd = os.path.dirname(os.path.abspath(__file__))

about['__version__'] = version


class UploadCommand(Command):
    """Support setup.py upload."""

    description = 'Build and publish the package.'
    user_options = []

    @staticmethod
    def status(s):
        """Prints things in bold."""
        print('\033[1m{0}\033[0m'.format(s))

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        try:
            self.status('Removing previous builds...')
            rmtree(os.path.join(here, 'dist'))
        except OSError:
            pass

        self.status('Building Source and Wheel (universal) distribution...')
        os.system('{0} setup.py sdist bdist_wheel --universal'.format(
            sys.executable))

        self.status('Uploading the package to PyPI via Twine...')
        os.system('twine upload dist/*')

        self.status('Pushing git tags...')
        os.system('git tag v{0}'.format(about['__version__']))
        os.system('git push --tags')

        sys.exit()

cmdclass = {
    'upload': UploadCommand,
    'build_ext': CCImportBuild,
}
build_meta = ccimport.BuildMeta(includes=[Path(__file__).parent.resolve() / "include"], compiler_to_cflags={
    "g++,clang++,nvcc": ["-DSOME_COMPILE_FLAG"], # linux compilers
    "cl": ["/DSOME_COMPILE_FLAG"], # windows compilers
}, libraries=[], libpaths=[], compiler_to_ldflags={
    "g++,clang++,nvcc": [], # linux linkers
    "link": [], # windows linkers
})


ext_modules: List[Extension] = [
    CCImportExtension("core_cc", ["src/main.cpp"],
                    "package/core_cc", # store location of your library
                    build_meta,
                    std="c++14")
]
# Where the magic happens:
setup(
    name=RELEASE_NAME,
    version=about['__version__'],
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type='text/markdown',
    author=AUTHOR,
    author_email=EMAIL,
    python_requires=REQUIRES_PYTHON,
    url=URL,
    packages=find_packages(exclude=('tests', )),
    # If your package is a single module, use this instead of 'packages':
    # py_modules=['mypackage'],
    entry_points={
        'console_scripts': [],
    },
    install_requires=REQUIRED,
    extras_require=EXTRAS,
    include_package_data=True,
    license='Apache License 2.0',
    classifiers=[
        # Trove classifiers
        # Full list: https://pypi.python.org/pypi?%3Aaction=list_classifiers
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: Implementation :: CPython',
    ],
    # $ setup.py publish support.
    cmdclass=cmdclass,
    ext_modules=ext_modules,
)
