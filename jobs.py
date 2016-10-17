
'''
Job resource input/output control using Redis as a locking layer

Copyright 2016 Josiah Carlson

This library licensed under the GNU LGPL v2.1

The initial library requirements and implementation were done for OpenMail LLC.
jobs.py (this library) was more or less intended to offer input and output
control like Luigi and/or Airflow (both Python packages), with fewer hard
integration requirements. In fact, jobs.py has been used successfully as part
of jobs running in a cron schedule via Jenkins, in build chains in Jenkins,
inside individual rpqueue tasks, and even inside individual Flask web requests
for some high-value data (jobs.py is backed by Redis, so job locking overhead
*can* be low, even when you need to keep data safe).

Source: https://github.com/josiahcarlson/jobs/
PyPI: https://pypi.python.org/pypi/jobspy/
Docs: https://pythonhosted.org/jobspy/

Features
========

Input/output locking on multiple *named* keys, called "inputs" and "outputs".

* All keys are case-sensitive
* Multiple readers on input keys
* Exclusive single writer on output keys (no readers or other writers)
* All inputs must have been an output previously
* Optional global and per-job history of sanitized input/output edges (enabled
  by default)
* Lock multiple inputs and outputs simultaneously, e.g. to produce outputs Y and
  Z, I need to consume inputs A, B, C.

How to use
==========

* Install jobs.py::

    $ sudo pip install jobspy

* Import jobs.py and configure the Redis connection *required* (maybe put this
  in some configuration file)::

    # in myjob.py or local_config.py
    import jobs
    jobs.CONN = redis.Redis(...)

* Use as a decorator on a function (must explicitly .start() the job, .stop()
  performed automatically if left uncalled)::

    # in myjob.py

    @jobs.resource_manager(['input1', 'input2'], ['output1', 'output2'], duration=300, wait=900)
    def some_job(job):
        job.add_inputs('input6', 'input7')
        job.add_outputs(...)
        job.start()
        # At this point, all inputs and outputs are locked according to the
        # locking semantics specified in the documentation.

        # If you call job.stop(failed=True), then the outputs will not be
        # "written"
        #job.stop(failed=True)
        # If you call job.stop(), then the outputs will be "written"
        job.stop()

        # Alternating job.stop() with job.start() is okay! You will drop the
        # locks in the .stop(), but will (try to) get them again with the
        # .start()
        job.start()

        # But if you need the lock for longer than the requested duration, you
        # can also periodically refresh the lock. The lock is only actually
        # refreshed once per second at most, and you can only refresh an already
        # started lock.
        job.refresh()

        # If an exception is raised and not caught before the decorator catches
        # it, the job will be stopped by the decorator, as though failed=True:
        raise Exception("Oops!")
        # will stop the job the same as
        #   job.stop(failed=True)
        # ... where the exception will bubble up out of the decorator.

* Or use as a context manager for automatic start/stop calling, with the same
  exception handling semantics as the decorator::

    def multi_step_job(arg1, arg2, ...):
        with jobs.ResourceManager([arg1], [arg2], duration=30, wait=60, overwrite=True) as job:
            for something in loop:
                # do something
                job.refresh()
            if bad_condition:
                raise Exception("Something bad happened, don't mark arg2 as available")
            elif other_bad_condition:
                # stop the job, not setting
                job.stop(failed=True)

        # arg2 should exist after it was an output, and we didn't get an
        # exception... though if someone else is writing to it immediately in
        # another call, then this may block...
        with jobs.ResourceManager([arg2], ['output.x'], duration=60, wait=900, overwrite=True):
            # something else
            pass

        # output.x should be written if the most recent ResourceManager stopped
        # cleanly.
        return

More examples
-------------

* Scheduled at 1AM UTC (5/6PM Pacific, depending on DST)::

        import datetime

        FMT = '%Y-%m-%d'

        def yesterday():
            return (datetime.datetime.utcnow().date() - datetime.timedelta(days=1)).strftime(FMT)

        @jobs.resource_manager([jobs.NG.reporting.events], (), 300, 900)
        def aggregate_daily_events(job):
            yf = yesterday()
            # outputs 'reporting.events_by_partner.YYYY-MM-DD'
            # we can add job inputs and outputs inside a decorated function before
            # we call .start()
            job.add_outputs(jobs.NG.reporting.events_by_partner[yf])

            job.start()
            # actually aggregate events

* Scheduled the next day around the time when we expect upstream reporting to
  be available::

        @jobs.resource_manager((), (), 300, 900)
        def fetch_daily_revenue(job):
            yf = yesterday()
            job.add_outputs(jobs.NG.reporting.upsteam_revenue[yf])

            job.start()
            # actually fetch daily revenue

* Executed downstream of fetch_daily_revenue()::

        @jobs.resource_manager((), (), 300, 900)
        def send_reports(job):
            yf = yesterday()

            # having jobs inputs here ensures that both of the *expected* upstream
            # flows were *actual*
            job.add_inputs(
                jobs.NG.reporting.events_by_partner[yf],
                jobs.NG.reporting.upstream_revenue[yf]
            )
            job.add_outputs(jobs.NG.reporting.report_by_partner[yf])

            job.start()
            # inputs are available, go ahead and generate the reports!

* And in other contexts...::

        def make_recommendations(partners):
            yf = yesterday()
            for partner in partners:
                with jobs.ResourceManager([jobs.NG.reporting.report_by_partner[yf]],
                        [jobs.NG.reporting.recommendations_by_partner[yf][partner]], 300, 900):
                    # job is already started
                    # generate the recommendations for the partner
                    pass


Configuration options
=====================

All configuration options are available as options on the jobs.py module itself,
though you *can* override the connection explicitly on a per-job basis. See the
'Connection configuration' section below for more details.::

    # The Redis connection, REQUIRED!
    jobs.CONN = redis.Redis()

    # Sets a prefix to be used on all keys stored in Redis (optional)
    jobs.GLOBAL_PREFIX = ''

    # Keep a sanitized ZSET of inputs and outputs, available for traversal
    # later. Note: sanitization runs the following on all edges before storage:
    #   edge = re.sub('[0-9][0-9-]*', '*', edge)
    # ... which allows you to get a compact flow graph even in cases where you
    # have day-parameterized builds.
    jobs.GRAPH_HISTORY = True

    # To use a logger that doesn't print to standard output, set the logging
    # object at the module level (see below). By default, the built-in "default
    # logger" prints to standard output.
    jobs.DEFAULT_LOGGER = logging.getLogger(...)

Using jobs.py with a custom Redis configuration
===============================================

If you would like to use jobs.py as a script (for the convenient command-line
options), you need to create a wrapper module, which can also act as your
general configuration updates for jobs.py (hack because I needed to release
this as open-source before the end of summer)::


    # myjobs.py
    import jobs
    jobs.CONN = ...
    jobs.DEFAULT_LOGGER = ...
    jobs.GLOBAL_PREFIX = ...
    jobs.GRAPH_HISTORY = ...

    from jobs import *

    if __name__ == '__main__':
        main()

Then you can use this as::

    $ python myjobs.py --help


And you can use ``myjobs.py`` everywhere, which will have all of your
configuration handled.::

    # daily_report.py
    import myjobs

    @myjobs.resource_manager(...)
    def daily_reporting(job, ...):
        # exactly the same as before.

'''

