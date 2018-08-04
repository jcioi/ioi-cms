#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2010-2012 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2012 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2016-2018 wafrelka <wafrelka@gmail.com>
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
from __future__ import print_function
from __future__ import unicode_literals

from cms.grading.ScoreType import ScoreTypeGroup


# Dummy function to mark translatable string.
def N_(message):
    return message


class GroupMinTruncation(ScoreTypeGroup):
    """The score of a submission is the sum of the product of the
    minimum of the ranges with the multiplier of that range.

    Parameters are [[m, t, lo, hi, r], ... ].
    t: see ScoreTypeGroup.
    The score is calculated by (((y - lo) / (hi - lo)) ** r) * m,
        where y is min(max(x, lo), hi) and
        x is the minimum value among all outcomes.
    When lo = hi, the score is m if hi <= x, otherwise 0.

    """

    def get_public_outcome(self, outcome, parameter):
        """See ScoreTypeGroup."""
        lo, hi = parameter[2:4]
        if outcome >= hi:
            return N_("Correct")
        elif outcome <= lo:
            return N_("Not correct")
        else:
            return N_("Partially correct")

    def reduce(self, outcomes, parameter):
        """See ScoreTypeGroup."""
        lo, hi, r = parameter[2:5]
        d = hi - lo
        x = min(outcomes)
        if d == 0:
            if hi <= x:
                return 1
            return 0
        y = min(max(x, lo), hi)
        return ((float(y - lo) / (hi - lo)) ** r)
