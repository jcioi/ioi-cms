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

"""Load participation data from JSON (this script is idempotent)

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
import json

from cms import utf8_decoder
from cms.db import Contest, Participation, SessionGen, Team, User, \
    ask_for_contest
from cmscommon.crypto import build_password, hash_password, generate_random_password

from sqlalchemy.exc import IntegrityError



logger = logging.getLogger(__name__)

def load_participations(path):
    logger.info("Loading...")
    with open(path, 'r') as io:
        data = json.load(io)

    participations = data['participations']
    with SessionGen() as session:
        for entry in participations:
            logger.info('Loading: %s' % (entry))
            contest = Contest.get_from_id(entry['contest_id'], session)
            if contest is None:
                logger.error("  Contest ID %d not found" % (entry['contest_id']))
                session.rollback()
                return False

            userdata = entry['user']
            user = session.query(User).filter(User.username == userdata['username']).first()
            if user is None:
                user = User(username=userdata['username'], first_name=userdata['first_name'], last_name=userdata['last_name'], password=build_password(generate_random_password()))
                logger.info('  Creating new user: %s' % (user.username))
                session.add(user)
            else:
                logger.info('  Using existing user: %s (id=%d)' % (user.username, user.id))


            if 'plaintext_password' in userdata:
                logger.info('  * password')
                user.first_name = build_password(userdata['plaintext_password'], 'plaintext')

            if 'first_name' in userdata:
                logger.info('  * first_name: %s' % (userdata['first_name']))
                user.first_name = userdata['first_name']
            if 'last_name' in userdata:
                logger.info('  * last_name: %s' % (userdata['last_name']))
                user.last_name = userdata['last_name']

            if 'team' in userdata:
                team = session.query(Team).filter(Team.code == userdata['team']['code']).first()
                if team is None:
                    team = Team(code=userdata['team']['code'], name=userdata['team']['name'])
                    logger.info('  Creating new team: %s' % (team.code))
                    session.add(team)
                else:
                    logger.info('  Using existing team: %s' % (team.code))
                if 'name' in userdata['team']:
                    logger.info('  * name: %s' % (userdata['team']['name']))
                    team.name = userdata['team']['name']
                user.team = team

            participation = session.query(Participation).join(Participation.user).filter(Participation.contest == contest).filter(User.username == user.username).first()
            if participation is None:
                participation = Participation(user=user, contest=contest)
                logger.info('  Creating new participation for contest_id=%d user=%s' % (contest.id, user.username))
                session.add(participation)
            else:
                logger.info('  Updating participation: id=%d contest_id=%d user=%s' % (participation.id, participation.contest_id, participation.user.username))

            if 'plaintext_password' in entry:
                logger.info('  * plaintext_password')
                participation.password = build_password(entry['plaintext_password'], 'plaintext')
            if 'ip' in entry:
                logger.info('  * ip: %s' % (entry['ip']))
                participation.ip = [ipaddress.ip_network(entry['ip'])]
            if 'delay_time' in entry:
                logger.info('  * delay_time: %d' % (entry['delay_time']))
                participation.delay_time = datetime.timedelta(seconds=entry['delay_time'])
            if 'extra_time' in entry:
                logger.info('  * extra_time: %d' % (entry['extra_time']))
                participation.extra_time = datetime.timedelta(seconds=entry['extra_time'])
            if 'hidden' in entry:
                logger.info('  * hidden: %s' % (entry['hidden']))
                participation.hidden = entry['hidden']
            if 'unrestricted' in entry:
                logger.info('  * unrestricted: %s' % (entry['unrestricted']))
                participation.unrestricted = entry['unrestricted']

        session.commit()

    logger.info("Done.")
    return True


def main():
    """Parse arguments and launch process.

    """
    parser = argparse.ArgumentParser(description="Load participations into CMS.")
    parser.add_argument(
        "target",
        action="store", type=utf8_decoder, nargs="?",
        help="target JSON file."
    )
    args = parser.parse_args()

    success = load_participations(
        path=args.target,
    )
    return 0 if success is True else 1


if __name__ == "__main__":
    sys.exit(main())
