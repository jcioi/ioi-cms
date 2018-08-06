#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function

import re, logging, io, os, subprocess, tempfile, zipfile, datetime
import yaml, json
from os.path import exists
from dateutil import parser, tz

from cms import SCORE_MODE_MAX, SCORE_MODE_MAX_SUBTASK, TOKEN_MODE_DISABLED
from cms.grading.languagemanager import LANGUAGES, HEADER_EXTS, SOURCE_EXTS
from cms.db import Contest, User, Task, Statement, Attachment, \
    Dataset, Manager, Testcase, Team
from cmscommon.crypto import build_password

from .base_loader import ContestLoader, TaskLoader, UserLoader


AUTO_COMPILATION_CMD = ['g++', '--std=c++14', '-O2', '-Wall']
ENVVAR_NAME_DEFAULT_CONF_PATH = 'CMS_DEFAULT_TASK_CONF_PATH'
DEFAULT_CONF_PATH = os.path.join('..', 'default-task-iif.yaml')

logger = logging.getLogger(__name__)

def load_yaml(path):
    return yaml.safe_load(io.open(path, encoding='utf-8'))
def make_timedelta(t):
    return datetime.timedelta(seconds=t)
def make_datetime(s):
    return parser.parse(s).astimezone(tz.tzutc()).replace(tzinfo=None)

def glob_to_regexp(g):
    SPECIAL_CHARS = '\\.^$+{}[]|()'
    for c in SPECIAL_CHARS:
        g = g.replace(c, '\\' + c)
    g = g.replace('*', '.*')
    g = g.replace('?', '.')
    return g
def globlist_to_text(gs):
    rs = ['(' + glob_to_regexp(g) + ')' for g in gs]
    return '\A' + '|'.join(rs) + '\Z'
def globlist_to_regexp(gs):
    return re.compile(globlist_to_text(gs))

def try_assign(dest, src, key, conv=lambda i:i):
    if key in src:
        dest[key] = conv(src[key])
def default_assign(dest, src, key, conv=lambda i:i):
    if key in src:
        dest.setdefault(key, conv(src[key]))
def assign(dest, src, key, conv=lambda i:i):
    dest[key] = conv(src[key])

