#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""This script removes a statement to a specific task in the database.

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from future.builtins.disabled import *  # noqa
from future.builtins import *  # noqa

import argparse
import logging
import sys

from cms import utf8_decoder
from cms.db import SessionGen, Statement, Task

logger = logging.getLogger(__name__)


def remove_statement(task_name, language_code):
    logger.info("Removing the statement(language: %s) of task %s "
                "in the database.", language_code, task_name)

    with SessionGen() as session:
        task = session.query(Task)\
            .filter(Task.name == task_name).first()
        if not task:
            logger.error("No task named %s", task_name)
            return False

        statements = session.query(Statement)\
            .filter(Statement.language == language_code)\
            .filter(Statement.task == task)\
            .all()
        if not statements:
            logger.error("No statement exists with given language")
            return False

        for statement in statements:
            session.delete(statement)
        session.commit()

    logger.info("Statement removed.")
    return True


def main():
    """Parse arguments and launch process.

    """
    parser = argparse.ArgumentParser(description="Remove a statement from CMS.")
    parser.add_argument("task_name", action="store", type=utf8_decoder,
                        help="short name of the task")
    parser.add_argument("language_code", action="store", type=utf8_decoder,
                        help="language code of statement, e.g. en")

    args = parser.parse_args()

    success = remove_statement(args.task_name, args.language_code)
    return 0 if success is True else 1


if __name__ == "__main__":
    sys.exit(main())
