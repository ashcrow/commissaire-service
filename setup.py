#!/usr/bin/env python
#
# Copyright (C) 2016  Red Hat, Inc
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Source build and installation script.
"""

import pip

from setuptools import setup, find_packages


def extract_names(filename):
    names = ''
    with open(filename, 'r') as m:
        names = ', '.join([x.strip() for x in m.readlines()])
    return names


def extract_requirements(filename):
    requirements = []
    for x in pip.req.parse_requirements(
            filename, session=pip.download.PipSession()):
        if x.req:
            requirements.append(str(x.req))
        elif x.link:
            print('\nIgnoring {} ({})'.format(x.link.url, x.comes_from))
            print('To install it run: pip install {}\n'.format(x.link.url))
    return requirements


install_requires = extract_requirements('requirements.txt')
test_require = extract_requirements('test-requirements.txt')


setup(
    name='commissaire_service',
    version='0.0.1',
    description='Commissaire Service Library',
    author=extract_names('CONTRIBUTORS'),
    maintainer=extract_names('MAINTAINERS'),
    url='https://github.com/ashcrow/commissaire-service',
    license="GPLv3+",

    install_requires=install_requires,
    tests_require=test_require,
    package_dir={'': 'src'},
    packages=find_packages('src'),
    entry_points={
        'console_scripts': [
            ('commissaire-storage-service = '
             'commissaire_service.storage:main'),
            ('commissaire-investigator-service = '
             'commissaire_service.investigator:main'),
        ],
    }
)
