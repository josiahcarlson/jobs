
import binascii
import os
import random
import time
import unittest

import jobs

import redis

jobs.CONN = CONN = redis.Redis(db=15)


NG = jobs.NG.test[int(time.time())*1000000 + random.randrange(1000000)]

def random_identifier():
    return binascii.hexlify(os.urandom(8))

class TestJobs(unittest.TestCase):
    def setUp(self):
        CONN.mset({str(NG.input1):'', str(NG.input2):'', str(NG.input3):''})

    def tearDown(self):
        kk = CONN.keys('*' + str(NG) + '*')
        kk2 = CONN.keys('*test.*')
        trim = 1000000*(time.time() - 300)
        for k in kk2:
            ts = k.partition(b'.')[-1].partition(b'.')[0]
            if len(ts) == 16 and ts.isdigit() and int(ts) < trim:
                kk.append(k)

        if kk:
            CONN.delete(*kk)

    # First set of tests is meant to test the raw underlying API that does all
    # of the work.

    def test_1_inputs(self):
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1], [], random_identifier(), 0, False),
                         {'ok': True})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1, NG.input3], [], random_identifier(), 0, False),
                         {'ok': True})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input2, NG.input3], [], random_identifier(), 0, False),
                         {'ok': True})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input2, NG.input3, NG.input1], [], random_identifier(), 0, False),
                         {'ok': True})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input4], [], random_identifier(), 0, False),
                         {'err': {'input_missing': [NG.input4]}, 'ok': False, 'temp': {}})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input3, NG.input4], [], random_identifier(), 0, False),
                         {'err': {'input_missing': [NG.input4]}, 'ok': False, 'temp': {}})

    def test_2_outputs(self):
        self.assertEqual(jobs._run_if_possible(CONN, [], [NG.output1], random_identifier(), 0, False),
                         {'ok': True})
        self.assertEqual(jobs._run_if_possible(CONN, [], [NG.input1], random_identifier(), 0, False),
                         {'err': {'output_exists': [NG.input1]}, 'ok': False, 'temp': {}})
        self.assertEqual(jobs._run_if_possible(CONN, [], [NG.input1, NG.output1], random_identifier(), 0, False),
                         {'err': {'output_exists': [NG.input1]}, 'ok': False, 'temp': {}})
        self.assertEqual(jobs._run_if_possible(CONN, [], [NG.input1, NG.output1], random_identifier(), 0, True),
                         {'ok': True})

    def test_3_inputs_and_outputs(self):
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1], [NG.output1], random_identifier(), 0, False),
                         {'ok': True})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1, NG.input3], [NG.output1], random_identifier(), 0, False),
                         {'ok': True})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1, NG.input3], [NG.input2], random_identifier(), 0, False),
                         {'err': {'output_exists': [NG.input2]}, 'ok': False, 'temp': {}})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1, NG.input3], [NG.input2], random_identifier(), 0, True),
                         {'ok': True})

        id = random_identifier()
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1, NG.input3], [NG.input2], id, 1, True),
                         {'ok': True})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input2, NG.input3], [], random_identifier(), 0, False),
                         {'err': {'input_missing': [NG.input2]}, 'ok': False, 'temp': {}})
        # Should fail because inputs are locked on writing
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1, NG.input3], [NG.input2], random_identifier(), 1, True),
                         {'err': {'output_locked': [NG.input2]}, 'ok': False, 'temp': {}})
        self.assertEqual(jobs._run_if_possible(CONN, [NG.input1, NG.input3], [NG.input2], id, 1, True),
                         {'ok': True})

        jobs._refresh_job(CONN, [NG.input1, NG.input3], [NG.input2], id, 10, True)
        lock_ttl = int(CONN.ttl('olock:' + str(NG.input2)))
        self.assertGreaterEqual(lock_ttl, 1)
        self.assertLessEqual(lock_ttl, 10)

        jobs._finish_job(CONN, [NG.input1, NG.input3], [NG.input2], id)

    # now test the actual resource manager that people should use

    def test_4_resource_manager(self):
        # make sure locks are created and destroyed
        with jobs.ResourceManager([NG.input1, NG.input2], [], 1, conn=CONN):
            self.assertTrue(CONN.exists('ilock:' + str(NG.input1)))
        self.assertFalse(CONN.exists('ilock:' + str(NG.input1)))

        try:
            with jobs.ResourceManager([NG.input1, NG.input2], [NG.input3], 1, conn=CONN):
                pass
        except jobs.ResourceUnavailable as e:
            self.assertEqual(e.args, ({'output_exists': [NG.input3]},))

        id = random_identifier()
        jobs._run_if_possible(CONN, [], [NG.output1], id, 10, False)
        # Verify that we wait long enough
        t = time.time()
        try:
            with jobs.ResourceManager([NG.output1], [], 0, 1, conn=CONN):
                pass
        except jobs.ResourceUnavailable as e:
            self.assertEqual(e.args, ({'input_missing': [NG.output1]},))
        self.assertGreater(time.time() - t, 1)
        self.assertLess(time.time() - t, 1.25)

        jobs._finish_job(CONN, [], [NG.output1], id)

        with jobs.ResourceManager([NG.output1], [NG.output2], 5, conn=CONN) as job:
            # Note: Nested resource manager calls are for testing purposes only,
            #       don't nest them in actual jobs!
            try:
                with jobs.ResourceManager([NG.output1], [NG.output2], 0, conn=CONN):
                    pass
            except jobs.ResourceUnavailable as e:
                # make sure the output is still locked
                self.assertEqual(e.args, ({'output_locked': [NG.output2]},))
                self.assertTrue(CONN.exists('olock:' + str(NG.output2)))
                # make sure that the output doesn't exist
                self.assertFalse(CONN.exists(str(NG.output2)))

            # verify lock TTLs and that we can refresh them
            time.sleep(1)
            lock_ttl = int(CONN.ttl('olock:' + str(NG.output2)))
            self.assertGreaterEqual(lock_ttl, 1)
            self.assertLessEqual(lock_ttl, 4)
            job.refresh()
            lock_ttl = int(CONN.ttl('olock:' + str(NG.output2)))
            self.assertGreaterEqual(lock_ttl, 4)
            self.assertLessEqual(lock_ttl, 5)

            self.assertFalse(CONN.exists(str(NG.output2)))
            start = time.time()
            # test whether a job that waits long enough for the lock can get it
            with jobs.ResourceManager([], [NG.output2], 0, 5, conn=CONN) as job:
                pass
            self.assertGreater(time.time() - start, 1)
            # verify that the recovered lock lead to completion
            self.assertTrue(CONN.exists(str(NG.output2)))

    def test_5_lost_lock(self):
        with jobs.ResourceManager([NG.input1, NG.input2], [NG.output1], 1) as job:
            time.sleep(2)
            self.assertEqual(job.refresh(), {'ok':True, 'temp': {
                'output_lock_lost': [NG.output1], 'input_lock_lost': [NG.input1, NG.input2]
            }})

if __name__ == '__main__':
    unittest.main()