from __future__ import print_function

import argparse
import atexit
import binascii
from collections import defaultdict, deque
from datetime import datetime, date
import functools
from hashlib import sha1
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import traceback

import redis.exceptions

_all = set(globals())

VERSION = '0.26.0'

# user-settable configuration
CONN = None
GLOBAL_PREFIX = ''
GRAPH_HISTORY = True
DEFAULT_LOGGER = None # actually set below, see BullshitLog()
# end user-settable configuration

EDGE_RE = re.compile('[0-9][0-9-]*')
TS_RE = re.compile('^(\d{9,}(?:[.]\d*)?)$')
DT_RE = re.compile('^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2})(?::(\d{2})(?:[.](?:\d+)?)?)?)?$')
EPOCH = datetime(1970, 1, 1)
PY3K = sys.version_info >= (3, 0, 0)
TEXT_TYPE = str if PY3K else unicode
LOCKED = set()
AUTO_REFRESH = set()
REFRESH_THREAD = None
_GHD = object()


class ResourceUnavailable(Exception):
    '''
    Raised when one or more inputs are unavailable, or when one or more outputs
    are already locked.
    '''

class NG(object):
    '''
    Convenience object for generating names:

    >>> str(NG.foo.bar.baz[1].goo)
    foo.bar.baz.1.goo
    '''
    __slots__ = '_name',
    def __init__(self, start=''):
        self._name = start.strip('.')
    def __getitem__(self, item):
        return self.__class__('%s.%s'%(self._name, item))
    __getattr__ = __getitem__
    def __call__(self, item):
        return self[item]
    def __str__(self):
        return self._name
    def __repr__(self):
        return repr(str(self))
    def __eq__(self, other):
        return str(self) == str(other)
    def __hash__(self):
        return hash(str(self))

TYPE_NG = NG
NG = NG()

@atexit.register
def _signal_handler(*args, **kwargs):
    for m in list(LOCKED):
        m.stop(failed=True, shutting_down=True)
    if args:
        # call the old handler, as necessary
        if OLD_SIGNAL:
            OLD_SIGNAL(*args, **kwargs)
        raise SystemExit()

# register new signal handler, and keep reference to the old one (if any)
OLD_SIGNAL = signal.signal(signal.SIGTERM, _signal_handler)

ATEXIT_SET = False
SIGNAL_SET = False
OLD_SIGNAL = None

def handle_auto_shutdown():
    global ATEXIT_SET, SIGNAL_SET, OLD_SIGNAL
    if not ATEXIT_SET:
        ATEXIT_SET = atexit.register(_signal_handler)

    if not SIGNAL_SET and isinstance(threading.currentThread(), threading._MainThread):
        SIGNAL_SET, OLD_SIGNAL = True, signal.signal(signal.SIGTERM, _signal_handler)

def resource_manager(inputs, outputs, duration, wait=None, overwrite=True,
        conn=None, graph_history=_GHD, suffix=None):
    '''
    Arguments:
        * inputs - the list of inputs that need to exist to start the job
        * outputs - the list of outputs to produce
        * duration - how long you want to lock the inputs and outputs from
            modification from other jobs
        * wait=None - how long to wait for inputs to be available and for
            when overwrite=True, how long to wait for other writers to
            finish writing
        * overwrite=False - whether to overwrite a pre-existing output if it
            already exists
        * conn=None - a Redis connection to use (provide here, or when
            calling .start())
        * graph_history=True - whether to keep history of graph edges
    '''
    def wrap(fcn):
        @functools.wraps(fcn)
        def call(*args, **kwargs):
            manager = ResourceManager(inputs, outputs, duration, wait,
                overwrite, conn, graph_history, _caller_name(fcn), suffix)
            ex = False
            try:
                return fcn(manager, *args, **kwargs)
            except:
                ex = True
                raise
            finally:
                manager.stop(failed=ex)
        return call
    return wrap


