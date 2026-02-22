import unittest

from cyberspace_cli.toward import choose_next_axis_value_toward, choose_next_hop_xyz


class TestToward(unittest.TestCase):
    def test_choose_next_axis_value_toward_progresses(self) -> None:
        r = choose_next_axis_value_toward(current=100, target=200, max_lca_height=20)
        self.assertNotEqual(r.next, r.current)
        self.assertLessEqual(r.lca_height, 20)
        self.assertLessEqual(abs(200 - r.next), abs(200 - 100))

    def test_choose_next_axis_value_toward_exact_when_small(self) -> None:
        r = choose_next_axis_value_toward(current=100, target=101, max_lca_height=20)
        self.assertEqual(r.next, 101)

    def test_choose_next_hop_xyz(self) -> None:
        hop = choose_next_hop_xyz(x=0, y=0, z=0, tx=800, ty=900, tz=1000, max_lca_height=20)
        self.assertTrue(hop.x.next > 0)
        self.assertTrue(hop.y.next > 0)
        self.assertTrue(hop.z.next > 0)


if __name__ == "__main__":
    unittest.main()
