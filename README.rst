
Job resource input/output control using Redis or Valkey as a locking layer

Copyright 2016-2025 Dr. Josiah Lee Carlson, Ph.D.

This library licensed under the GNU LGPL v2.1

The initial library requirements and implementation were done for OpenMail LLC.
(now System1 LLC.) jobs.py (this library) was more or less intended to offer
input and output control like Luigi and/or Airflow (both Python packages), with
fewer hard integration requirements. In fact, jobs.py has been used successfully
as part of jobs running in a cron schedule via Jenkins, in build chains in
Jenkins, inside individual rpqueue tasks, and even inside individual Flask web
requests for some high-value data (jobs.py is backed by Redis, so job locking
overhead *can* be low, even when you need to keep data safe).

Note: any company that I (Josiah Carlson, the author) introduce or use this
library, automatically has a license to use / deploy / ship jobs.py as part of a
docker layer, or other similar virtualization component for dev / staging / test
/ or production use. Basically I'm trying to say to any lawyers / lawyer-type
people: if I worked for the company, or the company you bought, and they are
using this library, it's fine.

If I *didn't* work for your company, and you want the *same* rights as ^^^, just
buy a commercial license. Monthly, annual, and *lifetime* rates are very
reasonable, give you the warm and fuzzies for supporting open-source software,
and give you actual *rights* to some level of support from the author.


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

    # Sometimes you don't want your outputs to last forever (sometimes history
    # should be forgotten, right?), and jobs.py gives you the chance to say as
    # much.
    # By default, a `None` duration means that outputs will last forever. Any
    # other value will be used in a call to `expire` on the associated output
    # keys after they are set on a job's successful completion. This value is in
    # seconds.
    jobs.OUTPUT_DURATION = None

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
    jobs.OUTPUT_DURATION = ...

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

