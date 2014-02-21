import sys
import os
import re
from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
README = unicode(open(os.path.join(here, 'README.rst')).read(), 'utf-8')
CHANGES = unicode(open(os.path.join(here, 'CHANGES.rst')).read(), 'utf-8')
versionfile = open(os.path.join(here, "coaster", "_version.py")).read()

mo = re.search(r"^__version__\s*=\s*['\"]([^'\"]*)['\"]", versionfile, re.M)
if mo:
    version = mo.group(1)
else:
    raise RuntimeError("Unable to find version string in coaster/_version.py.")


requires = [
    'Flask',
    'werkzeug',
    'BeautifulSoup',
    'simplejson',
    'Flask-Assets',
    'semantic_version',
    'pytz',
    'markdown',
    'Pygments',
    'docflow',
    'sqlalchemy',
    'Flask-SQLAlchemy',
    'Flask-Script==0.5.3',
    'Flask-Alembic',
    ]

if sys.version_info[0:2] < (2, 7):
    requires.append('ordereddict')


setup(name='coaster',
    version=version,
    description='Coaster for Flask',
    long_description=README + '\n\n' + CHANGES,
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
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
    packages=['coaster'],
    include_package_data=True,
    zip_safe=True,
    test_suite='tests',
    install_requires=requires,
    dependency_links=[
        "https://github.com/jace/flask-alembic/archive/master.zip#egg=Flask-Alembic-0.1",
        ]
    )
