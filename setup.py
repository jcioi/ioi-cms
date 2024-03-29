#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2010-2013 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2018 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2013 Luca Wehrstedt <luca.wehrstedt@gmail.com>
# Copyright © 2014 Artem Iglikov <artem.iglikov@gmail.com>
# Copyright © 2015 William Di Luigi <williamdiluigi@gmail.com>
# Copyright © 2016 Myungwoo Chun <mc.tamaki@gmail.com>
# Copyright © 2016 Masaki Hara <ackie.h.gmai@gmail.com>
# Copyright © 2016 Peyman Jabbarzade Ganje <peyman.jabarzade@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Build and installation routines for CMS.

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
# setuptools doesn't seem to like this:
# from __future__ import unicode_literals
from future.builtins.disabled import *  # noqa
from future.builtins import *  # noqa

import io
import re
import os

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py


PACKAGE_DATA = {
    "cms.server": [
        os.path.join("static", "*.*"),
        os.path.join("static", "jq", "*.*"),
        os.path.join("admin", "static", "*.*"),
        os.path.join("admin", "static", "jq", "*.*"),
        os.path.join("admin", "static", "sh", "*.*"),
        os.path.join("admin", "templates", "*.*"),
        os.path.join("admin", "templates", "fragments", "*.*"),
        os.path.join("admin", "templates", "views", "*.*"),
        os.path.join("contest", "static", "*.*"),
        os.path.join("contest", "static", "css", "*.*"),
        os.path.join("contest", "static", "img", "*.*"),
        os.path.join("contest", "static", "img", "mimetypes", "*.*"),
        os.path.join("contest", "static", "js", "*.*"),
        os.path.join("contest", "templates", "*.*"),
    ],
    "cms.service": [
        os.path.join("templates", "printing", "*.*"),
    ],
    "cms.locale": [
        os.path.join("*", "LC_MESSAGES", "*.*"),
    ],
    "cmsranking": [
        os.path.join("static", "img", "*.*"),
        os.path.join("static", "lib", "*.*"),
        os.path.join("static", "*.*"),
    ],
    "cmstestsuite": [
        os.path.join("code", "*.*"),
        os.path.join("tasks", "batch_stdio", "data", "*.*"),
        os.path.join("tasks", "batch_fileio", "data", "*.*"),
        os.path.join("tasks", "batch_fileio_managed", "code", "*"),
        os.path.join("tasks", "batch_fileio_managed", "data", "*.*"),
        os.path.join("tasks", "communication", "code", "*"),
        os.path.join("tasks", "communication", "data", "*.*"),
        os.path.join("tasks", "communication2", "code", "*"),
        os.path.join("tasks", "communication2", "data", "*.*"),
        os.path.join("tasks", "outputonly", "data", "*.*"),
        os.path.join("tasks", "outputonly_comparator", "code", "*"),
        os.path.join("tasks", "outputonly_comparator", "data", "*.*"),
        os.path.join("tasks", "twosteps", "code", "*.*"),
        os.path.join("tasks", "twosteps", "data", "*.*"),
        os.path.join("tasks", "twosteps_comparator", "code", "*"),
        os.path.join("tasks", "twosteps_comparator", "data", "*.*"),
    ],
}


def find_version():
    """Return the version string obtained from cms/__init__.py"""
    path = os.path.join("cms", "__init__.py")
    version_file = io.open(path, "rt", encoding="utf-8").read()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",
                              version_file, re.M)
    if version_match is not None:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")


# We piggyback the translation catalogs compilation onto build_py since
# the po and mofiles will be part of the package data for cms.locale,
# which is collected at this stage.
class build_py_and_l10n(build_py):
    def run(self):
        self.run_command("compile_catalog")
        # Can't use super here as in Py2 it isn't a new-style class.
        build_py.run(self)


