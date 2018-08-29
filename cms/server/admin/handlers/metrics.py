#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2018 wafrelka <wafrelka@gmail.com>
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

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from future.builtins.disabled import *  # noqa
from future.builtins import *  # noqa

import logging

from sqlalchemy import func, not_

from cms.server import CommonRequestHandler
from cms.db import User, Contest, Task, Submission, Participation


logger = logging.getLogger(__name__)


class MetricsHandler(CommonRequestHandler):

    def get(self):

        metrics = {}
        descs = {}

        sub_full_query = self.sql_session.query(User.username, Contest.name, Task.name, func.count(Submission.id))\
            .select_from(Participation)\
            .filter(not_(Participation.hidden))\
            .join(User, User.id == Participation.user_id)\
            .join(Contest, Contest.id == Participation.contest_id)\
            .join(Submission, Submission.participation_id == Participation.id)\
            .join(Task, Task.id == Submission.task_id)\
            .group_by(User.username, Contest.name, Task.name)

        sub_official_counts = sub_full_query.filter(Submission.official).all()
        sub_unofficial_counts = sub_full_query.filter(not_(Submission.official)).all()

        descs['submissions_total'] = ('counter', None)
        metrics['submissions_total'] = {}
        for cs, status in [(sub_official_counts, 'official'), (sub_unofficial_counts, 'unofficial')]:
            for c in cs:
                uname, cname, tname, count = c
                metrics['submissions_total'][(('contest', cname), ('task', tname), ('user', uname), ('status', status))] = count

        for metric_key, metric_values in metrics.items():

            if metric_key in descs:
                metric_type, metric_help = descs[metric_key]
                if metric_help is not None:
                    self.write('# HELP cms_{} {}\n'.format(metric_key, metric_help))
                self.write('# TYPE cms_{} {}\n'.format(metric_key, metric_type))

            for labels, value in metric_values.items():
                if labels:
                    kvs_list = map(lambda kv: '{}="{}"'.format(kv[0], kv[1]), labels)
                    self.write('cms_{}{{{}}} {}\n'.format(metric_key, ','.join(kvs_list), value))
                else:
                    self.write('cms_{} {}\n'.format(metric_key, value))

        self.set_header('Content-Type', 'text/plain')
