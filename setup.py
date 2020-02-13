# -*- coding: utf-8 -*-

import os
import re
import sys

from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.rst')) as f:
    README = f.read()
with open(os.path.join(here, 'CHANGES.rst')) as f:
    CHANGES = f.read()
with open(os.path.join(here, "coaster", "_version.py")) as f:
    versionfile = f.read()

mo = re.search(r"^__version__\s*=\s*['\"]([^'\"]*)['\"]", versionfile, re.M)
if mo:
    version = mo.group(1)
else:
    raise RuntimeError("Unable to find version string in coaster/_version.py.")

PY2 = sys.version_info[0] == 2

requires = [
    'six>=1.13.0',
    'nltk>=3.0',
    'shortuuid',
    'isoweek',
    'UgliPyJS',
    'PyExecJS',
    'Flask-Assets',
    'webassets',
    'Flask-Migrate',
    'Flask-Script',
    'Flask-SQLAlchemy',
    'sqlalchemy-utils',
    'SQLAlchemy>=1.0.9',
    'psycopg2',
    'docflow>=0.3.2',
    'html2text==2019.8.11;python_version<"3"',
    'html2text>2019.8.11;python_version>"2.7"',
    'bcrypt',
    'unidecode',
    'tldextract',
    'Pygments',
    'bleach',
    'html5lib>=0.999999999',
    'Markdown>=3.1.0',
    'pymdown-extensions>=6.0',
    'pytz',
    'semantic_version>=2.8.0',
    'simplejson',
    'werkzeug',
    'markupsafe',
    'blinker',
    'Flask>=1.0',
    'furl',
    'iso8601',
    'Jinja2',
]

if PY2:
    requires.remove('Jinja2')
    requires.remove('Markdown>=3.1.0')
    requires.remove('pymdown-extensions>=6.0')
    requires.extend(
        ['PySqlite', 'Jinja2<3.0', 'Markdown<=3.2.0', 'pymdown-extensions==6.2.0']
    )

setup(
    name='coaster',
    version=version,
    description='Coaster for Flask',
    long_description=README + '\n\n' + CHANGES,
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Development Status :: 3 - Alpha",
        "Topic :: Software Development :: Libraries",
    ],
    author='Kiran Jonnalagadda',
    author_email='kiran@hasgeek.com',
    url='https://github.com/hasgeek/coaster',
    keywords='coaster',
    packages=['coaster', 'coaster.utils', 'coaster.sqlalchemy', 'coaster.views'],
    include_package_data=True,
    zip_safe=False,
    test_suite='tests',
    install_requires=requires,
)
