"""Explicitly owned pytest observer. Never loaded by the product."""
import json
import os
from pathlib import Path

import pytest


def record(kind, **fields):
    with Path(os.environ['SHARDCAIRN_OWNED_LOG']).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'kind': kind, **fields},sort_keys=True)+'\n')


def pytest_runtest_logstart(nodeid, location):
    record('start',nodeid=nodeid)


@pytest.fixture(scope='session')
def x():
    record('setup',setup='x')
    yield []
    record('teardown',setup='x')
