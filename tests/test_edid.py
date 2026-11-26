import os
import unittest
from pathlib import Path

from camlink_edid import edid
from fakes import factory_like_edid, with_checksum

# The exact 18 bytes that were written to a real card and accepted by a PS5.
HARDWARE_VERIFIED_DTD = bytes.fromhex("565e00a0a0a0295030203500555021000018")


class TimingTests(unittest.TestCase):
    def test_qhd60_encodes_to_the_hardware_verified_bytes(self):
        self.assertEqual(edid.QHD60_DTD, HARDWARE_VERIFIED_DTD)

    def test_decode_is_the_inverse_of_encode(self):
        self.assertEqual(edid.decode_dtd(HARDWARE_VERIFIED_DTD), edid.QHD60)

    def test_qhd60_parameters(self):
        t = edid.QHD60
        self.assertEqual((t.h_active, t.v_active, t.h_total, t.v_total), (2560, 1440, 2720, 1481))
        self.assertAlmostEqual(t.refresh_hz, 59.95055, places=4)
        self.assertAlmostEqual(t.h_freq_khz, 88.787, places=2)
        self.assertIn("H-/V-", t.describe())

    def test_display_descriptor_is_not_a_timing(self):
        self.assertIsNone(edid.decode_dtd(edid.EMPTY_DESCRIPTOR))


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.base = factory_like_edid()

    def test_factory_like_edid_is_valid(self):
        self.assertEqual(edid.problems(self.base), [])
        self.assertEqual(edid.classify(self.base), edid.FACTORY_LAYOUT)

    def test_rejects_wrong_size(self):
        self.assertTrue(edid.problems(self.base[:255]))
        self.assertTrue(edid.problems(self.base + b"\0"))

    def test_rejects_bad_checksum(self):
        broken = bytearray(self.base)
        broken[127] ^= 1
        self.assertIn("checksum of block 0 is wrong", edid.problems(broken))
        broken = bytearray(self.base)
        broken[255] ^= 1
        self.assertIn("checksum of block 1 is wrong", edid.problems(broken))

    def test_rejects_other_identity(self):
        other = bytearray(self.base)
        other[10] = 0x67
        self.assertTrue(any("identity" in p for p in edid.problems(with_checksum(other))))

    def test_rejects_bad_header(self):
        other = bytearray(self.base)
        other[1] = 0
        self.assertIn("invalid EDID header", edid.problems(with_checksum(other)))

    def test_rejects_missing_extension(self):
        other = bytearray(self.base)
        other[126] = 0
        self.assertTrue(edid.problems(with_checksum(other)))

    def test_rejects_missing_preferred_timing(self):
        other = bytearray(self.base)
        other[54:72] = edid.EMPTY_DESCRIPTOR
        self.assertTrue(any("preferred" in p for p in edid.problems(with_checksum(other))))

    def test_rejects_mode_above_receiver_limit(self):
        # 2560x1440 @ 120 Hz needs about 497 MHz, far beyond the 300 MHz receiver.
        too_fast = edid.Timing(497_750, 2560, 160, 48, 32, 1440, 85, 3, 5, 597, 336, 0x18)
        other = bytearray(self.base)
        other[72:90] = edid.encode_dtd(too_fast)
        self.assertTrue(any("exceeds" in p for p in edid.problems(with_checksum(other))))

    def test_rejects_mode_outside_declared_range(self):
        other = bytearray(self.base)
        other[108 + 9] = 20  # range limits: max 200 MHz
        found = edid.problems(with_checksum(other))
        self.assertTrue(any("exceeds" in p for p in found))

    def test_rejects_edid_14_range_offsets(self):
        other = bytearray(self.base)
        other[108 + 4] = 0x02
        self.assertTrue(edid.problems(with_checksum(other)))


class ChangeTests(unittest.TestCase):
    def setUp(self):
        self.base = factory_like_edid()

    def test_add_changes_only_slot2_and_checksum(self):
        new = edid.add_qhd60(self.base)
        self.assertEqual(edid.problems(new), [])
        self.assertEqual(edid.classify(new), edid.QHD60_PRESENT)
        self.assertTrue(set(edid.changed_offsets(self.base, new)) <= set(range(72, 90)) | {127})
        self.assertEqual(new[72:90], HARDWARE_VERIFIED_DTD)
        self.assertEqual(new[128:], self.base[128:])

    def test_remove_is_the_exact_inverse(self):
        self.assertEqual(edid.remove_qhd60(edid.add_qhd60(self.base)), self.base)

    def test_add_and_remove_are_idempotent(self):
        added = edid.add_qhd60(self.base)
        self.assertEqual(edid.add_qhd60(added), added)
        self.assertEqual(edid.remove_qhd60(self.base), self.base)

    def test_refuses_to_overwrite_a_different_descriptor(self):
        other = bytearray(self.base)
        other[72:90] = edid.encode_dtd(edid.Timing(148_500, 1920, 280, 88, 44, 1080, 45, 4, 5, 160, 90, 0x1E))
        other = with_checksum(other)
        self.assertEqual(edid.classify(other), edid.UNKNOWN)
        with self.assertRaises(edid.EdidError):
            edid.add_qhd60(other)
        with self.assertRaises(edid.EdidError):
            edid.remove_qhd60(other)

    def test_refuses_invalid_input(self):
        broken = bytearray(self.base)
        broken[127] ^= 1
        with self.assertRaises(edid.EdidError):
            edid.add_qhd60(broken)

    def test_refuses_when_limits_do_not_cover_the_mode(self):
        other = bytearray(self.base)
        other[108 + 9] = 24  # max 240 MHz < 241.5 MHz
        with self.assertRaises(edid.EdidError):
            edid.add_qhd60(with_checksum(other))

    def test_offered_modes(self):
        before = {(m.width, m.height, m.refresh_hz, m.interlaced) for m in edid.offered_modes(self.base)}
        after = {(m.width, m.height, m.refresh_hz, m.interlaced) for m in edid.offered_modes(edid.add_qhd60(self.base))}
        self.assertNotIn((2560, 1440, 60, False), before)
        self.assertEqual(after - before, {(2560, 1440, 60, False)})
        self.assertTrue(any(m.preferred and m.width == 3840 for m in edid.offered_modes(self.base)))
        self.assertEqual(edid.offered_modes(b"\x00" * 10), [])

    def test_describe_never_crashes(self):
        for sample in (self.base, edid.add_qhd60(self.base), bytes(256), b"\x00" * 10):
            self.assertTrue(edid.describe(sample))


@unittest.skipUnless(os.environ.get("CAMLINK_EDID_FACTORY_DUMP"),
                     "set CAMLINK_EDID_FACTORY_DUMP to a factory EDID read from a card")
class FactoryDumpTests(unittest.TestCase):
    """Optional check against a real, unmodified factory EDID (not included in the repository)."""

    def test_known_hashes(self):
        factory = Path(os.environ["CAMLINK_EDID_FACTORY_DUMP"]).read_bytes()
        self.assertEqual(edid.sha256(factory), edid.FACTORY_SHA256)
        added = edid.add_qhd60(factory)
        self.assertEqual(edid.sha256(added), edid.FACTORY_WITH_QHD60_SHA256)
        self.assertEqual(edid.remove_qhd60(added), factory)
        self.assertIn("identical to the factory EDID", edid.state_text(factory))


if __name__ == "__main__":
    unittest.main()
