# -*- coding: utf-8 -*-
"""서식 재현 자체 점검(개발용 래퍼): hwpx_new.selfcheck 위에서 한 문서 또는 코퍼스를 돌린다."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hwpx_new.selfcheck import compare, fingerprints, key_of, report, run_selfcheck  # noqa: E402,F401


def run_one(template, out, name=None, with_class=False, md=False):
    r = run_selfcheck(template, out_dir=out, md=md, with_class=with_class)
    r['name'] = name or os.path.splitext(os.path.basename(template))[0]
    return r


def show(r, verbose=False):
    print(f"[{r['name']}] " + report(r, verbose))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('template')
    ap.add_argument('--out', default=None)
    ap.add_argument('-v', action='store_true')
    ap.add_argument('--cls', action='store_true')
    ap.add_argument('--md', action='store_true')
    a = ap.parse_args()
    out = a.out or os.path.join(os.getcwd(), '_out', 'rt')
    r = run_one(a.template, out, with_class=a.cls, md=a.md)
    show(r, a.v)


if __name__ == '__main__':
    main()
