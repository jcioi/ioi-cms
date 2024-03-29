#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2015-2016 William Di Luigi <williamdiluigi@gmail.com>
# Copyright © 2016-2017 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2017 Myungwoo Chun <mc.tamaki@gmail.com>
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

"""Utility to export submissions to a folder.

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from future.builtins.disabled import *  # noqa
from future.builtins import *  # noqa
from six import iteritems

import argparse
import io
import logging
import os
import sys

from cms import utf8_decoder
from cms.db import Dataset, File, Participation, SessionGen, \
    Submission, SubmissionResult, Task, User
from cms.db.filecacher import FileCacher
from cms.grading import languagemanager


logger = logging.getLogger(__name__)


# Templates for the comment at the beginning of the exported submission.
# Note that output only submissions will contain an initial, C-style formatted
# comment, so to recover the original file one will need to use tail -n +6.
_RAW_TEMPLATE_DATA = """
* user:  %s
* fname: %s
* lname: %s
* task:  %s
* score: %s
* date:  %s
"""
TEMPLATE = {
    ".c": "/**%s*/\n" % _RAW_TEMPLATE_DATA,
    ".pas": "(**%s*)\n" % _RAW_TEMPLATE_DATA,
    ".py": "\"\"\"%s\"\"\"\n" % _RAW_TEMPLATE_DATA,
    ".php": "<?php\n/**%s*/\n?>" % _RAW_TEMPLATE_DATA,
    ".hs": "{-%s-}\n" % _RAW_TEMPLATE_DATA,
}
TEMPLATE[".cpp"] = TEMPLATE[".c"]
TEMPLATE[".java"] = TEMPLATE[".c"]
TEMPLATE[".txt"] = TEMPLATE[".c"]


def filter_top_scoring(results, unique):
    """Filter results keeping only the top scoring submissions for each user
    and task

    results ([Submission]): the starting list of submissions
    unique (bool): if True, keep only the first top-scoring submission

    return ([Submission]): the filtered submissions

    """
    usertask = {}
    for row in results:
        key = (row[6], row[10])  # u_id, t_id
        value = (-row[3], row[2], row)  # sr_score, s_timestamp
        if unique:
            if key not in usertask or usertask[key][0] > value:
                usertask[key] = [value]
        else:
            if key not in usertask or usertask[key][0][0] > value[0]:
                usertask[key] = [value]
            elif usertask[key][0][0] == value[0]:
                usertask[key].append(value)

    results = []
    for key, values in iteritems(usertask):
        for value in values:
            results.append(value[2])  # the "old" row

    return results


def main():
    """Parse arguments and launch process.

    """
    parser = argparse.ArgumentParser(
        description="Export CMS submissions to a folder.\n",
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-c", "--contest-id", action="store", type=int,
                        help="id of contest (default: all contests)")
    parser.add_argument("-t", "--task-id", action="store", type=int,
                        help="id of task (default: all tasks)")
    parser.add_argument("-u", "--user-id", action="store", type=int,
                        help="id of user (default: all users)")
    parser.add_argument("-s", "--submission-id", action="store", type=int,
                        help="id of submission (default: all submissions)")
    parser.add_argument("--utf8", action="store_true",
                        help="if set, the files will be encoded in utf8"
                             " when possible")
    parser.add_argument("--add-info", action="store_true",
                        help="if set, information on the submission will"
                             " be added in the first lines of each file")
    parser.add_argument("--min-score", action="store", type=float,
                        help="ignore submissions which scored strictly"
                             " less than this (default: 0.0)",
                        default=0.0)
    parser.add_argument("--filename", action="store", type=utf8_decoder,
                        help="the filename format to use\n"
                             "Variables:\n"
                             "  id: submission id\n"
                             "  file: filename without extension\n"
                             "  ext: filename extension\n"
                             "  time: submission timestamp\n"
                             "  user: username\n"
                             "  task: taskname\n"
                             "  score: raw score\n"
                             " (default: {id}.{file}{ext})",
                        default="{id}.{file}{ext}")
    parser.add_argument("output_dir", action="store", type=utf8_decoder,
                        help="directory where to save the submissions")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="if set, confirmation will not be shown")

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--unique", action="store_true",
                       help="if set, only the earliest best submission"
                            " will be exported for each (user, task)")
    group.add_argument("--best", action="store_true",
                       help="if set, only the best submissions will be"
                            " exported for each (user, task)")

    args = parser.parse_args()

    if not os.path.exists(args.output_dir):
        os.mkdir(args.output_dir)
    if not os.path.isdir(args.output_dir):
        logger.critical("The output-dir parameter must point to a directory")
        return 1

    cacher = FileCacher()

    with SessionGen() as session:
        q = session.query(Submission)\
            .join(Submission.task)\
            .join(Submission.files)\
            .join(Submission.results)\
            .join(SubmissionResult.dataset)\
            .join(Submission.participation)\
            .join(Participation.user)\
            .filter(Dataset.id == Task.active_dataset_id)\
            .filter(SubmissionResult.score >= args.min_score)\
            .with_entities(Submission.id, Submission.language,
                           Submission.timestamp,
                           SubmissionResult.score,
                           File.filename, File.digest,
                           User.id, User.username, User.first_name,
                           User.last_name,
                           Task.id, Task.name)

        if args.contest_id:
            q = q.filter(Participation.contest_id == args.contest_id)

        if args.task_id:
            q = q.filter(Submission.task_id == args.task_id)

        if args.user_id:
            q = q.filter(Participation.user_id == args.user_id)

        if args.submission_id:
            q = q.filter(Submission.id == args.submission_id)

        results = q.all()

        if args.unique or args.best:
            results = filter_top_scoring(results, args.unique)

        print("%s file(s) will be created." % len(results))
        if not args.yes and (input("Continue? [Y/n] ").strip().lower() not in ["y", ""]):
            return 0

        done = 0
        for row in results:
            s_id, s_language, s_timestamp, sr_score, f_filename, f_digest, \
                u_id, u_name, u_fname, u_lname, t_id, t_name = row

            timef = s_timestamp.strftime('%Y%m%dT%H%M%S')

            ext = languagemanager.get_language(s_language).source_extension \
                if s_language else '.txt'
            filename_base, filename_ext = os.path.splitext(
                f_filename.replace('.%l', ext)
            )

            # "name" is a deprecated specifier with the same meaning as "file"
            filename = args.filename.format(id=s_id, file=filename_base,
                                            name=filename_base,
                                            ext=filename_ext,
                                            time=timef, user=u_name,
                                            task=t_name,
                                            score=sr_score)
            filename = os.path.join(args.output_dir, filename)
            if os.path.exists(filename):
                logger.warning("Skipping file '%s' because it already exists",
                               filename)
                continue
            filedir = os.path.dirname(filename)
            if not os.path.exists(filedir):
                os.makedirs(filedir)
            if not os.path.isdir(filedir):
                logger.warning("%s is not a directory, skipped.", filedir)
                continue

            if not (args.utf8 or args.add_info):

                cacher.get_file_to_path(f_digest, filename)

            else:

                content_bytes = cacher.get_file_content(f_digest)

                if args.utf8:
                    try:
                        content = utf8_decoder(content_bytes)
                        content_bytes = content.encode("utf-8")
                    except TypeError:
                        logger.critical("Could not guess encoding of file "
                                        "'%s'. Aborting.",
                                        filename)
                        return 1

                if args.add_info:

                    template_str = TEMPLATE[ext] % (
                        u_name,
                        u_fname,
                        u_lname,
                        t_name,
                        sr_score,
                        s_timestamp
                    )
                    template_bytes = template_str.encode("utf-8")

                    content_bytes = template_bytes + content_bytes

                with io.open(filename, 'wb') as f_out:
                    f_out.write(content_bytes)

            done += 1
            print(done, "/", len(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
