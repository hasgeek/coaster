import os
import re
from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
CHANGES = open(os.path.join(here, 'CHANGES.rst')).read()
versionfile = open(os.path.join(here, "coaster", "_version.py")).read()

mo = re.search(r"^__version__\s*=\s*['\"]([^'\"]*)['\"]", versionfile, re.M)
if mo:
    version = mo.group(1)
else:
    raise RuntimeError("Unable to find version string in coaster/_version.py.")


requires = [
    'six',
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
    'docflow>=0.3.2',
    'html2text',
    'bcrypt',
    'unidecode',
    'tldextract',
    'Pygments',
    'bleach',
    'html5lib>=0.999999999',
    'markdown>=2.4.1',
    'pytz',
    'semantic_version',
    'simplejson',
    'werkzeug',
    'markupsafe',
    'blinker',
    'Flask>=1.0',
    ]


setup(name='coaster',
    version=version,
    description='Coaster for Flask',
    long_description=README + '\n\n' + CHANGES,
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.6",
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