class ResourceManager(object):
    def __init__(self, inputs, outputs, duration, wait=None, overwrite=True,
            conn=None, graph_history=_GHD, identifier=None, suffix=None):
        '''
        Arguments:
            * inputs - the list of inputs that need to exist to start the job
            * outputs - the list of outputs to produce
            * duration - how long you want to lock the inputs and outputs from
                modification from other jobs
            * wait=None - how long to wait for inputs to be available and for
                when overwrite=True, how long to wait for other writers to
                finish writing
            * overwrite=False - whether to overwrite a pre-existing output if it
                already exists
            * conn=None - a Redis connection to use (provide here, or when
                calling .start())
            * graph_history=True - whether to keep history of graph edges
        '''
        assert isinstance(inputs, (list, tuple, set)), inputs
        assert isinstance(outputs, (list, tuple, set)), outputs
        self.inputs = list(inputs)
        self.outputs = list(outputs)
        self.duration = max(duration, 0)
        self.wait = max(wait or 0, 0)
        self.overwrite = overwrite
        self.last_refreshed = None
        self.prefix_identifier(identifier or _caller_name(_get_caller()))
        self.conn = conn
        self.graph_history = GRAPH_HISTORY if graph_history is _GHD else graph_history
        self.auto_refresh = None
        self._lock = threading.RLock()

        # This is a symptom of bad design. But it exists because I need the
        # functionality. Practicality beats purity.
        self.suffix = suffix

    def add_inputs(self, *inputs):
        '''
        Adds inputs before the job has started.
        '''
        if self.is_running:
            raise RuntimeError("Can't add inputs after starting")
        self.inputs.extend(inputs)

    def add_outputs(self, *outputs):
        '''
        Adds outputs before the job as started.
        '''
        if self.is_running:
            raise RuntimeError("Can't add outputs after starting")
        self.outputs.extend(outputs)

    @property
    def identifier(self):
        '''
        Property to allow for .suffix to be set after job creation.
        '''
        s = (self.suffix or '').strip('.')
        s = ('.' + s) if s else ''
        return str(self._identifier) + s

    def prefix_identifier(self, base_identifier):
        '''
        Will set a new identifier derived from the provided base_identifier by
        adding a ``.<random string>`` suffix. Ensures that otherwise identical
        names from job runners don't get confused about who is running what.

        The final identifier to be used will be the base_identifier provided here,
        a 48 bit random numeric identifier, followed by an optional .suffix:
        ``<base_identifier>.<random string>[.suffix]``
        '''
        if self.is_running:
            raise RuntimeError("Can't set the identifier after starting")

        # generate a 48 bit identifier using os.urandom, use decimal not hex
        self._identifier = NG(base_identifier)[int(binascii.hexlify(os.urandom(6)), 16)]

    def can_run(self, conn=None):
        '''
        Will return whether the job can be run immediately, but does not start
        the job.
        '''
        conn = conn or self.conn or CONN
        if not conn:
            raise RuntimeError("Cannot start a job without a connection to Redis!")
        if self.is_running:
            raise RuntimeError("Already started!")
        return _run_if_possible(conn, self.inputs, self.outputs, self.identifier, 0, self.overwrite)

    def refresh(self, lost_lock_fail=False, **kwargs):
        '''
        For jobs that may take longer than the provided "duration", you should
        .refresh() periodically to ensure that someone doesn't overwrite your
        inputs or outputs.

        Arguments:
            * lock_lost_fail - fail if any lock was lost, and raise an exception

        Note: will only refresh at most once/second.

        '''
        inside_auto_refresh = kwargs.get('inside_auto_refresh')
        with self._lock:
            if self.is_running and time.time() - self.last_refreshed > 1:
                DEFAULT_LOGGER.debug("Refreshing job locks")
                lost = _refresh_job(self.conn, self.inputs, self.outputs,
                    self.identifier, self.duration, self.overwrite)

                if lost.get('err') or lost.get('temp'):
                    if lost_lock_fail:
                        auto = inside_auto_refresh and self.auto_refresh
                        self.stop(failed=True)
                        if not auto:
                            raise ResourceUnavailable(lost.get('err'))

                    DEFAULT_LOGGER.warning("Lock(s) lost due to timeout: %r", lost)

                self.last_refreshed = time.time()
                return lost

    def start(self, conn=None, auto_refresh=None, **kwargs):
        '''
        Will attempt to start the run within self.wait seconds, waiting for:
         * inputs to be available
         * outputs to not be locked for read or write
         * outputs to not exist when ``overwrite=False``

        If unable to start within self.wait seconds, will raise an exception
        showing the bad/missing resources.

        If ``auto_refresh`` is provided, and can be considered boolean ``True``,
        a background thread will try to call ``job.refresh()`` on this lock
        once per second, until the job is explicitly stopped with ``.stop()``
        or the process exits, whichever comes first.
        '''
        try:
            with self._lock:
                return self._start(conn, auto_refresh, **kwargs)
        finally:
            if self.is_running and self.auto_refresh:
                _start_auto_refresh(self)

    def _start(self, conn, auto_refresh, **kwargs):
        self.conn = conn or self.conn or CONN
        if not self.conn:
            raise RuntimeError("Cannot start a job without a connection to Redis!")

        if self.is_running:
            return

        if not self.identifier or not isinstance(self.identifier, (str, TYPE_NG)):
            raise RuntimeError("Can't start job without a valid identifier")

        if LOCKED and not kwargs.pop('i_really_know_what_i_am_doing_dont_warn_me', None):
            DEFAULT_LOGGER.warning("Trying to start job while another job has "
                "already started in the same process is a recipe for deadlocks. "
                "You should probably stop doing that unless you know what you "
                "are doing.")

        result = {'ok': False, 'err': {}}

        DEFAULT_LOGGER.info("Trying to start job with inputs: %r and outputs: %r",
            self.inputs, self.outputs)

        def tr():
            DEFAULT_LOGGER.debug("Trying to start job")
            result = _run_if_possible(self.conn, self.inputs, self.outputs,
                self.identifier, self.duration, self.overwrite,
                history=self.graph_history)

            if result['ok']:
                DEFAULT_LOGGER.info("Starting job")
                self.last_refreshed = time.time()
                self.auto_refresh = bool(auto_refresh)
                LOCKED.add(self)
                return result, True
            else:
                DEFAULT_LOGGER.debug("Failed to start job: %r", result)
            return result, False

        # Report that we are still waiting after waiting for 1 second, the first
        # time.
        last_reported = time.time() - 29
        stop_waiting = time.time() + max(self.wait or 0, 0)
        while time.time() < stop_waiting:
            result, s = tr()
            if s:
                return self

            if 'output_exists' in result['err']:
                # We can't recover from "output exists" errors without
                # overwriting the output, and we only get the error when we
                # can't overwrite the output. Don't bother waiting any longer.
                break

            # Only print a message reporting the waiting status once every 30
            # seconds
            if time.time() - last_reported >= 30:
                DEFAULT_LOGGER.info("Still waiting to start job... %r", result['err'])
                last_reported = time.time()

            # Wait up to 10ms between tests
            time.sleep(min(max(stop_waiting - time.time(), 0), .01))

        # try one more time before bailing out...
        result, s = tr()
        if s:
            return self

        DEFAULT_LOGGER.info("Failed to start job: %r", result['err'])
        raise ResourceUnavailable(result['err'])

    @property
    def is_running(self):
        '''
        Returns whether or not the job is running.
        '''
        return self.last_refreshed is not None

    def stop(self, failed=False, shutting_down=False):
        '''
        Stops a job if running. If the optional "failed" argument is true,
        outputs will not be set as available.
        '''
        if self.is_running:
            with self._lock:
                if not self.is_running:
                    # another thread could have changed the status
                    return
                failed = bool(failed)
                DEFAULT_LOGGER.info("Stopping job failed = %r", bool(failed))
                if shutting_down:
                    DEFAULT_LOGGER.warning("Stopping job as part of atexit/signal handler exit")
                try:
                    _finish_job(self.conn, self.inputs, self.outputs, self.identifier,
                        failed=failed)
                finally:
                    self.last_refreshed = None
                    self.auto_refresh = None
                    LOCKED.discard(self)
                    AUTO_REFRESH.discard(self)

    def __enter__(self):
        return self.start(self.conn)

    def __exit__(self, typ, value, tb):
        self.stop(bool(typ or value or tb))


