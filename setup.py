# -*- coding: utf-8 -*-

import os
import re

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

requires = [
    'bcrypt',
    'bleach',
    'blinker',
    'docflow>=0.3.2',
    'Flask-Assets',
    'Flask-Migrate',
    'Flask-Script',
    'Flask-SQLAlchemy',
    'Flask>=1.0',
    'furl',
    'html2text==2019.8.11;python_version<"3"',
    'html2text>2019.8.11;python_version>"2.7"',
    'html5lib>=0.999999999',
    'iso8601',
    'isoweek',
    'Jinja2<=2.11.1;python_version<="2.7"',
    'Jinja2>2.11.1;python_version>="3.6"',
    'Markdown>=3.2.0;python_version>="3.5"',
    'Markdown<3.2.0;python_version<="2.7"',
    'markupsafe',
    'nltk<=3.4.5;python_version<="2.7"',
    'nltk>=3.4.5;python_version>"2.7"',
    'psycopg2',
    'PyExecJS',
    'Pygments<=2.5.2;python_version<"3.5"',
    'Pygments>=2.6.0;python_version>="3.5"',
    'pymdown-extensions>=6.0;python_version>="3.5"',
    'pymdown-extensions==6.2.0;python_version<="2.7"',
    'PySqlite==2.8.3;python_version=="2.7"',
    'pytz',
    'semantic_version>=2.8.0',
    'shortuuid==0.5.0',
    'simplejson',
    'six>=1.13.0',
    'sqlalchemy-utils',
    'SQLAlchemy>=1.0.9',
    'tldextract',
    'UgliPyJS',
    'unidecode',
    'webassets',
    'werkzeug',
]

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
