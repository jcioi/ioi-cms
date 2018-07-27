#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function

import io
import logging
import os
import os.path
import sys
import tempfile
import zipfile
import yaml
import json
import re
from io import StringIO
from dateutil import parser, tz
from datetime import timedelta

from cms import SCORE_MODE_MAX
from cms.grading.languagemanager import LANGUAGES, HEADER_EXTS, get_language
from cms.db import Contest, User, Task, Statement, Attachment, \
    Dataset, Manager, Testcase
from cmscontrib import touch
from cmscommon.crypto import build_password

from .base_loader import ContestLoader, TaskLoader, UserLoader

logger = logging.getLogger(__name__)


# Patch PyYAML to make it load all strings as unicode instead of str
# (see http://stackoverflow.com/questions/2890146).
def construct_yaml_str(self, node):
    return self.construct_scalar(node)
yaml.Loader.add_constructor('tag:yaml.org,2002:str', construct_yaml_str)
yaml.SafeLoader.add_constructor('tag:yaml.org,2002:str', construct_yaml_str)

def make_timedelta(t):
    return timedelta(seconds=t)

def make_datetime(s):
    return parser.parse(s).astimezone(tz.tzutc()).replace(tzinfo=None)

def load_yaml(path):
    return yaml.safe_load(io.open(path, 'rt', encoding='utf-8'))

def same_path(a, b):
    return os.path.normpath(a) == os.path.normpath(b)

def get_mtime(fname):
    return os.stat(fname).st_mtime

def convert_glob_to_regexp(g):
    SPECIAL_CHARS = '\\.^$+{}[]|()'
    for c in SPECIAL_CHARS:
        g = g.replace(c, '\\' + c)
    g = g.replace('*', '.*')
    g = g.replace('?', '.')
    return g
def convert_globlist_to_regexp(gs):
    rs = ['(' + convert_glob_to_regexp(g) + ')' for g in gs]
    return '\A' + '|'.join(rs) + '\Z'

def try_assign(dest, src, keyname, conv=lambda i:i):
    if keyname in src:
        dest[keyname] = conv(src[keyname])
def assign(dest, src, keyname, conv=lambda i:i):
    dest[keyname] = conv(src[keyname])