def _create_outputs(outputs, conn=None, identifier=None, suffix=None):
    '''
    Sometimes you just need outputs to exist. These creates outputs.
    '''
    identifier = NG(identifier or _caller_name(_get_caller()))
    if suffix:
        identifier = identifier[suffix]
    (conn or CONN).mset(**{o:identifier for o in outputs})


def _force_unlock(inputs, outputs, conn=None):
    '''
    Sometimes you just need to unlock some inputs and outputs. This unlocks
    inputs and outputs.
    '''
    inputs = [i if i.startswith('ilock:') else ('ilock:' + i) for i in inputs]
    outputs = [o if o.startswith('olock:') else ('olock:' + o) for o in outputs]
    io = inputs + outputs
    if io:
        return (conn or CONN).delete(*io)


def _check_inputs_and_outputs(fcn):
    @functools.wraps(fcn)
    def call(conn, inputs, outputs, identifier, *a, **kw):
        assert isinstance(inputs, (list, tuple, set)), inputs
        assert isinstance(outputs, (list, tuple, set)), outputs
        assert '' not in inputs, inputs
        assert '' not in outputs, outputs
        # this is for actually locking inputs/outputs
        inputs, outputs = list(map(str, inputs)), list(map(str, outputs))
        locks = inputs + [''] + outputs

        if kw.pop('history', None):
            igraph = [EDGE_RE.sub('*', inp) for inp in inputs]
            ograph = [EDGE_RE.sub('*', out) for out in outputs]
            graph_id = EDGE_RE.sub('*', str(identifier))
            graph = igraph + [''] + ograph + ['', graph_id]
            if all(x.startswith('test.') for x in igraph + ograph):
                graph = ['', '']
        else:
            graph = ['', '']

        return fcn(conn, locks, graph, str(identifier), *a, **kw)
    return call

def _fix_err(result):
    # Translate list of error types to a dictionary of grouped errors.
    def _fix(d):
        err = defaultdict(list)
        for why, key in d:
            err[why].append(key)
        return dict(err)

    if result.get('err'):
        result['err'] = _fix(result['err'])
    if result.get('temp'):
        result['temp'] = _fix(result['temp'])
    return result

@_check_inputs_and_outputs
def _run_if_possible(conn, inputs_outputs, graph, identifier, duration, overwrite):
    '''
    Internal call to run a job if possible, only acquiring the locks if all are
    available.
    '''
    return _fix_err(json.loads(_run_if_possible_lua(conn, keys=inputs_outputs,
        args=[json.dumps({
            'prefix': GLOBAL_PREFIX,
            'id': identifier,
            'now': time.time(),
            'duration': duration,
            'overwrite': bool(overwrite),
            'refresh': False,
            'edges': graph})]
    ).decode('latin-1')))

@_check_inputs_and_outputs
def _refresh_job(conn, inputs_outputs, graph, identifier, duration, overwrite):
    '''
    Internal call to refresh a job that already has a lock.
    '''
    return _fix_err(json.loads(_run_if_possible_lua(conn, keys=inputs_outputs,
        args=[json.dumps({
            'prefix': GLOBAL_PREFIX,
            'id': identifier,
            'now': time.time(),
            'duration': duration,
            'overwrite': bool(overwrite),
            'refresh': True,
            'edges': []})]
    ).decode('latin-1')))

@_check_inputs_and_outputs
def _finish_job(conn, inputs_outputs, graph, identifier, failed=False):
    '''
    Internal call to finish a job.
    '''
    _finish_job_lua(conn, keys=inputs_outputs,
        args=[json.dumps([identifier, time.time(), not failed, GLOBAL_PREFIX])]
    )

def _caller_name(code):
    if callable(code):
        code = code.__code__
    return "%s:%s"%(code.co_filename, code.co_name)

def _get_caller():
    return sys._getframe(2).f_code

