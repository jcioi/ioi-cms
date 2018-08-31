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
import traceback

from sqlalchemy import func, not_

from cms.service import EvaluationService
from cms.server import CommonRequestHandler
from cms.db import User, Contest, Task, Submission, Participation, Dataset, SubmissionResult, Question, Team, Evaluation


logger = logging.getLogger(__name__)

def filter_none(items):
    return list(filter(lambda kv: (kv[1] is not None), items))
def get_dataset_status(is_live, autojudge):
    if is_live:
        return 'live'
    return 'active' if autojudge else 'inactive'

def compute_contest_metrics(sql_session):

    metrics = {}
    descs = {}

    sub_full_query = sql_session.query(Contest.name, Task.name, Team.code, User.username, func.count(Submission.id))\
        .select_from(Participation)\
        .filter(not_(Participation.hidden))\
        .outerjoin(Team, Team.id == Participation.team_id)\
        .join(User, User.id == Participation.user_id)\
        .join(Contest, Contest.id == Participation.contest_id)\
        .join(Submission, Submission.participation_id == Participation.id)\
        .join(Task, Task.id == Submission.task_id)\
        .group_by(Contest.id, Task.id, Team.id, User.id)

    sub_official_counts = sub_full_query.filter(Submission.official).all()
    sub_unofficial_counts = sub_full_query.filter(not_(Submission.official)).all()

    descs['submissions_total'] = ('gauge', 'status = official | unofficial')
    metrics['submissions_total'] = {}
    for cs, status in [(sub_official_counts, 'official'), (sub_unofficial_counts, 'unofficial')]:
        for c in cs:
            cname, taskname, teamname, uname, count = c
            key = (('contest', cname), ('task', taskname), ('team', teamname), ('user', uname), ('status', status))
            metrics['submissions_total'][key] = count

    res_full_query = sql_session.query(
        Contest.name, Task.name, Team.code, User.username, Dataset.description,
        Dataset.id == Task.active_dataset_id, Dataset.autojudge, func.count(SubmissionResult.submission_id))\
        .select_from(Participation)\
        .filter(not_(Participation.hidden))\
        .outerjoin(Team, Team.id == Participation.team_id)\
        .join(User, User.id == Participation.user_id)\
        .join(Contest, Contest.id == Participation.contest_id)\
        .join(Submission, Submission.participation_id == Participation.id)\
        .join(Task, Task.id == Submission.task_id)\
        .join(SubmissionResult, SubmissionResult.submission_id == Submission.id)\
        .join(Dataset, Dataset.id == SubmissionResult.dataset_id)\
        .group_by(Contest.id, Task.id, Team.id, User.id, Dataset.id)

    res_compiling_query = res_full_query.filter(not_(SubmissionResult.filter_compiled()))
    res_evaluating_query = res_full_query.filter(
        SubmissionResult.filter_compilation_succeeded(),
        not_(SubmissionResult.filter_evaluated()))
    res_evaluated_query = res_full_query.filter(
        SubmissionResult.filter_compilation_succeeded(),
        SubmissionResult.filter_evaluated())

    res_compiling_ok = res_compiling_query.filter(
        SubmissionResult.compilation_tries <
        EvaluationService.EvaluationService.MAX_COMPILATION_TRIES)\
        .all()
    res_compiling_stop = res_compiling_query.filter(
        SubmissionResult.compilation_tries >=
        EvaluationService.EvaluationService.MAX_COMPILATION_TRIES)\
        .all()
    res_compilation_failed = res_full_query.filter(
        SubmissionResult.filter_compilation_failed())\
        .all()

    res_evaluating_ok = res_evaluating_query.filter(
        SubmissionResult.evaluation_tries <
        EvaluationService.EvaluationService.MAX_EVALUATION_TRIES)\
        .all()
    res_evaluating_stop = res_evaluating_query.filter(
        SubmissionResult.evaluation_tries >=
        EvaluationService.EvaluationService.MAX_EVALUATION_TRIES)\
        .all()
    res_scoring = res_evaluated_query.filter(
        not_(SubmissionResult.filter_scored()))\
        .all()
    res_scored = res_evaluated_query.filter(
        SubmissionResult.filter_scored())\
        .all()

    judgements_list = [
        (res_compiling_ok, 'compiling'),
        (res_compiling_stop, 'stuck_in_compilation'),
        (res_compilation_failed, 'compilation_failed'),
        (res_evaluating_ok, 'evaluating'),
        (res_evaluating_stop, 'stuck_in_evaluation'),
        (res_scoring, 'scoring'),
        (res_scored, 'scored'),
    ]

    status_list = " | ".join(map(lambda l: l[1], judgements_list))

    descs['judgements_total'] = ('gauge', 'status = {}\\ndataset_status = live | active | inactive'.format(status_list))
    metrics['judgements_total'] = {}
    for cs, status in judgements_list:
        for c in cs:
            cname, taskname, teamname, uname, ds_desc, ds_live, ds_autojudge, count = c
            ds_status = get_dataset_status(ds_live, ds_autojudge)
            key = (('contest', cname), ('task', taskname), ('team', teamname), ('user', uname),
                ('dataset', ds_desc), ('dataset_status', ds_status), ('status', status))
            metrics['judgements_total'][key] = count

    question_query = sql_session.query(Contest.name, Team.code, User.username, func.count(Question.id))\
        .select_from(Participation)\
        .filter(not_(Participation.hidden))\
        .outerjoin(Team, Team.id == Participation.team_id)\
        .join(User, User.id == Participation.user_id)\
        .join(Contest, Contest.id == Participation.contest_id)\
        .join(Question, Question.participation_id == Participation.id)\
        .group_by(Contest.id, Team.id, User.id)

    question_answered = question_query.filter(Question.reply_timestamp.isnot(None)).all()
    question_ignored = question_query.filter(Question.ignored.is_(True)).all()
    question_pending = question_query.filter(Question.reply_timestamp.is_(None), Question.ignored.is_(False)).all()

    question_list = [
        (question_answered, 'answered'),
        (question_ignored, 'ignored'),
        (question_pending, 'pending'),
    ]

    status_list = " | ".join(map(lambda l: l[1], question_list))

    descs['questions_total'] = ('gauge', 'status = {}'.format(status_list))
    metrics['questions_total'] = {}
    for qs, status in question_list:
        for q in qs:
            cname, tname, uname, count = q
            key = (('contest', cname), ('team', tname), ('user', uname), ('status', status))
            metrics['questions_total'][key] = count

    evals = sql_session.query(
        Contest.name, Task.name, Team.code, User.username, Dataset.description,
        Dataset.id == Task.active_dataset_id, Dataset.autojudge, func.coalesce(func.sum(Evaluation.execution_wall_clock_time), 0.0))\
        .select_from(Participation)\
        .filter(not_(Participation.hidden))\
        .outerjoin(Team, Team.id == Participation.team_id)\
        .join(User, User.id == Participation.user_id)\
        .join(Contest, Contest.id == Participation.contest_id)\
        .join(Submission, Submission.participation_id == Participation.id)\
        .join(Task, Task.id == Submission.task_id)\
        .join(SubmissionResult, SubmissionResult.submission_id == Submission.id)\
        .join(Dataset, Dataset.id == SubmissionResult.dataset_id)\
        .join(Evaluation, Evaluation.submission_id == Submission.id)\
        .filter(Evaluation.dataset_id == Dataset.id)\
        .group_by(Contest.id, Team.id, User.id, Task.id, Dataset.id)\
        .all()

    descs['wall_clock_time_total'] = ('gauge', 'dataset_status = live | active | inactive')
    metrics['wall_clock_time_total'] = {}

    for e in evals:
        cname, taskname, teamname, uname, ddesc, ds_live, ds_autojudge, wtime = e
        ds_status = get_dataset_status(ds_live, ds_autojudge)
        key = (('contest', cname), ('task', taskname), ('team', teamname), ('user', uname),
            ('dataset', ddesc), ('dataset_status', ds_status))
        metrics['wall_clock_time_total'][key] = wtime

    return (metrics, descs)