class ImprovedImojLoader(ContestLoader, TaskLoader, UserLoader):

    """Load a contest, task or user stored using Improved Imoj format.

    Given the filesystem location of a contest, task or user, stored
    using Improved Imoj format, parse those files and directories
    to produce data that can be consumed by CMS.
    This format is INCOMPATIBLE with former ImoJudge-like format (used in 2015).

    As a ContestLoader,
    the path must be a contest config file with '.yaml' extension.

    As a TaskLoader, the path must be a directory that contains
    \"cms/task-iif.yaml\" file.
    Also, there must be a default task config file \"../default-task-iif.yaml\".

    """

    short_name = 'improved_imoj'
    description = 'Improved Imoj format'

    @staticmethod
    def detect(path):

        as_contest = exists(path) and path.endswith('.yaml')
        as_task = exists(os.path.join(path, 'cms', 'task-iif.yaml'))

        # ImportUser/Team forces to use base_path/$name
        orig_path = os.path.normpath(os.path.join(path, '..'))
        as_user_or_team = exists(orig_path) and orig_path.endswith('.yaml')
        return as_contest or as_task or as_user_or_team

    @staticmethod
    def find_task_name(task_path):

        conf_path = os.path.join(task_path, 'cms', 'task-iif.yaml')
        if not os.path.exists(conf_path):
            return None
        conf = load_yaml(conf_path)
        return conf.get('name')

    def contest_has_changed(self):
        return True

    def user_has_changed(self):
        return True

    def task_has_changed(self):
        return True

    def get_task_loader(self, taskname):

        conf_path = self.path
        base_path = os.path.dirname(self.path)

        if not exists(conf_path):
            logger.critical("cannot find contest config file")
            return None

        conf = load_yaml(conf_path)
        candidates = []

        for t in conf['tasks']:
            task_path = os.path.join(base_path, t)
            name = ImprovedImojLoader.find_task_name(task_path)
            if name == taskname:
                candidates.append(task_path)

        if len(candidates) == 0:
            logger.critical("cannot find specified task")
            return None
        if len(candidates) > 1:
            logger.critical("multiple tasks found with the same task name")
            return None

        return self.__class__(candidates[0], self.file_cacher)

    def get_contest(self):

        conf_path = self.path
        base_path = os.path.dirname(self.path)

        if not exists(conf_path):
            logger.critical("cannot find contest config file")
            return None, None, None

        conf = load_yaml(conf_path)
        name = conf['name']

        logger.info("loading parameters for contest \"%s\"", name)

        # default values
        conf.setdefault('allow_user_tests', False)
        conf.setdefault('allow_questions', False)
        conf.setdefault('timezone', 'Asia/Tokyo')

        # override
        conf['token_mode'] = TOKEN_MODE_DISABLED

        # validity check
        cms_langs = [lang.name for lang in LANGUAGES]
        for lang in conf['languages']:
            if lang not in cms_langs:
                logger.critical("language \"%s\" is not supported", lang)
                return None, None, None

        contest = {}

        assign(contest, conf, 'name')
        assign(contest, conf, 'description')
        assign(contest, conf, 'languages')

        assign(contest, conf, 'allow_user_tests')
        assign(contest, conf, 'allow_questions')
        assign(contest, conf, 'timezone')
        assign(contest, conf, 'token_mode')

        try_assign(contest, conf, 'ip_restriction')
        try_assign(contest, conf, 'ip_autologin')
        try_assign(contest, conf, 'score_precision')
        try_assign(contest, conf, 'max_submission_number')
        try_assign(contest, conf, 'max_user_test_number')
        try_assign(contest, conf, 'analysis_enabled')
        try_assign(contest, conf, 'min_submission_interval', make_timedelta)
        try_assign(contest, conf, 'min_user_test_interval', make_timedelta)
        try_assign(contest, conf, 'start', make_datetime)
        try_assign(contest, conf, 'stop', make_datetime)
        try_assign(contest, conf, 'analysis_start', make_datetime)
        try_assign(contest, conf, 'analysis_stop', make_datetime)

        participations = []

        for u in conf['users']:
            p = {}
            assign(p, u, 'username')
            try_assign(p, u, 'team')
            try_assign(p, u, 'hidden')
            try_assign(p, u, 'ip')
            try_assign(p, u, 'password', build_password)
            participations.append(p)

        tasks = []

        for t in conf['tasks']:
            task_path = os.path.join(base_path, t)
            task_name = ImprovedImojLoader.find_task_name(task_path)
            if task_name is not None:
                tasks.append(task_name)
            else:
                logger.warning("cannot detect task name (path: \"%s\")", task_path)

        logger.info("contest parameters loaded")

        return Contest(**contest), tasks, participations

    def get_team(self):
        # due to the terrible AddUser script
        conf_path = os.path.dirname(self.path)
        name = os.path.basename(self.path)

        if not exists(conf_path):
            logger.critical("cannot find config file")
            return None

        logger.info("loading parameters for team \"%s\"", name)

        conf = load_yaml(conf_path)
        candidates = [u for u in conf['teams'] if u['code'] == name]

        if len(candidates) == 0:
            logger.critical("cannot find specified team")
            return None
        if len(candidates) > 1:
            logger.critical("multiple teams found with the same code")
            return None

        item = candidates[0]

        # default values
        team = {}

        assign(team, item, 'code')
        assign(team, item, 'name')

        return Team(**item)

    def get_user(self):

        # due to the terrible AddUser script
        conf_path = os.path.dirname(self.path)
        username = os.path.basename(self.path)

        if not exists(conf_path):
            logger.critical("cannot find user config file")
            return None

        logger.info("loading parameters for user \"%s\"", username)

        conf = load_yaml(conf_path)
        candidates = [u for u in conf['users'] if u['username'] == username]

        if len(candidates) == 0:
            logger.critical("cannot find specified user")
            return None
        if len(candidates) > 1:
            logger.critical("multiple users found with the same name")
            return None

        user_conf = candidates[0]

        # default values
        user_conf.setdefault('first_name', '')
        user_conf.setdefault('last_name', username)

        user = {}

        assign(user, user_conf, 'username')
        assign(user, user_conf, 'first_name')
        assign(user, user_conf, 'last_name')
        assign(user, user_conf, 'password', build_password)

        logger.info("user parameters loaded")

        return User(**user)

    def get_task(self, get_statement=True):

        base_path = self.path
        cms_path = os.path.join(base_path, 'cms')
        conf_path = os.path.join(base_path, 'cms', 'task-iif.yaml')

        if not exists(conf_path):
            logger.critical("cannot find \"task-iif.yaml\"")
            return None

        conf = load_yaml(conf_path)
        name = conf['name']

        logger.info("loading parameters for task \"%s\"", name)

        # inherited default
        default_conf_path_x = os.path.join(base_path, DEFAULT_CONF_PATH)
        default_conf_path = os.environ.get(ENVVAR_NAME_DEFAULT_CONF_PATH, default_conf_path_x)
        if exists(default_conf_path):
            default_conf = load_yaml(default_conf_path)
            default_assign(conf, default_conf, 'primary_language')
            default_assign(conf, default_conf, 'max_submission_number')
            default_assign(conf, default_conf, 'min_submission_interval')
        else:
            logging.warning("cannot find default config file")

        # default
        conf.setdefault('score_mode', SCORE_MODE_MAX_SUBTASK)
        conf.setdefault('primary_language', 'ja')
        conf.setdefault('samples', ['sample-*'])
        conf.setdefault('feedback', ['*'])
        conf.setdefault('version', 'default-dataset')

        # override
        conf['token_mode'] = TOKEN_MODE_DISABLED

        task = {}
        task_type = conf.get('task_type', 'batch').lower()
        score_type = conf.get('score_type', 'normal').lower()

        # general task config
        assign(task, conf, 'name')
        assign(task, conf, 'title')
        task['primary_statements'] = [conf['primary_language']]
        assign(task, conf, 'score_mode')
        assign(task, conf, 'token_mode')
        try_assign(task, conf, 'max_submission_number')
        try_assign(task, conf, 'max_user_test_number')
        try_assign(task, conf, 'min_submission_interval', make_timedelta)
        try_assign(task, conf, 'min_user_test_interval', make_timedelta)
        try_assign(task, conf, 'score_precision')

        sample_regexp = globlist_to_regexp(conf['samples'])
        feedback_regexp = globlist_to_regexp(conf['feedback'])

        # testcases detection
        testcases = {}
        missing_out_testcases = []

        old_input_dir = os.path.join(base_path, 'in')
        new_input_dir = os.path.join(base_path, 'gen', 'in')

        for input_dir in [old_input_dir, new_input_dir]:

            if not os.path.isdir(input_dir):
                continue

            for fname in os.listdir(input_dir):

                m = re.match(r'\A(.+)\.txt\Z', fname)

                if not m:
                    logger.warning("ignored input file: \"%s\"", fname)
                    continue

                codename = m.group(1)
                in_path = os.path.join(input_dir, fname)
                out_path = os.path.join(input_dir, '..', 'out', fname)

                if not exists(out_path):
                    missing_out_testcases.append(codename)
                    out_path = None

                if codename in testcases:
                    logger.warning("duplicated testcase name: \"%s\"", codename)

                testcases[codename] = {
                    'in_path': in_path,
                    'out_path': out_path,
                    'sample': sample_regexp.match(codename) is not None,
                    'feedback': feedback_regexp.match(codename) is not None,
                }

        # additional files detection
        headers = []
        stubs, graders, manager, checker = [], [], None, None
        manager_src, checker_src = None, None

        for fname in os.listdir(cms_path):

            path = os.path.join(cms_path, fname)

            if any(fname.endswith(ext) for ext in HEADER_EXTS):
                headers.append((fname, path))

            for src_ext in SOURCE_EXTS:
                if fname == ('stub%s' % src_ext):
                    stubs.append((fname, path))
                if fname == ('grader%s' % src_ext):
                    graders.append((fname, path))

            if fname == 'manager.cpp':
                manager_src = path
            if fname == 'checker.cpp':
                checker_src = path

        # auto compilation
        if manager_src:
            manager = ('manager', os.path.join(cms_path, 'manager'))
            logger.info("manager auto compilation")
            ret = subprocess.call(AUTO_COMPILATION_CMD + [manager_src, '-o', manager[1]])
            if ret != 0:
                logger.critical("manager compilation failed")
                return None
        if checker_src:
            checker = ('checker', os.path.join(cms_path, 'checker'))
            logger.info("checker auto compilation")
            ret = subprocess.call(AUTO_COMPILATION_CMD + [checker_src, '-o', checker[1]])
            if ret != 0:
                logger.critical("checker compilation failed")
                return None

        # statements detection & registration
        if get_statement:

            statements = {}

            primary_language = conf['primary_language']
            pdf_dir = os.path.join(base_path, 'task')
            pdf_files = [
                ('statement.pdf', primary_language),
                ('statement-ja.pdf', 'ja'),
                ('statement-en.pdf', 'en'),
            ]

            for fname, lang in pdf_files:
                path = os.path.join(pdf_dir, fname)
                if exists(path):
                    digest = self.file_cacher.put_file_from_path(path,
                        "statement (%s) for task \"%s\"" % (lang, name))
                    statements[lang] = Statement(lang, digest)

            task['statements'] = statements

            if len(statements) == 0:
                logger.warning("cannot find any task statements")

        # attachments detection
        dist_path = os.path.join(base_path, 'dist')

        zipping_files = []
        dist_files = []

        if exists(dist_path):
            for base, dirs, files in os.walk(dist_path):
                for fname in files:

                    path = os.path.join(base, fname)
                    arc_name = os.path.relpath(path, dist_path)
                    safe_arc_name = arc_name.replace(os.sep, '-')

                    if fname.endswith('.zip'):
                        dist_files.append((path, safe_arc_name))
                    else:
                        zipping_files.append((path, arc_name))

        for codename, testcase in testcases.items():

            in_path = testcase['in_path']
            out_path = testcase['out_path']

            if testcase['sample']:
                zipping_files.append((in_path, "%s-in.txt" % codename))
                if out_path:
                    zipping_files.append((out_path, "%s-out.txt" % codename))
            elif task_type == 'outputonly':
                zipping_files.append((in_path, "input_%s.txt" % codename))

        dataset = {}

        dataset['description'] = conf['version']
        dataset['autojudge'] = False

        # score type parameters
        if score_type == 'normal':

            dataset['score_type_parameters'] = [
                [st['point'], globlist_to_text(st['targets'])]
                for st in conf['subtasks']
            ]
            dataset['score_type'] = 'GroupMin'

        elif score_type == 'truncation':

            score_params = []

            for st in conf['subtasks']:

                opt = st['score_option']
                opt.setdefault('power', 1.0)

                if 'threshold' not in opt:
                    logger.critical("truncation score type requires \"threshold\" parameter")
                    return None

                param = [
                    st['point'],
                    globlist_to_text(st['targets']),
                    opt['threshold'][0],
                    opt['threshold'][1],
                    opt['power'],
                ]

                score_params.append(param)

            dataset['score_type_parameters'] = score_params
            dataset['score_type'] = 'GroupMinTruncation'

        else:

            logger.critical("unknown score type \"%s\"", score_type)
            return None

        # task_type
        grader_param = 'grader' if graders else 'alone'
        eval_param = 'comparator' if checker else 'diff'

        if task_type == 'batch':

            assign(dataset, conf, 'time_limit')
            assign(dataset, conf, 'memory_limit')

            task['submission_format'] = ["%s.%%l" % name]
            dataset['task_type'] = 'Batch'
            dataset['task_type_parameters'] = \
                [grader_param, ['', ''], eval_param]

        elif task_type == 'outputonly':

            task['submission_format'] =  [
                'output_%s.txt' % codename
                for codename in sorted(testcases.keys())]
            dataset['task_type'] = 'OutputOnly'
            dataset['task_type_parameters'] = [eval_param]

        elif task_type == 'communication':

            assign(dataset, conf, 'time_limit')
            assign(dataset, conf, 'memory_limit')

            if not stubs:
                logger.critical("stub is required for communication task")
                return None
            if not manager:
                logger.critical("manager is required for communication task")
                return None

            task_params = [1]
            submission_format = ["%s.%%l" % name]

            if 'task_option' in conf:

                opt = conf['task_option']

                if 'processes' not in opt:
                    logger.critical("task_option/processes is required")
                    return None
                if 'formats' not in opt:
                    logger.critical("task_option/formats is required")
                    return None

                task_params = [opt['processes']]
                submission_format = [
                    fname for fname in opt['formats']
                ]

            task['submission_format'] = submission_format
            dataset['task_type'] = 'Communication'
            dataset['task_type_parameters'] = task_params

        else:

            logger.critical("unknown task type \"%s\"", task_type)
            return None

        # attachments registration
        attachments = {}

        for path, arc_name in dist_files:
            digest = self.file_cacher.put_file_from_path(
                path, "distribution file for task \"%s\"" % name)
            attachments[arc_name] = Attachment(arc_name, digest)

        # zipfile registration
        if zipping_files:

            zip_archive = tempfile.mkstemp('cms-iimoj-loader-', '.zip')
            zip_path = zip_archive[1]

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as fp:
                for path, arc_name in zipping_files:
                    new_arc_name = os.path.join(name, arc_name)
                    fp.write(path, new_arc_name)

            zip_digest = self.file_cacher.put_file_from_path(zip_path,
                "distribution archive for task \"%s\"" % name)
            zip_fname = name + '.zip'
            attachments[zip_fname] = Attachment(zip_fname, zip_digest)
            os.remove(zip_path)

        task['attachments'] = attachments

        # additional files registration
        extra_managers = {}

        extra_files = headers + stubs + graders
        if manager:
            extra_files.append(manager)
        if checker:
            extra_files.append(checker)

        for fname, path in extra_files:
            digest = self.file_cacher.put_file_from_path(path,
                    "extra file \"%s\" for task \"%s\"" % (fname, name))
            logger.info("extra file: \"%s\"", fname)
            extra_managers[fname] = Manager(fname, digest)

        dataset['managers'] = extra_managers

        # testcases registration
        logger.info("registering testcases")

        registered_testcases = {}

        for codename, testcase in testcases.items():

            in_path = testcase['in_path']
            out_path = testcase['out_path']
            feedback = testcase['feedback']

            in_digest = self.file_cacher.put_file_from_path(in_path,
                "input \"%s\" for task \"%s\"" % (codename, name))
            out_digest = None

            if out_path:
                out_digest = self.file_cacher.put_file_from_path(out_path,
                    "output \"%s\" for task \"%s\"" % (codename, name))
            else:
                out_digest = self.file_cacher.put_file_content(b'',
                    "output \"%s\" for task \"%s\"" % (codename, name))

            registered_testcases[codename] = Testcase(codename,
                feedback, in_digest, out_digest)

        logger.info("testcases registration completed")

        dataset['testcases'] = registered_testcases

        # instantiation
        db_task = Task(**task)
        dataset['task'] = db_task
        db_dataset = Dataset(**dataset)
        db_task.active_dataset = db_dataset

        # import result
        logger.info("========== task \"%s\" ==========", name)
        logger.info("tasktype  : %s", task_type)

        if task_type != 'batch':
            logger.info("headers   : [%02d files]", len(headers))
            for fname, _ in sorted(headers):
                logger.info("            * %s", fname)

        if task_type == 'communication':
            logger.info("manager   : %s", "OK" if manager else "--")
            logger.info("stub      : [%02d files]", len(stubs))
            for fname, _ in sorted(stubs):
                logger.info("            * %s", fname)

        if task_type != 'communication':
            logger.info("comparator: %s", "OK" if checker else "--")

        if task_type == 'batch':
            logger.info("grader    : [%02d files]", len(graders))
            for fname, _ in sorted(graders):
                logger.info("            * %s", fname)

        logger.info("zipped    : [%02d files]", len(zipping_files))
        for _, arc_name in sorted(zipping_files):
            logger.info("            * %s", arc_name)
        logger.info("direct    : [%02d files]", len(dist_files))
        for _, arc_name in sorted(dist_files):
            logger.info("            * %s", arc_name)

        if missing_out_testcases and task_type != 'communication':
            pretty = ", ".join(sorted(missing_out_testcases)[:4])
            remain = len(missing_out_testcases) - 4
            if remain > 0:
                pretty += (", (%d more files)" % remain)
            logger.warning("missing output: %s", pretty)

        logger.info("=================%s============", "=" * len(name))

        logger.info("task parameters loaded")

        return db_task