NO_SCRIPT_MESSAGES = ['NOSCRIPT', 'No matching script.']
def _script_load(script):
    '''
    Re-borrowed from:
    https://github.com/josiahcarlson/rom/blob/master/rom/util.py
    '''
    script = script.encode('utf-8') if isinstance(script, TEXT_TYPE) else script
    sha = [None, sha1(script).hexdigest()]
    def call(conn, keys=[], args=[], force_eval=False):
        keys = tuple(keys)
        args = tuple(args)
        if not force_eval:
            if not sha[0]:
                try:
                    # executing the script implicitly loads it
                    return conn.execute_command(
                        'EVAL', script, len(keys), *(keys + args))
                finally:
                    # thread safe by re-using the GIL ;)
                    del sha[:-1]

            try:
                return conn.execute_command(
                    "EVALSHA", sha[0], len(keys), *(keys+args))

            except redis.exceptions.ResponseError as msg:
                if not any(msg.args[0].startswith(nsm) for nsm in NO_SCRIPT_MESSAGES):
                    raise

        return conn.execute_command(
            "EVAL", script, len(keys), *(keys+args))

    return call

_run_if_possible_lua = _script_load('''
-- KEYS - list of inputs and outputs to lock, separated by an empty string:
--        {'input', '', 'output'}
-- ARGV - {json.dumps({
--     prefix: key_prefix,
--     id: identifier,
--     now: timestamp,
--     duration: lock_duration_in_seconds,
--     overwrite: overwrite_as_boolean,
--     refresh: refresh_as_boolean,
--       -- If there is a graph history, these edges represent them.
--     edges: [inputs, '', outputs, '', graph_id]
-- })}

local args = cjson.decode(ARGV[1])
local failures = {}
local temp_failures = {}
local is_input = true
local is_refresh = args.refresh
local graph = args.edges
local prefix = args.prefix

redis.call('zremrangebyscore', prefix .. 'jobs:running', '-inf', args.now)

-- make sure input keys are available and output keys are not yet written
for i, kk in ipairs(KEYS) do
    local exists = redis.call('exists', prefix .. kk) == 1

    local olock = redis.call('get', prefix .. 'olock:' .. kk)
    olock = olock and olock ~= args.id

    -- always clean out the input lock ZSET
    local ilk = prefix .. 'ilock:' .. kk
    redis.call('zremrangebyscore', ilk, 0, args.now)
    local ilock = redis.call('exists', ilk) == 1

    if kk == '' then
        is_input = false

    elseif is_input then
        if olock or not exists then
            if is_refresh then
                -- lost our input lock
                table.insert(failures, {'input_lock_lost', kk})

            else
                -- input doesn't exist, or input exists but someone is writing to it
                table.insert(failures, {'input_missing', kk})
            end

        elseif is_refresh and not redis.call('zscore', ilk, args.id) then
            -- lost our input lock, report the temp failure
            table.insert(temp_failures, {'input_lock_lost', kk})
        end

    else
        if exists and not args.overwrite then
            -- exists, can't overwrite
            table.insert(failures, {'output_exists', kk})

        elseif olock then
            -- the output has been locked by another process
            table.insert(failures, {'output_locked', kk})

        elseif ilock then
            -- the output file is being read by another process
            table.insert(failures, {'output_used', kk})

        elseif is_refresh and not redis.call('get', prefix .. 'olock:' .. kk) then
            -- lost our output lock, reacquire it
            table.insert(temp_failures, {'output_lock_lost', kk})
        end
    end
end

if #failures > 0 then
    return cjson.encode({ok=false, err=failures, temp=temp_failures})
end
if args.duration == 0 then
    return cjson.encode({ok=true})
end

is_input = true
for i, kk in ipairs(KEYS) do
    if kk == '' then
        is_input = false
    elseif is_input then
        local ilock = prefix .. 'ilock:' .. kk

        -- add lock for this call
        redis.call('zadd', ilock, args.now + args.duration, args.id)
        if redis.call('ttl', ilock) < args.duration then
            -- ensure that the locks last long enough
            redis.call('expire', ilock, args.duration)
        end

    else
        -- lock the output keys to ensure that no one is concurrently writing
        local olock = prefix .. 'olock:' .. kk

        redis.call('setex', olock, args.duration, args.id)
    end
end

redis.call('zadd', prefix .. 'jobs:running', args.now + args.duration, args.id)
redis.call('setex', prefix .. 'jobs:running:' .. args.id, args.duration, cjson.encode(KEYS))

-- keep a record of our input/output graph
if not is_refresh then
    is_input = true
    local id = table.remove(graph)
    table.remove(graph)
    for i, kk in ipairs(graph) do
        if kk == '' then
            is_input = false
        elseif is_input then
            redis.call('zadd', prefix .. 'jobs:graph:input', args.now, kk .. ' -> ' .. id)
        else
            redis.call('zadd', prefix .. 'jobs:graph:output', args.now, id .. ' -> ' .. kk)
        end
    end
end

if #temp_failures > 0 then
    return cjson.encode({ok=true, temp=temp_failures})
end
return cjson.encode({ok=true})
''')

_finish_job_lua = _script_load('''
-- KEYS - list of inputs and outputs to finish the job for, same semantics as
--        _run_if_possible_lua()
-- ARGV - {json.dumps([identifier, now, success, prefix])}

local args = cjson.decode(ARGV[1])
local is_input = true
local prefix = args[4]

for i, kk in ipairs(KEYS) do
    if kk == '' then
        is_input = false

    elseif is_input then
        local ilock = prefix .. 'ilock:' .. kk
        -- clean out old input locks
        redis.call('zremrangebyscore', ilock, 0, args[2])
        redis.call('zrem', ilock, args[1])

    else
        -- clean out old locks that have our identifier
        local olock = prefix .. 'olock:' .. kk
        if redis.call('get', olock) == args[1] then
            redis.call('del', olock)
        end

        if args[3] then
            -- set the output key to the identifier to signify the job is done
            redis.call('set', prefix .. kk, args[1])
        end
    end
end

redis.call('zrem', prefix .. 'jobs:running', args[1])
redis.call('del', prefix .. 'jobs:running:' .. args[1])
''')

