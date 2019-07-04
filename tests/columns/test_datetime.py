from contextlib import contextmanager
from datetime import date, datetime
import os
from time import tzset

from mock import patch
from pytz import timezone, utc

from tests.testcase import BaseTestCase
from tests.util import require_server_version


class DateTimeTestCase(BaseTestCase):
    def test_simple(self):
        with self.create_table('a Date, b DateTime, c DateTime'):
            data = [(date(2012, 10, 25),
                     datetime(2012, 10, 25, 14, 7, 19),
                     '2019-07-02 11:47:20')]
            self.client.execute(
                'INSERT INTO test (a, b, c) VALUES', data
            )

            query = 'SELECT * FROM test'
            inserted = self.emit_cli(query)
            self.assertEqual(
                inserted,
                '2012-10-25\t2012-10-25 14:07:19\t2019-07-02 11:47:20\n')

            inserted = self.client.execute(query)

            self.assertEqual(inserted[0][:2], data[0][:2])
            self.assertEqual(inserted[0][2], datetime(2019, 7, 2, 11, 47, 20))

    def test_nullable_date(self):
        with self.create_table('a Nullable(Date)'):
            data = [
                (None, ), (date(2012, 10, 25), ),
                (None, ), (date(2017, 6, 23), )
            ]
            self.client.execute(
                'INSERT INTO test (a) VALUES', data
            )

            query = 'SELECT * FROM test'
            inserted = self.emit_cli(query)
            self.assertEqual(
                inserted, '\\N\n2012-10-25\n\\N\n2017-06-23\n'
            )

            inserted = self.client.execute(query)
            self.assertEqual(inserted, data)

    def test_nullable_datetime(self):
        with self.create_table('a Nullable(DateTime)'):
            data = [
                (None, ), (datetime(2012, 10, 25, 14, 7, 19), ),
                (None, ), (datetime(2017, 6, 23, 19, 10, 15), )
            ]
            self.client.execute(
                'INSERT INTO test (a) VALUES', data
            )

            query = 'SELECT * FROM test'
            inserted = self.emit_cli(query)
            self.assertEqual(
                inserted,
                '\\N\n2012-10-25 14:07:19\n\\N\n2017-06-23 19:10:15\n'
            )

            inserted = self.client.execute(query)
            self.assertEqual(inserted, data)


