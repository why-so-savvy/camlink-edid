import unittest

from camlink_edid import edid, protocol
from fakes import FakeCard, factory_like_edid


def no_sleep(_seconds):
    pass


class FrameTests(unittest.TestCase):
    def test_read_frame_matches_vendor_software(self):
        # Observed from the vendor software: 06 | 06 07 a0 01 <offset> 08
        self.assertEqual(protocol.read_frame(0x10).hex(" "), "06 07 a0 01 10 08")

    def test_write_frame_header(self):
        frame = protocol.write_frame(0x08, bytes(range(8)))
        self.assertEqual(frame[:5].hex(" "), "0d 06 a0 09 08")
        self.assertEqual(frame[5:], bytes(range(8)))

    def test_old_wrong_header_can_never_be_produced(self):
        # The first prototype sent "09 0a a0 09": length and command were swapped.
        for offset in range(0, 256, 8):
            frame = protocol.write_frame(offset, bytes(8))
            self.assertEqual(frame[:4], bytes([0x0D, 0x06, 0xA0, 0x09]))

    def test_frames_only_target_the_edid_address(self):
        for offset in range(0, 256, 8):
            self.assertEqual(protocol.read_frame(offset)[2], 0xA0)
            self.assertEqual(protocol.write_frame(offset, bytes(8))[2], 0xA0)

    def test_frame_arguments_are_checked(self):
        for bad in (-8, 3, 256):
            with self.assertRaises(ValueError):
                protocol.read_frame(bad)
        with self.assertRaises(ValueError):
            protocol.write_frame(0, bytes(7))


class CardTests(unittest.TestCase):
    def setUp(self):
        self.base = factory_like_edid()
        self.target = edid.add_qhd60(self.base)
        self.fake = FakeCard(self.base)
        self.card = protocol.Card(self.fake, sleep=no_sleep)

    def test_read(self):
        self.assertEqual(self.card.read_edid_stable(), self.base)

    def test_successful_write_commits_once(self):
        self.card.write_edid(self.target)
        self.assertEqual(self.fake.commits, 1)
        self.assertEqual(bytes(self.fake.flash), self.target)
        self.assertEqual(len(self.fake.write_frames), 32)

    def test_rejected_first_chunk_stops_immediately(self):
        self.fake.reject_write_at = 0x00
        with self.assertRaises(protocol.WriteAborted) as ctx:
            self.card.write_edid(self.target)
        self.assertEqual(ctx.exception.offset, 0)
        self.assertFalse(ctx.exception.may_be_stored)
        self.assertEqual(len(self.fake.write_frames), 1)
        self.assertEqual(self.fake.commits, 0)

    def test_readback_mismatch_stops_before_commit(self):
        self.fake.corrupt_readback_at = 0x48
        with self.assertRaises(protocol.WriteAborted):
            self.card.write_edid(self.target)
        self.assertEqual(self.fake.commits, 0)
        self.assertEqual(bytes(self.fake.flash), self.base)
        self.assertEqual(len(self.fake.write_frames), 0x48 // 8 + 1)
        self.fake.replug()
        self.assertEqual(self.card.read_edid_stable(), self.base)

    def test_transport_error_mid_write(self):
        self.fake.raise_at = 0x80
        with self.assertRaises(protocol.WriteAborted) as ctx:
            self.card.write_edid(self.target)
        self.assertFalse(ctx.exception.may_be_stored)
        self.assertEqual(bytes(self.fake.flash), self.base)

    def test_problem_on_last_chunk_is_reported_as_possibly_stored(self):
        self.fake.corrupt_readback_at = 0xF8
        with self.assertRaises(protocol.WriteAborted) as ctx:
            self.card.write_edid(self.target)
        self.assertTrue(ctx.exception.may_be_stored)

    def test_bad_read_status(self):
        self.fake.exchange = lambda payload: bytes([1]) + bytes(16)
        with self.assertRaises(protocol.ProtocolError):
            self.card.read_edid()

    def test_unstable_reads_are_not_trusted(self):
        self.fake.unstable_reads = True
        with self.assertRaises(protocol.ProtocolError):
            self.card.read_edid_stable()

    def test_wrong_length_target(self):
        with self.assertRaises(ValueError):
            self.card.write_edid(self.target[:128])


if __name__ == "__main__":
    unittest.main()