_get_job_info_lua = _script_load('''
-- ARGV - {json.dumps([now, prefix])}

local args = cjson.decode(ARGV[1])
local prefix = args[2]
local jobs = {}
local jobl = redis.call('zrangebyscore', prefix .. 'jobs:running', args[1], 'inf', 'withscores')
for i=1, #jobl, 2 do
    local job = {}
    job.id = jobl[i]
    job.exptime = tonumber(jobl[i+1])
    job.io = cjson.decode(redis.call('get', prefix .. 'jobs:running:' .. jobl[i]))
    table.insert(jobs, job)
end

return cjson.encode(jobs)
''')


class BullshitLog(object):
    level = 20
    def setLevel(self, level):
        self.level = level
    def getEffectiveLevel(self):
        return self.level

for name in 'debug info warning error critical exception'.split():
    def maker(name):
        my_level = getattr(logging, name.upper()) if name != 'exception' else logging.ERROR
        altname = (name if name != 'exception' else 'error').upper()
        def _log(self, msg, *args, **kwargs):
            exc = kwargs.pop('exc_info', None) or name == 'exception'
            tb = ('\n' + traceback.format_exc().strip()) if exc else ''
            if args:
                try:
                    msg = msg % args
                except:
                    self.exception(
                        "Exception raised while formatting message:\n%s\n%r",
                        msg, args)
            msg += tb
            # todo: check level before printing
            if self.level <= my_level:
                print("%s %s %s"%(time.asctime(), altname, msg))
        _log.__name__ = name
        return _log

    setattr(BullshitLog, name, maker(name))

DEFAULT_LOGGER = BullshitLog()

def _start_auto_refresh(job, lock=threading.Lock()):
    '''
    Internal implementation detail; I will auto-refresh job locks in a
    background thread if you ask.
    '''
    global REFRESH_THREAD
    rq = AUTO_REFRESH
    def refresh():
        while True:
            # find the next job to be refreshed
            with lock:
                job = None
                jobs = list(rq)
                times = [j.last_refreshed for j in jobs]
                for i, ti in enumerate(times):
                    if ti is not None:
                        if job is not None:
                            if ti < times[job]:
                                job = ti
                        else:
                            job = ti
                    else:
                        rq.discard(jobs[i])

                # no more running jobs, bail
                if not rq:
                    break

                last = times[job]
                job = jobs[job]

            # wait a little bit if necessary...
            next = last + 1
            wait = next - time.time()
            if wait > 0:
                time.sleep(min(wait, .1))
                # check again
                continue

            try:
                if job.auto_refresh:
                    # refresh as necessary
                    job.refresh(inside_auto_refresh=True)
            except:
                DEFAULT_LOGGER.execption("Exception while automatically refreshing")

            # remove as necessary
            with lock:
                if job.last_refreshed is None or not job.auto_refresh:
                    rq.discard(job)

    with lock:
        if job.last_refreshed is not None and job.auto_refresh:
            rq.add(job)
        if rq and (not REFRESH_THREAD or not REFRESH_THREAD.is_alive()):
            REFRESH_THREAD = threading.Thread(target=refresh)
            REFRESH_THREAD.setDaemon(1)
            REFRESH_THREAD.start()


DELTA_TIMES = [
    ('days', 86400),
    ('hours', 3600),
    ('minutes', 60),
    ('seconds', 1),
]

def _delta_to_time_string(delta):
    for name, secs in DELTA_TIMES:
        if delta >= secs:
            break

    return "%.2f %s"%(max(delta, 0), name)

def get_jobs(conn):
    '''
    Gets the list of currently running jobs, their inputs, and their outputs.
    '''
    jobs = json.loads(_get_job_info_lua(conn, keys=(), args=[json.dumps([time.time(), GLOBAL_PREFIX])]))
    if not jobs:
        jobs = []
    for job in jobs:
        io = job.pop('io')
        sep = io.index('')
        job['inputs'] = io[:sep]
        job['outputs'] = io[sep+1:]
    return jobs

def show_jobs(conn):
    '''
    Prints information about currently running jobs.
    '''
    jobs = get_jobs(conn)
    if not jobs:
        print("[]")
        return
    print("[")
    last = len(jobs) - 1
    for i, job in enumerate(jobs):
        print("", json.dumps(job), end='')
        print("," if i != last else '')
    print("]")

def _fix_edge(e):
    return EDGE_RE.sub('*', e)



def _to_ts(val):
    if isinstance(val, (int, float)):
        return val
    elif isinstance(val, (datetime, date)):
        return (val-EPOCH).total_seconds()
    v = TS_RE.match(val)
    if v:
        return float(v.group(0))
    v = DT_RE.match(val)
    if v:
        # get all of the passed datetime pieces, don't worry about them being
        # terribly valid, the datetime constructor will handle that ;)
        v = list(filter(None, v.groups()))
        if len(v) == 7:
            # truncate to microseconds as necessary
            v[6] = v[6][:6]
            # extend to microseconds as necessary
            v[6] += (6 - len(v[6])) * '0'
        v = list(map(int, v))
        dt = datetime(*v)
        return (dt-EPOCH).total_seconds()
    raise Exception("Value %r is not a timestamp, datetime, or date"%(val,))

def edges(conn, before=None, after=None):
    '''
    Returns (inputs, outputs). Inputs are sorted by prefix, outputs are sorted
    by suffix.

    The `before` and `after` arguments

    '''
    io = []
    for key in ['jobs:graph:input', 'jobs:graph:output']:
        l = '-inf' if after is None else _to_ts(after)
        h = 'inf' if before is None else _to_ts(before)

        iol = conn.zrangebyscore(key, l, h)
        io.append(list(sorted(set(_fix_edge(e) for e in iol))))
    return io

