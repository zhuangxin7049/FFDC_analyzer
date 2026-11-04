"""Standard host PCIe registers must not use backend firmware enums."""
import unittest
import snapdump


class LegacyPcieTests(unittest.TestCase):
    def test_standard_register_pair_and_latched_errors(self):
        result = snapdump._legacy_pcie('''<=PCIE Config start=>
 78: 00090947 PCI_DEV_STATUS_CTRL
 7c: 00437c24 PCI_LINK_CAP
 80: 10240040 PCI_LINK_STATUS_CTRL
104: 00000000 PCI_UC_ERR_STATUS
110: 00002000 PCI_C_ERR_STATUS
<=PCIE Config end=>''')
        self.assertEqual((result['max_speed_gts'], result['max_width']), (16, 2))
        self.assertEqual((result['current_speed_gts'], result['current_width']), (16, 2))
        self.assertEqual(result['device_error_bits'], 9)
        self.assertEqual(result['correctable_error_status'], 0x2000)
        self.assertEqual(result['uncorrectable_error_status'], 0)

    def test_unlabelled_backend_and_missing_registers_remain_unknown(self):
        result = snapdump._legacy_pcie('pciLinkSpeed=1f\nNegotiatedLinkRate 5\n7c: 00437c24 PCI_LINK_CAP')
        self.assertIsNone(result['max_speed_gts'])
        self.assertIsNone(result['current_width'])
        self.assertIsNone(result['correctable_error_status'])

    def test_reserved_speed_and_register_boundaries(self):
        result = snapdump._legacy_pcie('''<=PCIE Config start=>
 7c: 0000002f PCI_LINK_CAP
 a0: 011e0004 PCI_LINK_STATUS_CTRL_2
<=PCIE Config end=>
 80: 10240040 PCI_LINK_STATUS_CTRL''')
        self.assertEqual(result['max_speed_code'], '15')
        self.assertIsNone(result['max_speed_gts'])
        self.assertIsNone(result['current_speed_gts'])


if __name__ == '__main__':
    unittest.main()
