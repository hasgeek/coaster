import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = unicode(open(os.path.join(here, 'README.rst')).read(), 'utf-8')
CHANGES = unicode(open(os.path.join(here, 'CHANGES.rst')).read(), 'utf-8')

requires = [
    'Flask',
    'BeautifulSoup'
    ]

setup(name='coaster',
      version='0.3.6',
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
      packages=find_packages(),
      include_package_data=True,
      zip_safe=True,
      test_suite='tests',
      install_requires=requires,
      )