def get_job_io(identifier, conn=None):
    it = (conn or CONN).get('jobs:running:' + identifier)
    if it:
        it = json.loads(it)
        inputs = it[:it.index('')]
        del it[:len(inputs) + 1]
        return inputs, it
    return [], []

def print_io(inputs, outputs):
    if inputs:
        print(time.asctime(), "Inputs:", inputs)
    if outputs:
        print(time.asctime(), "Outputs:", outputs)
    if not inputs and not outputs:
        print(time.asctime(), "No inputs/outputs?")

#--------------------------- graph traversal stuff ---------------------------

def _filter_right(e, suf):
    suf = ' -> ' + suf
    return [ei.partition(' -> ')[0] for ei in e if ei.endswith(suf)]

def _filter_left(e, pre):
    pre = pre + ' -> '
    return [ei.partition(' -> ')[-1] for ei in e if ei.startswith(pre)]

def _produces(outputs, edge):
    return _filter_right(outputs, _fix_edge(edge))

def _consumes(inputs, edge):
    return _filter_left(inputs, _fix_edge(edge))

def _inputs(inputs, job):
    return _filter_right(inputs, _fix_edge(job))

def _outputs(outputs, job):
    return _filter_left(outputs, _fix_edge(job))

ARROW = ' -> '

def print_edge(left, right, s):
    if not right:
        left, _, right = left.partition(ARROW)
    if not left.strip('*.') or not right.strip('*.'):
        return
    print('"%s" -> "%s"%s'%(left, right, s))


def _traverse(out, je, s, conn=None, depth=-1, before=None, after=None):
    inputs, outputs = edges(conn or CONN, before=before, after=after)
    inputs.sort()
    outputs.sort()

    known = set([je])
    q = deque([(je, depth)])

    # out/downstream is all stuff leading from left to right.
    # in/upstream is all stuff leading from right to left.
    all_edges = inputs + outputs

    if out:
        # outputs, so downstream
        while q:
            it, d = q.popleft()
            dm1 = d-1
            for outp in _outputs(all_edges, it):
                print_edge(it, outp, s)
                if outp not in known:
                    known.add(outp)
                    if d:
                        q.append((outp, dm1))

    else:
        # inputs, so upstream
        while q:
            it, d = q.popleft()
            dm1 = d-1
            for inp in _inputs(all_edges, it):
                print_edge(inp, it, s)
                if inp not in known:
                    known.add(inp)
                    if d:
                        q.append((inp, dm1))

#-------------------------- for calling as a script --------------------------

def handle_args(args):
    if args.yes_history is not None:
        global GRAPH_HISTORY
        GRAPH_HISTORY = args.yes_history

    if args.start:
        assert args.wait is not None and args.wait > 0, "--wait > 0 required when using --start"
        assert args.duration is not None and args.duration > 0, "--duration > 0 required when using --start"
        overwrite = True if args.yes_overwrite is None else args.yes_overwrite

        job = ResourceManager(args.inputs, args.outputs, args.duration, args.wait,
            overwrite, graph_history=GRAPH_HISTORY)
        job._identifier = args.start
        job.start()
        # This has to be dirty, because we want the job to be locked after we
        # exit the process if it was acquired.
        LOCKED.discard(job)

    if args.stop:
        print(time.asctime(), "Finishing the job:", args.stop)
        inputs, outputs = get_job_io(args.stop)
        print_io(inputs, outputs)
        _create_outputs(outputs)
        _force_unlock(inputs, [])
        print(time.asctime(), "Finished.")

    if args.stop_failed:
        print(time.asctime(), "Failing the job:", args.stop_failed)
        inputs, outputs = get_job_io(args.stop_failed)
        print_io(inputs, outputs)
        _force_unlock(inputs, outputs)
        print(time.asctime(), "Failed.")

    if args.unlock_inputs:
        print(time.asctime(), "Unlocking inputs:", args.unlock_inputs)
        _force_unlock(args.unlock_inputs, [])
        print(time.asctime(), "Unlocked.")

    if args.create_outputs:
        print(time.asctime(), "Creating outputs:", args.create_outputs)
        _create_outputs(args.create_outputs)
        print(time.asctime(), "Created")
        args.unlock_outputs.extend(args.create_outputs)

    if args.unlock_outputs:
        print(time.asctime(), "Unlocking outputs:", args.unlock_outputs)
        _force_unlock([], args.unlock_outputs)
        print(time.asctime(), "Unlocked.")

    gout = args.graphviz and (args.upstream or args.downstream or args.all)

    s = ''
    if gout:
        print('digraph {\nrankdir=LR\n')
        s = ';'

    if args.upstream:
        _traverse(False, args.upstream, s, depth=args.depth, after=args.after, before=args.before)

    if args.downstream:
        _traverse(True, args.downstream, s, depth=args.depth, after=args.after, before=args.before)

    skip = "copy_data.py:copy_table.*"
    if args.all:
        inputs, outputs = edges(CONN, after=args.after, before=args.before)
        for edge in inputs:
            if edge.endswith(skip):
                continue
            print_edge(edge, None, s)
        skip += ' '
        skip2 = '/' + skip
        for edge in outputs:
            if edge.startswith(skip) or edge.startswith(skip2):
                continue
            print_edge(edge, None, s)

    if gout:
        print('}')

    if not len(sys.argv):
        show_jobs(CONN)

