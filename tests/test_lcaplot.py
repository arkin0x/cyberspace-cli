import unittest

from cyberspace_cli.lcaplot import block_boundary_offsets, compute_adjacent_lca_heights


class TestLCAPlot(unittest.TestCase):
    def test_adjacent_plus_spike_at_2k_minus_1(self) -> None:
        # 15 -> 16 crosses a 2^4 boundary, requiring lca_height 5 (bit positions start at 1).
        s = compute_adjacent_lca_heights(center=15, span=0, direction=1)
        self.assertEqual(s.heights, [5])
        self.assertEqual(s.offsets, [0])

    def test_adjacent_minus_spike_at_power_of_two(self) -> None:
        # 16 -> 15 is the same boundary but in the negative direction.
        s = compute_adjacent_lca_heights(center=16, span=0, direction=-1)
        self.assertEqual(s.heights, [5])

    def test_block_boundaries_for_h4(self) -> None:
        # With h=4, block size is 16, so within [0..31]: starts at 0,16; ends at 15,31.
        starts, ends = block_boundary_offsets(center=0, series_start=0, series_end=31, h=4)
        self.assertEqual(starts, [0, 16])
        self.assertEqual(ends, [15, 31])


if __name__ == "__main__":
    unittest.main()