def compute_system_metrics(evaluation_service):

    metrics = {}
    descs = {}

    workers_status = evaluation_service.workers_status().get()
    connected_workers = len(list(filter(lambda st: st['connected'], workers_status.values())))
    total_workers = len(workers_status)

    descs['workers_total'] = ('gauge', 'status = connected | disconnected')
    metrics['workers_total'] = {
        (('status', 'connected'),): connected_workers,
        (('status', 'disconnected'),): total_workers - connected_workers,
    }

    return (metrics, descs)

def format_metrics_data(metrics, descs):

    lines = []

    for metric_key, metric_values in metrics.items():

        if metric_key in descs:
            metric_type, metric_help = descs[metric_key]
            lines.append('# TYPE cms_{} {}'.format(metric_key, metric_type))
            if metric_help is not None:
                lines.append('# HELP cms_{} {}'.format(metric_key, metric_help))

        for labels, value in metric_values.items():

            value_repr = '{:.4f}'.format(value) if type(value) is float else '{}'.format(value)
            filtered_labels = None if labels is None else filter_none(labels)

            if filtered_labels:
                kvs_list = map(lambda kv: '{}="{}"'.format(kv[0], kv[1]), filtered_labels)
                lines.append('cms_{}{{{}}} {}'.format(metric_key, ','.join(kvs_list), value_repr))
            else:
                lines.append('cms_{} {}'.format(metric_key, value_repr))

        lines.append('')

    return lines

class ContestMetricsHandler(CommonRequestHandler):

    def get(self):

        try:

            metrics, descs = compute_contest_metrics(self.sql_session)
            text = format_metrics_data(metrics, descs)
            self.write('\n'.join(text + ['']))
            self.set_header('Content-Type', 'text/plain')

        except Exception as err:

            logger.error(traceback.format_exc())

class SystemMetricsHandler(CommonRequestHandler):

    def get(self):

        try:

            metrics, descs = compute_system_metrics(self.service.evaluation_service)
            text = format_metrics_data(metrics, descs)
            self.write('\n'.join(text + ['']))
            self.set_header('Content-Type', 'text/plain')

        except Exception as err:

            logger.error(traceback.format_exc())