#------------------------ set up the argument parser -------------------------

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog='''
This module intends to offer the ability to lock inputs and outputs in the
context of data flows, data pipelines, etl flows, job flows, and general
multi-locking.


If run as a script, this module will print the list of currently known running
jobs if run without arguments. Other arguments can do a variety of convenient
things.

$ python {0}


Want to know all downstream outputs and jobs from an input, output, or
identifier?

$ python {0} --downstream input
$ python {0} --downstream output
$ python {0} --downstream identifier


Want to know what jobs and inputs are upstream from a given input, output, or
identifier?

$ python {0} --upstream input
$ python {0} --upstream output
$ python {0} --upstream identifier


Want to limit how deep the graph traversal goes?

$ python {0} --upstream output --depth 5
$ python {0} --upstream input --depth 25
$ python {0} --upstream input --depth -1 # the default, unlimited


Want to limit your scan to jobs before, after, or between a timestamp, datetime,
and/or date?

$ python {0} --downstream <...> --after 2016-09-01 --before "2016-09-01 05:23:44"
$ python {0} --upstream <...> --after 1473739917  --before 1473825618.18592
$ python {0} --all <...> --after 2016-09-01 --before 1473825618.18592


Note when using --start and --yes-history:
    Edge components (the job identifier, inputs, and outputs) are all "cleaned"
    prior to insertion into edge history. "Cleaning" involves replacing all
    substrings matching this regular expression: '[0-9][0-9-]*' with an asterisk
    '*'. So for a job identifier 'foo.bar.2016-09-01', with input 'blah.6213'
    and output 'other.1456282826', sanitized edges would be:

    'blah.* -> foo.bar.*'
    'foo.bar.* -> other.*'

'''.format(sys.argv[0] or 'jobs.py'))

#-------------------------- what and how to output ---------------------------

parser.add_argument(
    '--graphviz',
    action='store_true',
    default=False,
    help="If edges are to be output, produce them in a format meant for graphviz 'dot' command"
)

group = parser.add_mutually_exclusive_group()
group.add_argument(
    '--display-all-edges-ever-known',
    '--all',
    action='store_true',
    dest='all',
    default=False,
    help="Print all input/output edges known about (useful for debugging)"
)

group.add_argument(
    '--upstream',
    help="Print the list of all upstream jobs and inputs from the provided job "
         "identifier, input, or output, in a breadth-first traversal"
)
group.add_argument(
    '--downstream',
    help="Print the list of all downstream jobs and outputs from the provided "
         "job identifier, input, or output, in a breadth-first traversal"
)

#------------------------------- job IO limits -------------------------------

parser.add_argument(
    '--depth',
    type=int,
    default=-1,
    help="Sets the depth of the traversal for --upstream and --downstream "
         "(negative numbers mean no-limit)"
)

parser.add_argument(
    '--after',
    help="If provided one of: timestamp ('1473825618.18592', '1473825618'), "
         "datetime ('2016-09-12 12:14:32.234232', '2016-09-12 12:14:32', "
         "'2016-09-12 12:14), or date ('2016-09-12'), will only produce jobs "
         "inputs or outputs last seen after that timestamp, datetime, or date. "
         "Note: only applies to --upstream and --downstream options, and only "
         "the most recent run information is kept."
)

parser.add_argument(
    '--before',
    help="Like --after, only requires jobs to be *before* the provided timestamp "
         "datetime, or date."
)

#--------------------------------- --refresh ---------------------------------

group.add_argument(
    '--refresh',
    dest='refresh',
    metavar="JOB_IDENTIFIER",
    help="Will refresh an already-started job with the given job identifier."
)

#------------ --start - really start a job from the command-line -------------

group.add_argument(
    '--start',
    dest='start',
    metavar="JOB_IDENTIFIER",
    help="Will start or refresh (if already started) the job with the given "
         "job identifier. Note: if you want to lock inputs/outputs (the start "
         "case, not the refresh case), you *must* provide them as --add-input "
         "and --add-output arguments"
)

#--------------------------- --duration and --wait ---------------------------

parser.add_argument(
    '--duration',
    type=int,
    default=None,
    help="How long to keep the lock for, required when using --start"
)

parser.add_argument(
    '--wait',
    type=int,
    default=None,
    help="How long to wait to acquire the lock, required when using --start"
)

#------------------------ --start inputs and outputs -------------------------

parser.add_argument(
    '--add-input',
    action='append',
    help="The list of inputs to lock when using --start"
)

parser.add_argument(
    '--add-output',
    action='append',
    help="The list of outputs to lock/generate when using --start"
)

#------------------------------ --start history ------------------------------

hgroup = parser.add_mutually_exclusive_group()
hgroup.add_argument(
    '--yes-history',
    action='store_true',
    default=None,
    help="Will override the default history option in the system globals. Note: "
         "only applies to --start calls that are actually starting a new job."
)

hgroup.add_argument(
    '--no-history',
    action='store_false',
    dest='yes_history',
    help="Will override the default history option in the system globals. Note: "
         "only applies to --start calls that are actually starting a new job."
)

#------------------------- --start overwrite outputs -------------------------

ogroup = parser.add_mutually_exclusive_group()
ogroup.add_argument(
    '--yes-overwrite',
    action='store_true',
    default=None,
    help="Will pass overwrite=True when using --start"
)

ogroup.add_argument(
    '--no-overwrite',
    action='store_false',
    dest='yes_overwrite',
    help="Will pass overwrite=False when using --start"
)

#---------------------------- remaining arguments ----------------------------

group.add_argument(
    '--stop',
    help="Unlock all inputs and outputs related to the provided job id, DO write "
         "outputs"
)
group.add_argument(
    '--stop-failed',
    help="Unlock all inputs and outputs related to the provided job id, DO NOT "
         "write outputs"
)
group.add_argument(
    '--unlock-inputs',
    nargs='*',
    help="Unlocks the provided inputs"
)
group.add_argument(
    '--unlock-outputs',
    nargs='*',
    help="Unlocks the provided outputs"
)
group.add_argument(
    '--create-outputs',
    nargs='*',
    help="Unlocks and sets the provided outputs"
)

def main():
    global ARGS
    ARGS = parser.parse_args()
    handle_args(ARGS)

__all__ = list(set(globals()) - _all)

if __name__ == '__main__':
    main()