# FIXME: split the class
#        (before splitting, we must rebuild the structure around loaders)
class ImprovedImoJudgeFormatLoader(ContestLoader, TaskLoader, UserLoader):

    """Load a contest, task or user stored using Improved ImoJudge format.

    Given the filesystem location of a contest, task or user, stored
    using Improved ImoJudge format, parse those files and directories
    to produce data that can be consumed by CMS.
    This format is INCOMPATIBLE with former ImoJudge-like format (used in 2015).

    As a ContestLoader,
    the path must be a contest config file with '.yaml' extension.

    As a TaskLoader, the path must be a directory that contains
    \"cms/task-iif.yaml\" file.
    Also, there must be a default task config file \"../default-task-iif.yaml\".

    """

    short_name = 'improved_imoj'
    description = 'Improved ImoJudge format'

    @staticmethod
    def detect(path):
        """See docstring in class Loader."""
        as_contest = os.path.exists(path) and path.endswith('.yaml')
        as_task = os.path.exists(os.path.join(path, 'cms', 'task-iif.yaml'))
        orig_path = os.path.normpath(os.path.join(path, '..'))
        as_user = os.path.exists(orig_path) and orig_path.endswith('.yaml')
        return as_contest or as_task or as_user

    def get_task_loader(self, taskname):
        """See docstring in class Loader."""

        conf_path = self.path
        base_path = os.path.dirname(self.path)

        if not os.path.exists(conf_path):
            logger.critical("specified contest config file not found")
            return None

        conf = load_yaml(conf_path)
        targets = []

        for t in conf['tasks']:
            taskdir = os.path.join(base_path, t)
            task_conf_path = os.path.join(taskdir, 'cms', 'task-iif.yaml')
            if not os.path.exists(task_conf_path):
                continue
            task_conf = load_yaml(task_conf_path)
            if ('name' in task_conf) and (task_conf['name'] == taskname):
                targets.append(taskdir)

        if len(targets) == 0:
            logger.critical("The specified task cannot be found.")
            return None
        if len(targets) > 1:
            logger.critical("There are multiple tasks with the same task name.")
            return None

        taskdir = os.path.join(base_path, targets[0])

        # TODO: check whether taskdir is a direct child of the contest dir

        return self.__class__(taskdir, self.file_cacher)

    def get_contest(self):
        """See docstring in class ContestLoader."""

        conf_path = self.path
        base_path = os.path.dirname(self.path)

        if not os.path.exists(conf_path):
            logger.critical("specified contest config file not found")
            return None

        conf = load_yaml(conf_path)
        name = conf['name']

        logger.info("Loading parameters for contest \"%s\".", name)

        args = {}

        assign(args, conf, 'name')
        assign(args, conf, 'description')
        assign(args, conf, 'languages')
        try_assign(args, conf, 'start', make_datetime)
        try_assign(args, conf, 'stop', make_datetime)

        try_assign(args, conf, 'ip_autologin')
        try_assign(args, conf, 'ip_restriction')

        try_assign(args, conf, 'score_precision')
        try_assign(args, conf, 'max_submission_number')
        try_assign(args, conf, 'max_user_test_number')
        try_assign(args, conf, 'min_submission_interval', make_timedelta)
        try_assign(args, conf, 'min_user_test_interval', make_timedelta)

        if 'token_mode' not in conf:
            conf['token_mode'] = 'disabled'

        assign(args, conf, 'token_mode')
        try_assign(args, conf, 'token_max_number')
        try_assign(args, conf, 'token_min_interval', make_timedelta)
        try_assign(args, conf, 'token_gen_initial')
        try_assign(args, conf, 'token_gen_number')
        try_assign(args, conf, 'token_gen_interval', make_timedelta)
        try_assign(args, conf, 'token_gen_max')

        if 'timezone' not in conf:
            conf['timezone'] = 'Asia/Tokyo'
        assign(args, conf, 'timezone')

        if 'allow_user_tests' not in conf:
            conf['allow_user_tests'] = False
        assign(args, conf, 'allow_user_tests')
        if 'allow_questions' not in conf:
            conf['allow_questions'] = False
        assign(args, conf, 'allow_questions')

        participations = []

        for u in conf['users']:
            participation_args = {}
            assign(participation_args, u, 'username')
            try_assign(participation_args, u, 'team')
            try_assign(participation_args, u, 'hidden')
            try_assign(participation_args, u, 'ip')
            try_assign(participation_args, u, 'password', build_password)
            participations.append(participation_args)

        tasks = []

        for t in conf['tasks']:
            taskdir = os.path.join(base_path, t)
            task_conf_path = os.path.join(taskdir, 'cms', 'task-iif.yaml')
            if not os.path.exists(task_conf_path):
                logger.warning("Task config file cannot be found "
                    "(path: %s).", task_conf_path)
                continue
            task_conf = load_yaml(task_conf_path)
            if not 'name' in task_conf:
                logger.warning("Task name cannot be found in config file "
                    "(path: %s).", task_conf_path)
                continue
            tasks.append(task_conf['name'])

        all_languages = [l.name for l in LANGUAGES]
        for l in args['languages']:
            if l not in all_languages:
                logger.critical("Language \"%s\" is not supported.", l)
                return None

        logger.info("Contest parameters loaded.")

        return Contest(**args), tasks, participations

    def get_user(self):
        """See docstring in class UserLoader."""

        # due to the terrible AddUser script
        conf_path = os.path.dirname(self.path)
        username = os.path.basename(self.path)

        if not os.path.exists(conf_path):
            logger.critical("specified config file not found")
            return None

        conf = load_yaml(conf_path)

        logger.info("Loading parameters for user %s.", username)

        targets = [u for u in conf['users'] if u['username'] == username]

        if len(targets) == 0:
            logger.critical("The specified user cannot be found.")
            return None
        if len(targets) > 1:
            logger.critical("There are multiple users with the same user name.")
            return None

        args = {}
        user_conf = targets[0]

        if 'first_name' not in user_conf:
            user_conf['first_name'] = ""
        if 'last_name' not in user_conf:
            user_conf['last_name'] = user_conf['username']

        assign(args, user_conf, 'username')
        assign(args, user_conf, 'password', build_password)
        assign(args, user_conf, 'first_name')
        assign(args, user_conf, 'last_name')
        try_assign(args, user_conf, 'hidden')

        logger.info("User parameters loaded.")

        return User(**args)

    def get_task(self, get_statement=True):
        """See docstring in class TaskLoader."""

        base_path = self.path
        contest_path = os.path.join(self.path, '..')
        conf_path = os.path.join(self.path, 'cms', 'task-iif.yaml')
        contest_conf_path = os.path.join(contest_path, 'default-task-iif.yaml')

        if not os.path.exists(conf_path):
            logger.critical("File missing: \"task-iif.yaml\"")
            return None
        if not os.path.exists(contest_conf_path):
            logger.critical("File missing: \"default-task-iif.yaml\"")
            return None

        conf = load_yaml(conf_path)
        contest_conf = load_yaml(contest_conf_path)

        name = conf['name']
        allowed_langs = contest_conf['languages']

        logger.info("Loading parameters for task %s.", name)

        default_keys = ['min_submission_interval', 'max_submission_number']
        for key in default_keys:
            parent_key = 'default_' + key
            if parent_key in contest_conf:
                conf.setdefault(key, contest_conf[parent_key])

        task_args = {}

        task_args['name'] = name
        assign(task_args, conf, 'title')

        if task_args['name'] == task_args['title']:
            logger.warning("Short name and title are same. Please check.")

        try_assign(task_args, conf, 'score_precision')
        try_assign(task_args, conf, 'max_submission_number')
        try_assign(task_args, conf, 'max_user_test_number')
        try_assign(task_args, conf, 'min_submission_interval', make_timedelta)
        try_assign(task_args, conf, 'min_user_test_interval', make_timedelta)

        if 'token_mode' not in conf:
            conf['token_mode'] = 'disabled'

        assign(task_args, conf, 'token_mode')
        try_assign(task_args, conf, 'token_max_number')
        try_assign(task_args, conf, 'token_min_interval', make_timedelta)
        try_assign(task_args, conf, 'token_gen_initial')
        try_assign(task_args, conf, 'token_gen_number')
        try_assign(task_args, conf, 'token_gen_interval', make_timedelta)
        try_assign(task_args, conf, 'token_gen_max')

        if 'score_mode' not in conf:
            conf['score_mode'] = SCORE_MODE_MAX
        assign(task_args, conf, 'score_mode')

        # Language Check
        for lang_name in allowed_langs:
            try:
                lang = get_language(lang_name)
            except KeyError:
                logger.critical("Language \"%s\" is not supported.", lang_name)
                return None

        # Statements
        if get_statement:

            primary_lang = conf.get('primary_language', 'ja')
            pdf_dir = os.path.join(base_path, 'task')
            pdf_paths = [
                (os.path.join(pdf_dir, "statement.pdf"), primary_lang),
                (os.path.join(pdf_dir, "statement-ja.pdf"), 'ja'),
                (os.path.join(pdf_dir, "statement-en.pdf"), 'en')]

            task_args['statements'] = {}
            for path, lang in pdf_paths:
                if os.path.exists(path):
                    digest = self.file_cacher.put_file_from_path(path,
                        "Statement for task %s (lang: %s)" % (name, lang))
                    task_args['statements'][lang] = Statement(lang, digest)

            if len(task_args['statements']) == 0:
                logger.warning("Couldn't find any task statement.")

            task_args['primary_statements'] = [primary_lang]

        # maybe modified in the succeeding process
        task_args['submission_format'] = [
            "%s.%%l" % name]

        task = Task(**task_args)

        ds_args = {}

        ds_args['task'] = task
        ds_args['description'] = conf.get('version', 'default-version')
        ds_args['autojudge'] = False

        testcases = []
        input_digests = {}

        feedback_globs = conf.get('feedback', ['*'])
        feedback_regexp = convert_globlist_to_regexp(feedback_globs)
        feedback_re = re.compile(feedback_regexp)

        # Testcases enumeration
        for input_dir_name in [os.path.join(base_path, 'gen', 'in'), os.path.join(base_path, 'in')]:
            if not os.path.isdir(input_dir_name):
                continue
            for f in os.listdir(input_dir_name):
                m = re.match(r'\A(.*)\.txt\Z', f)
                if m:
                    tc_name = m.group(1)
                    in_path = os.path.join(input_dir_name, f)
                    out_path = os.path.join(input_dir_name, '..', 'out', f)
                    testcases.append({
                        'name': tc_name,
                        'in_path': in_path,
                        'out_path': out_path,
                        'feedback': feedback_re.match(tc_name) is not None
                    })
                else:
                    logger.warning("File \"%s\" was not added to testcases" % f)

        testcases.sort(key=lambda tc: tc['name'])

        # FIXME: detect testcase name collision

        ds_args['testcases'] = {}

        null_output_testcases = []

        for tc in testcases:

            in_path = tc['in_path']
            out_path = tc['out_path']
            tc_name = tc['name']
            feedback = tc['feedback']

            input_digest = self.file_cacher.put_file_from_path(
                in_path, "Input %s for task %s" % (tc_name, name))
            output_digest = None

            if os.path.exists(out_path):
                output_digest = self.file_cacher.put_file_from_path(
                    out_path, "Output %s for task %s" % (tc_name, name))
            else:
                null_output_testcases.append(tc_name)
                dummy = StringIO('')
                output_digest = self.file_cacher.put_file_from_fobj(
                    dummy, "Dummy output %s for task %s" % (tc_name, name))
                dummy.close()

            ds_args['testcases'][tc_name] = Testcase(tc_name, feedback,
                input_digest, output_digest)
            input_digests[tc_name] = input_digest

        if null_output_testcases:
            pretty_testcases = ", ".join(null_output_testcases)
            logger.warning("Some output files are missing.")
            logger.warning("Testcases: %s", pretty_testcases)

        # Attachments
        dist_path = os.path.join(base_path, 'dist')

        zip_dist_files = []
        direct_dist_files = []

        if os.path.exists(dist_path):

            for base, dirs, files in os.walk(dist_path):
                for fname in files:
                    fpath = os.path.join(base, fname)
                    arc_name = os.path.relpath(fpath, dist_path)
                    if fname.endswith('.zip'):
                        replaced_arc_name = arc_name.replace(os.sep, '-')
                        direct_dist_files.append((fpath, replaced_arc_name))
                    else:
                        zip_dist_files.append((fpath, arc_name))

        # Auto copy of sample input/output files
        samples_globs = conf.get('samples', ['sample-*'])
        samples_regexp = convert_globlist_to_regexp(samples_globs)
        samples_re = re.compile(samples_regexp)

        for tc in testcases:

            in_path = tc['in_path']
            out_path = tc['out_path']
            tc_name = tc['name']
            feedback = tc['feedback']

            if not samples_re.match(tc_name):
                continue
            zip_dist_files.append((in_path, tc_name + '-in.txt'))
            if os.path.exists(out_path):
                zip_dist_files.append((out_path, tc_name + '-out.txt'))

        zip_dist_file_names = map(lambda f: f[1], zip_dist_files)
        direct_dist_file_names = map(lambda f: f[1], direct_dist_files)
        logger.info("compressed dist files: %s", ", ".join(zip_dist_file_names))
        logger.info("direct dist files: %s", ", ".join(direct_dist_file_names))

        if zip_dist_files:
            zfn = tempfile.mkstemp('iif-loader-', '.zip')
            with zipfile.ZipFile(zfn[1], 'w', zipfile.ZIP_STORED) as zf:
                for fpath, fname in zip_dist_files:
                    zf.write(fpath, os.path.join(name, fname))
            zip_digest = self.file_cacher.put_file_from_path(
                zfn[1], "Distribution archive for task %s" % name)
            fname = name + '.zip'
            task.attachments[fname] = Attachment(fname, zip_digest)
            os.remove(zfn[1])

        for fpath, fname in direct_dist_files:
            digest = self.file_cacher.put_file_from_path(
                fpath, "Distribution file for task %s" % name)
            task.attachments[fname] = Attachment(fname, digest)

        # Score type specific processing
        scoretype = conf.get('score_type', 'Normal')

        if scoretype == 'Normal':

            score_params = [
                [st['point'], convert_globlist_to_regexp(st['targets'])]
                for st in conf['subtasks']]
            ds_args['score_type_parameters'] = score_params
            ds_args['score_type'] = 'GroupMin'

        elif scoretype == 'Truncation':

            score_params = []

            for st in conf['subtasks']:

                option = st['score_option']

                if 'threshold' not in option:
                    logger.critical("\"Truncation\" score type requires "
                        "\"threshold\" parameter for each task.")
                    return None

                if 'power' not in option:
                    option['power'] = 1.0

                param = [
                    st['point'],
                    convert_globlist_to_regexp(st['targets']),
                    option['threshold'][0],
                    option['threshold'][1],
                    option['power']
                ]

                score_params.append(param)

            ds_args['score_type_parameters'] = score_params
            ds_args['score_type'] = 'GroupMinTruncation'

        else:

            logger.critical("Score type \"%s\" is "
                "currently unsupported.", scoretype)
            return None

        cms_path = os.path.join(base_path, 'cms')

        grader_found = False
        stub_found = False
        manager_found = False
        comparator_found = False

        ds_args["managers"] = {}

        # Auto generation for manager/checker
        compilation_pairs = [
            ['manager.cpp', 'manager'],
            ['checker.cpp', 'checker']]
        for src_name, dst_name in compilation_pairs:
            src = os.path.join(cms_path, src_name)
            dst = os.path.join(cms_path, dst_name)
            if os.path.exists(src):
                has_src_changed = True
                if os.path.exists(dst):
                    has_src_changed = get_mtime(src) > get_mtime(dst)
                if has_src_changed:
                    logger.info("Auto-generation for %s." % dst)
                    os.system("g++ -std=c++11 -O2 -Wall -static %s -o %s"
                              % (src, dst))

        # Additional headers
        if os.path.exists(cms_path):
            for fname in os.listdir(cms_path):

                if any(fname.endswith(h) for h in HEADER_EXTS):

                    digest = self.file_cacher.put_file_from_path(
                        os.path.join(cms_path, fname),
                        "Header \"%s\" for task %s" % (fname, name))
                    ds_args['managers'][fname] = Manager(fname, digest)
                    logger.info("Storing additional header \"%s\".", fname)

        # Graders and Stubs
        for lang_name in allowed_langs:

            lang = get_language(lang_name)
            src_ext = lang.source_extension
            if src_ext is None:
                logger.warning("Source exts not found for language \"%s\"", lang_name)
                continue

            # Grader
            grader_fname = 'grader%s' % src_ext
            grader_path = os.path.join(cms_path, grader_fname)
            if os.path.exists(grader_path):
                grader_found = True
                digest = self.file_cacher.put_file_from_path(
                    grader_path,
                    "Grader for task %s (language: %s)" % (name, lang_name))
                ds_args['managers'][grader_fname] = Manager(grader_fname, digest)

            # Stub
            stub_fname = 'stub%s' % src_ext
            stub_path = os.path.join(cms_path, stub_fname)
            if os.path.exists(stub_path):
                stub_found = True
                digest = self.file_cacher.put_file_from_path(
                    stub_path,
                    "Stub for task %s (language: %s)" % (name, lang_name))
                ds_args['managers'][stub_fname] = Manager(stub_fname, digest)

        # Graders and Stubs Check
        for lang_name in allowed_langs:

            lang = get_language(lang_name)
            src_ext = lang.source_extension
            if src_ext is None:
                continue

            grader_fname = 'grader%s' % src_ext
            grader_path = os.path.join(cms_path, grader_fname)
            if grader_found and not os.path.exists(grader_path):
                logger.warning("Grader for language \"%s\" not found.", lang_name)

            stub_fname = 'stub%s' % src_ext
            stub_path = os.path.join(cms_path, stub_fname)
            if stub_found and not os.path.exists(stub_path):
                logger.warning("Stub for language \"%s\" not found.", lang_name)

        # Manager
        if os.path.exists(os.path.join(cms_path, 'manager')):
            manager_found = True
            digest = self.file_cacher.put_file_from_path(
                os.path.join(cms_path, 'manager'),
                "Manager for task %s" % name)
            ds_args['managers']['manager'] = Manager('manager', digest)

        # Checker
        if os.path.exists(os.path.join(cms_path, 'checker')):
            comparator_found = True
            digest = self.file_cacher.put_file_from_path(
                os.path.join(cms_path, 'checker'),
                "Checker for task %s" % name)
            ds_args['managers']['checker'] = Manager('checker', digest)

        eval_param = 'comparator' if comparator_found else 'diff'

        # Task type specific processing
        tasktype = conf.get('task_type', 'Batch')

        if tasktype == 'Batch':

            compilation_param = 'grader' if grader_found else 'alone'
            infile_param = ''
            outfile_param = ''

            assign(ds_args, conf, 'time_limit', conv=float)
            assign(ds_args, conf, 'memory_limit')

            ds_args['task_type'] = 'Batch'
            ds_args['task_type_parameters'] = \
                [compilation_param, [infile_param, outfile_param], eval_param]

        elif tasktype == 'OutputOnly':

            task.submission_format = [
                'output_%s.txt' % tc['name']
                for tc in testcases]
            for tc in testcases:
                fname = 'input_%s.txt' % tc['name']
                task.attachments[fname] = Attachment(fname, input_digests[tc['name']])

            ds_args['task_type'] = 'OutputOnly'
            ds_args['task_type_parameters'] = [eval_param]

        elif tasktype == 'Communication':

            if not stub_found:
                logger.critical("Stub is required for Communication task.")
                return None
            if not manager_found:
                logger.critical("Manager is required for Communication task.")
                return None

            assign(ds_args, conf, 'time_limit', conv=float)
            assign(ds_args, conf, 'memory_limit')

            ds_args['task_type'] = 'Communication'

            task_params = [1]

            if 'task_option' in conf:

                task_option = conf['task_option']

                if 'processes' not in task_option:
                    logger.critical("task_option/processes is required.")
                    return None
                if 'formats' not in task_option:
                    logger.critical("task_option/formats is required.")
                    return None

                task_params = [task_option['processes']]
                task.submission_format = [
                    filename
                    for filename in task_option['formats']]

            ds_args['task_type_parameters'] = task_params

        else:
            logger.critical("Task type \"%s\" is "
                "currently unsupported.", tasktype)
            return None

        dataset = Dataset(**ds_args)
        task.active_dataset = dataset

        logger.info("tasktype: %s", tasktype)
        def pr(b):
            return "found" if b else "-----"
        logger.info("grader: %s, comparator: %s", pr(grader_found), pr(comparator_found))
        logger.info("stub  : %s, manager   : %s", pr(stub_found), pr(manager_found))

        logger.info("Task parameters loaded.")

        return task

    def contest_has_changed(self):
        """See docstring in class ContestLoader."""
        return True

    def user_has_changed(self):
        """See docstring in class UserLoader."""
        return True

    def task_has_changed(self):
        """See docstring in class TaskLoader."""
        return True