setup(
    name="cms",
    version=find_version(),
    author="The CMS development team",
    author_email="contestms@googlegroups.com",
    url="https://github.com/cms-dev/cms",
    download_url="https://github.com/cms-dev/cms/archive/master.tar.gz",
    description="A contest management system and grader "
                "for IOI-like programming competitions",
    packages=find_packages(),
    package_data=PACKAGE_DATA,
    cmdclass={"build_py": build_py_and_l10n},
    scripts=["scripts/cmsLogService",
             "scripts/cmsScoringService",
             "scripts/cmsEvaluationService",
             "scripts/cmsWorker",
             "scripts/cmsResourceService",
             "scripts/cmsChecker",
             "scripts/cmsContestWebServer",
             "scripts/cmsAdminWebServer",
             "scripts/cmsProxyService",
             "scripts/cmsPrintingService",
             "scripts/cmsRankingWebServer",
             "scripts/cmsInitDB",
             "scripts/cmsDropDB"],
    entry_points={
        "console_scripts": [
            "cmsRunTests=cmstestsuite.RunTests:main",
            "cmsAddAdmin=cmscontrib.AddAdmin:main",
            "cmsAddParticipation=cmscontrib.AddParticipation:main",
            "cmsAddStatement=cmscontrib.AddStatement:main",
            "cmsAddSubmission=cmscontrib.AddSubmission:main",
            "cmsAddTeam=cmscontrib.AddTeam:main",
            "cmsAddTestcases=cmscontrib.AddTestcases:main",
            "cmsAddUser=cmscontrib.AddUser:main",
            "cmsCleanFiles=cmscontrib.CleanFiles:main",
            "cmsComputeComplexity=cmscontrib.ComputeComplexity:main",
            "cmsDumpExporter=cmscontrib.DumpExporter:main",
            "cmsDumpImporter=cmscontrib.DumpImporter:main",
            "cmsDumpUpdater=cmscontrib.DumpUpdater:main",
            "cmsExportSubmissions=cmscontrib.ExportSubmissions:main",
            "cmsImportContest=cmscontrib.ImportContest:main",
            "cmsImportDataset=cmscontrib.ImportDataset:main",
            "cmsImportTask=cmscontrib.ImportTask:main",
            "cmsImportTeam=cmscontrib.ImportTeam:main",
            "cmsImportUser=cmscontrib.ImportUser:main",
            "cmsRWSHelper=cmscontrib.RWSHelper:main",
            "cmsRemoveContest=cmscontrib.RemoveContest:main",
            "cmsRemoveParticipation=cmscontrib.RemoveParticipation:main",
            "cmsRemoveStatement=cmscontrib.RemoveStatement:main",
            "cmsRemoveSubmissions=cmscontrib.RemoveSubmissions:main",
            "cmsRemoveTask=cmscontrib.RemoveTask:main",
            "cmsRemoveUser=cmscontrib.RemoveUser:main",
            "cmsSpoolExporter=cmscontrib.SpoolExporter:main",
            "cmsMake=cmstaskenv.cmsMake:main",
        ],
        "cms.grading.tasktypes": [
            "Batch=cms.grading.tasktypes.Batch:Batch",
            "Communication=cms.grading.tasktypes.Communication:Communication",
            "OutputOnly=cms.grading.tasktypes.OutputOnly:OutputOnly",
            "TwoSteps=cms.grading.tasktypes.TwoSteps:TwoSteps",
        ],
        "cms.grading.scoretypes": [
            "Sum=cms.grading.scoretypes.Sum:Sum",
            "GroupMin=cms.grading.scoretypes.GroupMin:GroupMin",
            "GroupMul=cms.grading.scoretypes.GroupMul:GroupMul",
            "GroupThreshold=cms.grading.scoretypes.GroupThreshold:GroupThreshold",
            "GroupMinTruncation=cms.grading.scoretypes.GroupMinTruncation:GroupMinTruncation",
        ],
        "cms.grading.languages": [
            "C++14 / g++=cms.grading.languages.cpp14_gpp:Cpp14Gpp",
            "C++11 / g++=cms.grading.languages.cpp11_gpp:Cpp11Gpp",
            "C11 / gcc=cms.grading.languages.c11_gcc:C11Gcc",
            "C# / Mono=cms.grading.languages.csharp_mono:CSharpMono",
            "Haskell / ghc=cms.grading.languages.haskell_ghc:HaskellGhc",
            "Java 1.4 / gcj=cms.grading.languages.java14_gcj:Java14Gcj",
            "Java / JDK=cms.grading.languages.java_jdk:JavaJDK",
            "Pascal / fpc=cms.grading.languages.pascal_fpc:PascalFpc",
            "PHP=cms.grading.languages.php:Php",
            "Python 2 / CPython=cms.grading.languages.python2_cpython:Python2CPython",
            "Python 3 / CPython=cms.grading.languages.python3_cpython:Python3CPython",
            "Rust=cms.grading.languages.rust:Rust",
        ],
    },
    keywords="ioi programming contest grader management system",
    license="Affero General Public License v3",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Natural Language :: English",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.6",
        "License :: OSI Approved :: "
        "GNU Affero General Public License v3",
    ]
)