class DateTimeTimezonesTestCase(BaseTestCase):
    @contextmanager
    def patch_env_tz(self, tz_name):
        # Although in many cases, changing the TZ environment variable may
        # affect the output of functions like localtime() without calling
        # tzset(), this behavior should not be relied on.
        # https://docs.python.org/3/library/time.html#time.tzset
        with patch.dict(os.environ, {'TZ': tz_name}):
            tzset()
            yield

        tzset()

    # Asia/Kamchatka = UTC+12
    # Asia/Novosibirsk = UTC+7
    # Europe/Moscow = UTC+3

    # 1500000000 second since epoch in Europe/Moscow.
    # 1500010800 second since epoch in UTC.
    dt = datetime(2017, 7, 14, 5, 40)
    dt_tz = timezone('Asia/Kamchatka').localize(dt)

    # INSERTs ans SELECTs must be the same as clickhouse-client's.

    def test_use_server_timezone(self):
        # Determine server timezone and calculate expected timestamp.
        server_tz_name = self.client.execute('SELECT timezone()')[0][0]
        offset = timezone(server_tz_name).utcoffset(self.dt).total_seconds()
        timestamp = 1500010800 - int(offset)

        with self.patch_env_tz('Asia/Novosibirsk'):
            with self.create_table('a DateTime'):
                self.client.execute(
                    'INSERT INTO test (a) VALUES', [(self.dt, )]
                )

                self.emit_cli(
                    "INSERT INTO test (a) VALUES ('2017-07-14 05:40:00')"
                )

                query = 'SELECT toInt32(a) FROM test'
                inserted = self.emit_cli(query)
                self.assertEqual(inserted, '{ts}\n{ts}\n'.format(ts=timestamp))

                query = 'SELECT * FROM test'
                inserted = self.emit_cli(query)
                self.assertEqual(
                    inserted,
                    '2017-07-14 05:40:00\n2017-07-14 05:40:00\n'
                )

                inserted = self.client.execute(query)
                self.assertEqual(inserted, [(self.dt, ), (self.dt, )])

    def test_use_client_timezone(self):
        settings = {'use_client_time_zone': True}

        with self.patch_env_tz('Asia/Novosibirsk'):
            with self.create_table('a DateTime'):
                self.client.execute(
                    'INSERT INTO test (a) VALUES', [(self.dt, )],
                    settings=settings
                )

                self.emit_cli(
                    "INSERT INTO test (a) VALUES ('2017-07-14 05:40:00')",
                    use_client_time_zone=1
                )

                query = 'SELECT toInt32(a) FROM test'
                inserted = self.emit_cli(query, use_client_time_zone=1)
                # 1499985600 = 1500000000 - 4 * 3600
                self.assertEqual(inserted, '1499985600\n1499985600\n')

                query = 'SELECT * FROM test'
                inserted = self.emit_cli(query, use_client_time_zone=1)
                self.assertEqual(
                    inserted,
                    '2017-07-14 05:40:00\n2017-07-14 05:40:00\n'
                )

                inserted = self.client.execute(query, settings=settings)
                self.assertEqual(inserted, [(self.dt, ), (self.dt, )])

    def test_insert_integers(self):
        settings = {'use_client_time_zone': True}

        with self.patch_env_tz('Europe/Moscow'):
            with self.create_table('a DateTime'):
                self.client.execute(
                    'INSERT INTO test (a) VALUES', [(1530211034, )],
                    settings=settings
                )

                query = 'SELECT toUInt32(a), a FROM test'
                inserted = self.emit_cli(query, use_client_time_zone=1)
                self.assertEqual(inserted, '1530211034\t2018-06-28 21:37:14\n')

    def test_insert_integer_bounds(self):
        with self.create_table('a DateTime'):
            self.client.execute(
                'INSERT INTO test (a) VALUES',
                [(0, ), (1, ), (1500000000, ), (2**32-1, )]
            )

            query = 'SELECT toUInt32(a) FROM test ORDER BY a'
            inserted = self.emit_cli(query)
            self.assertEqual(inserted, '0\n1\n1500000000\n4294967295\n')

    @require_server_version(1, 1, 54337)
    def test_datetime_with_timezone_use_server_timezone(self):
        server_tz_name = self.client.execute('SELECT timezone()')[0][0]
        offset = timezone(server_tz_name).utcoffset(self.dt)

        with self.patch_env_tz('Asia/Novosibirsk'):
            with self.create_table('a DateTime'):
                self.client.execute(
                    'INSERT INTO test (a) VALUES', [(self.dt_tz, )]
                )

                self.emit_cli(
                    "INSERT INTO test (a) VALUES "
                    "(toDateTime('2017-07-14 05:40:00', 'Asia/Kamchatka'))",
                )

                query = 'SELECT toInt32(a) FROM test'
                inserted = self.emit_cli(query)
                # 1499967600 = 1500000000 - 12 * 3600
                self.assertEqual(inserted, '1499967600\n1499967600\n')

                query = 'SELECT * FROM test'
                inserted = self.emit_cli(query)

                dt = (self.dt_tz.astimezone(utc) + offset).replace(tzinfo=None)
                self.assertEqual(inserted, '{dt}\n{dt}\n'.format(dt=dt))

                inserted = self.client.execute(query)
                self.assertEqual(inserted, [(dt, ), (dt, )])

    @require_server_version(1, 1, 54337)
    def test_datetime_with_timezone_use_client_timezone(self):
        settings = {'use_client_time_zone': True}

        with self.patch_env_tz('Asia/Novosibirsk'):
            with self.create_table('a DateTime'):
                self.client.execute(
                    'INSERT INTO test (a) VALUES', [(self.dt_tz, )],
                    settings=settings
                )

                self.emit_cli(
                    "INSERT INTO test (a) VALUES "
                    "(toDateTime('2017-07-14 05:40:00', 'Asia/Kamchatka'))",
                    use_client_time_zone=1
                )

                query = 'SELECT toInt32(a) FROM test'
                inserted = self.emit_cli(query, use_client_time_zone=1)
                # 1499967600 = 1500000000 - 12 * 3600
                self.assertEqual(inserted, '1499967600\n1499967600\n')

                query = 'SELECT * FROM test'
                inserted = self.emit_cli(query, use_client_time_zone=1)
                # 2017-07-14 00:40:00 = 2017-07-14 05:40:00 - 05:00:00
                # (Kamchatka - Novosibirsk)
                self.assertEqual(
                    inserted,
                    '2017-07-14 00:40:00\n2017-07-14 00:40:00\n'
                )

                inserted = self.client.execute(query, settings=settings)
                dt = datetime(2017, 7, 14, 0, 40)
                self.assertEqual(inserted, [(dt, ), (dt, )])

    @require_server_version(1, 1, 54337)
    def test_column_use_server_timezone(self):
        with self.patch_env_tz('Europe/Moscow'):
            with self.create_table("a DateTime('Asia/Novosibirsk')"):
                self.client.execute(
                    'INSERT INTO test (a) VALUES', [(self.dt, )]
                )

                self.emit_cli(
                    "INSERT INTO test (a) VALUES ('2017-07-14 05:40:00')"
                )

                query = 'SELECT toInt32(a) FROM test'
                inserted = self.emit_cli(query)
                # 1499985600 = 1500000000 - 4 * 3600
                self.assertEqual(inserted, '1499985600\n1499985600\n')

                query = 'SELECT * FROM test'
                inserted = self.emit_cli(query)
                self.assertEqual(
                    inserted,
                    '2017-07-14 05:40:00\n2017-07-14 05:40:00\n'
                )

                inserted = self.client.execute(query)
                self.assertEqual(inserted, [(self.dt, ), (self.dt, )])

    @require_server_version(1, 1, 54337)
    def test_column_use_client_timezone(self):
        settings = {'use_client_time_zone': True}

        with self.patch_env_tz('Europe/Moscow'):
            with self.create_table("a DateTime('Asia/Novosibirsk')"):
                self.client.execute(
                    'INSERT INTO test (a) VALUES', [(self.dt, )],
                    settings=settings
                )
                self.emit_cli(
                    "INSERT INTO test (a) VALUES ('2017-07-14 05:40:00')",
                    use_client_time_zone=1
                )

                query = 'SELECT toInt32(a) FROM test'
                inserted = self.emit_cli(query, use_client_time_zone=1)
                # 1499985600 = 1500000000 - 4 * 3600
                self.assertEqual(inserted, '1499985600\n1499985600\n')

                query = 'SELECT * FROM test'
                inserted = self.emit_cli(query, use_client_time_zone=1)
                self.assertEqual(
                    inserted,
                    '2017-07-14 05:40:00\n2017-07-14 05:40:00\n'
                )

                inserted = self.client.execute(query, settings=settings)
                self.assertEqual(inserted, [(self.dt, ), (self.dt, )])
