#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
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

"""This script generates a password for users or participations.

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from future.builtins.disabled import *  # noqa
from future.builtins import *  # noqa

# We enable monkey patching to make many libraries gevent-friendly
# (for instance, urllib3, used by requests)
import gevent.monkey
gevent.monkey.patch_all()  # noqa

import argparse
import datetime
import ipaddress
import logging
import sys

from cms import utf8_decoder
from cms.db import Contest, Participation, SessionGen, Team, User, \
    ask_for_contest
from cmscommon.crypto import build_password, hash_password, generate_random_password

from sqlalchemy.exc import IntegrityError


logger = logging.getLogger(__name__)

def generate_passwords(contest_id, exclude_hidden, exclude_unrestricted, output_path):
    logger.info("Updating passwords...")

    with open(output_path, 'w') as io:
        with SessionGen() as session:
            if contest_id is not None:
                contest = Contest.get_from_id(contest_id, session)
                objects = session.query(Participation).join(User)
                if exclude_unrestricted:
                    objects = objects.filter(Participation.unrestricted == False)
                if exclude_hidden:
                    objects = objects.filter(Participation.hidden == False)
            else:
                objects = session.query(User)

            for obj in objects:
                password = generate_random_password()
                obj.password = build_password(password, 'plaintext')

                username = obj.username if isinstance(obj, User) else obj.user.username
                if contest_id is not None:
                    logger.info("Updating user %s in contest id %d", username, contest.id)
                    io.write("%s,%d,%s\n" % (username, contest.id, password))
                else:
                    logger.info("Updating user %s", username)
                    io.write("%s,%s\n" % (username, password))

            session.commit()

    logger.info("Done.")
    return True


def main():
    """Parse arguments and launch process.

    """
    parser = argparse.ArgumentParser(description="Add a participation to CMS.")
    parser.add_argument("-c", "--contest-id", action="store", type=int,
                        help="id of the contest the users will be attached to")
    parser.add_argument("--exclude-hidden", action="store_true",
                        help="exclude hidden participation")
    parser.add_argument("--exclude-unrestricted", action="store_true",
                        help="exclude unrestricted participation")
    parser.add_argument("-o", "--output", action="store", type=str, default='/dev/null',
                        help="CSV output")


    args = parser.parse_args()

    success = generate_passwords(
        contest_id=args.contest_id,
        exclude_hidden=args.exclude_hidden,
        exclude_unrestricted=args.exclude_unrestricted,
        output_path=args.output,
    )
    return 0 if success is True else 1


if __name__ == "__main__":
    sys.exit(main())
