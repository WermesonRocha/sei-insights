import time
import unittest
from unittest import mock

from sei_insights.clients.rate_limit import RateLimiter


class RateLimiterTest(unittest.TestCase):
    def test_rejeita_min_negativo(self):
        with self.assertRaises(ValueError):
            RateLimiter(-1, 5)

    def test_rejeita_max_menor_que_min(self):
        with self.assertRaises(ValueError):
            RateLimiter(3, 2)

    def test_wait_dorme_entre_min_e_max(self):
        with mock.patch("sei_insights.clients.rate_limit.time.sleep") as sleep, \
                mock.patch("sei_insights.clients.rate_limit.random.uniform", return_value=2.0), \
                mock.patch("sei_insights.clients.rate_limit.time.monotonic", side_effect=[0.0, 0.5, 2.0, 2.0]):
            rl = RateLimiter(1, 3)
            rl.wait()
            # Primeira chamada: now=0.0, elapsed=0.0, remaining=2.0, sleep(2.0), _last_request=0.5
            sleep.assert_called_once()
            self.assertAlmostEqual(sleep.call_args[0][0], 2.0)
            rl.wait()
            # Segunda chamada: now=2.0, elapsed=2.0-0.5=1.5, remaining=2.0-1.5=0.5, sleep(0.5)
            self.assertEqual(sleep.call_count, 2)
            self.assertAlmostEqual(sleep.call_args_list[1][0][0], 0.5)

    def test_wait_seconds_obedece_retry_after(self):
        with mock.patch("sei_insights.clients.rate_limit.time.sleep") as sleep:
            rl = RateLimiter(1, 3)
            rl.wait_seconds(4.2)
            sleep.assert_called_once_with(4.2)
