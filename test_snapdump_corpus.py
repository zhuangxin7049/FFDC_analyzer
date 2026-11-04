"""Regressions derived from the /mnt corpus, using small independent fixtures."""
import sys
import unittest
from unittest.mock import patch

import ffdc_snapdump
import snapdump
from snapdump_chat import build_snapdump_chat
from test_snapdump import check, legacy_crash, zipped


class CorpusRegressionTests(unittest.TestCase):
    def test_large_pl_module_keeps_counters_after_old_limit(self):
        pl = 'padding\n' * (17 * 1024 * 1024 // 8)
        pl += 'Total Outstanding IOs: 123, Pending IOs: 2\nSAS Device Discovery Error Event Counter : 1\n'
        raw = zipped({'crashDump.txt': legacy_crash(), 'PL_MODULE.txt': pl})
        result = snapdump.analyze_snapdump('large-pl.zip', raw)
        self.assertEqual(result['snapshot']['outstanding_io'], 123)
        self.assertEqual(result['snapshot']['pending_io'], 2)
        self.assertEqual(result['snapshot']['discovery_errors'], 1)
        self.assertEqual(result['_file_text']['PL_MODULE.txt'], pl)
        self.assertLess(ffdc_snapdump._result_size(result), 25 * 1024 * 1024)

    def test_archive_and_standalone_limits_are_independent(self):
        with patch.object(snapdump, 'MAX_FILE_BYTES', 200), patch.object(snapdump, 'MAX_STANDALONE_BYTES', 100):
            self.assertTrue(snapdump.analyze_snapdump('sample.zip', zipped({'Summary.txt': 'a' * 101})))
            with self.assertRaisesRegex(ValueError, 'Standalone text'):
                snapdump.analyze_snapdump('Summary.txt', b'a' * 101)
            with self.assertRaisesRegex(ValueError, 'decompression limit'):
                snapdump.analyze_snapdump('sample.zip', zipped({'Summary.txt': 'a' * 201}))

    def test_named_nvram_single_dword_scalar(self):
        for raw, expected in [('00000000', 'info'), ('0000000a', 'warn')]:
            with self.subTest(raw=raw):
                result = snapdump.analyze_snapdump('sample.zip', zipped({
                    'crashDump.txt': legacy_crash(),
                    'NVRAM_MODULE.txt': 'CtrlResetCount :\r\n7fdd5a64:  ' + raw + '     ....\r\nhibernate :\r\n7fdd5a64:  00000001\r\n'}))
                self.assertEqual(result['snapshot']['controller_resets'], raw)
                self.assertEqual(check(result, 'Controller reset counter')['severity'], expected)

    def test_nvram_unavailable_or_multiword_struct_is_not_a_scalar(self):
        for text in ['CtrlResetCount :\n7fdd5a64: ........\nhibernate :\n7fdd5a64: 00000001\n',
                     'CtrlResetCount :\n7fdd5a64: 00000001 00000002\n']:
            with self.subTest(text=text):
                self.assertIsNone(snapdump._reset_counter(text))

    def modern_raid(self, counts=None):
        return snapdump.analyze_snapdump('mpi3-raid.zip', zipped({
            'Summary.txt': 'SNAPDUMPI_FAILURE_TYPE_ONDEMAND\nFwMode: IOPI_FW_OPMODE_RAID\n',
            'CrashDump.txt': 'Ver Name: 8.14.1\nBoardName: MR 9670W-16i\nLd/PD device counts:\n' +
                (counts or 'ldPresentCnt=a ldDegradedCnt=1 ldOfflineCnt=2\npdDiskPresentCnt=c pdDiskFailedCnt=1 pdDiskPredFailureCnt=0\nmemCorrectableErrCnt=0 memUnCorrectableErrCnt=0\n') + 'Adapter Status:\n',
            'Pd.txt': 'PD=165\nscsiType=0 state=0(UNCONFIGURED_GOOD)\nmediaErrCount=0 otherErrCount=2 predFailCount=0\n'
                      'PD=176\nscsiType=d state=0(UNCONFIGURED_GOOD)\n',
            'Nvram.txt': 'NVRAM Raw dump all(Hex):\n7081CC60: 00000000\n',
            'Encl.txt': 'inUseSlotCount:c\n',
        }))

    def test_mpi3_raid_hex_counts_and_pd_inventory(self):
        result = self.modern_raid()
        self.assertEqual(result['snapshot']['ld_present'], 10)
        self.assertEqual(result['snapshot']['pd_disks'], 12)
        self.assertEqual(result['snapshot']['mapped_slots'], 12)
        self.assertEqual(result['snapshot']['mapped_slots_raw'], ['c'])
        self.assertEqual(check(result, 'Logical drive state')['severity'], 'critical')
        self.assertEqual(check(result, 'Physical disk state')['severity'], 'critical')
        self.assertEqual(result['physical_drives'], [{'id': '165', 'state': 'UNCONFIGURED_GOOD',
                         'media_errors': 0, 'other_errors': 2, 'predictive_failures': 0}])
        self.assertIn('failed_por', result['coverage']['missing_fields'])
        self.assertIsNone(result['snapshot']['failed_por'])
        self.assertIsNone(result['snapshot']['failed_hip'])
        self.assertNotIn('logical_drives', result)  # Packed per-volume state is not invented.

    def test_perfit_hba_does_not_borrow_raid_disk_counts(self):
        result = snapdump.analyze_snapdump('hba.zip', zipped({
            'Summary.txt': 'SNAPDUMPI_FAILURE_TYPE_ONDEMAND\nFwMode: IOPI_FW_OPMODE_PERFIT\n',
            'CrashDump.txt': 'Ver Name: 8.19\nLd/PD device counts:\nldPresentCnt=0 pdDiskPresentCnt=0\nAdapter Status:\n',
        }))
        self.assertNotIn('pd_disks', result['snapshot'])
        self.assertFalse(any(item['title']=='Physical disk state' for item in result['checks']))

    def test_empty_identity_fields_never_consume_next_line(self):
        result = snapdump.analyze_snapdump('CrashDump.txt', b'Ver Name: 8.14\nPackage Ver Name:\nDriver Ver:\nBuildDate:\nRelease Level:\nBoardName:\nNextLabel: value\n')
        for name in ['package','driver','build_date','release_level','board']:
            self.assertEqual(result['firmware'][name], '')

    def test_history_counts_do_not_override_current_snapshot(self):
        result = snapdump.analyze_snapdump('legacy.zip', zipped({
            'crashDump.txt': legacy_crash(controller='ldPresentCount=1 ldDegradedCount=0 ldOfflineCount=0'),
            'event_dump.txt': 'EVT#00001-T0: 1=VD 0 is now OFFLINE\nEVT#00002-T1: 1=VD 0 is now DEGRADED\n',
        }))
        self.assertEqual(result['events']['counts']['offline'], 1)
        self.assertEqual(result['events']['counts']['degraded'], 1)
        self.assertEqual(check(result, 'Logical drive state')['severity'], 'ok')

    def test_actual_string_representation_and_shared_objects_count(self):
        text = 'a' * 2000
        self.assertEqual(ffdc_snapdump._result_size([text,text]), sys.getsizeof([text,text]) + sys.getsizeof(text))
        self.assertGreater(ffdc_snapdump._result_size('😀' * 2000), ffdc_snapdump._result_size(text))

    def test_mpi3_raid_raw_evidence_is_available_to_davy(self):
        result = self.modern_raid()
        _, prompt, sources = build_snapdump_chat(result, '分析这张卡的阵列和硬盘错误')
        excerpts = '\n'.join(item['excerpt'] for item in sources)
        self.assertIn('ldDegradedCnt=1', excerpts)
        self.assertIn('pdDiskPresentCnt=c', excerpts)
        self.assertIn('otherErrCount=2', excerpts)
        self.assertIn('packed per-volume', prompt)
        for source in sources:
            expected = '\n'.join(result['_file_text'][source['name']].splitlines()[source['start_line']-1:source['end_line']])
            self.assertEqual(source['excerpt'], expected)


if __name__ == '__main__':
    unittest.main()
