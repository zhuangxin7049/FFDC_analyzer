"""Legacy PSoC identities and status layouts from SEP FW Rev 1.08 (2017)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from test_backplane_spec import capture, parse, report


NEW29 = '''#cio -n bp1_sep1_ctrl -m block -t wr 32 0
rData[00]: 50 53 6F 43 1E 08 30 69 26 00 00 00 00 01 BE 00
rData[10]: 63 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00
#cio -n bp1_sep1_status -m block -t wr 32 0
rData[00]: 26 08 D2 F0 80 80 80 80 80 80 80 80 04 00 0C 00
rData[10]: 00 00 FF FF FF FF FF FF FF FF FF FF FF FF FF FF
#cio -n bp1_sep2_ctrl -m block -t wr 32 0
rData[00]: 50 53 6F 43 1E 0A 20 69 26 00 00 00 00 03 BE 00
rData[10]: 64 02 00 00 00 00 01 00 08 00 00 00 00 00 00 00
#cio -n bp1_sep2_status -m block -t wr 32 0
rData[00]: 26 02 D8 C0 80 80 04 00 3C 00 00 00 00 00 00 00
rData[10]: 00 00 FF FF FF FF FF FF FF FF FF FF FF FF FF FF'''

LEGACY_IDS = {
    '60': ('SEP 4S','04B61193',4,'sas_sata'),
    '61': ('SEP 4M','1E080069',4,'legacy_mixed'),
    '62': ('SEP 8S','112F11A1',8,'sas_sata'),
    '63': ('SEP 8S100','1E083069',8,'legacy_mixed'),
    '64': ('SEP 2M','1E0A2069',2,'legacy_mixed'),
    '65': ('SEP ITE','1E080069',4,'legacy_mixed'),
    '66': ('SEP 8SP','112F11A1',8,'sas_sata'),
}


def legacy_capture(app_id='63', values=(0x80,), **kwargs):
    ctrl,status=capture(app_id,values,**kwargs)
    ctrl[4:8]=bytes.fromhex(LEGACY_IDS[app_id][1])
    ctrl[23:32]=[0]*9
    n=len(values);status[n+5]=0;status[n+6]=(-sum(status[3:n+6]))&255
    return ctrl,status


class LegacySepTests(unittest.TestCase):
    def test_exact_new29_snapshot_has_eight_plus_two_sas_drives(self):
        rows=app.parse_sep_info(NEW29)
        for ctrl,status,name,n,start in [(rows[0],rows[1],'SEP 8S100',8,0), (rows[2],rows[3],'SEP 2M',2,8)]:
            self.assertEqual(ctrl['decode_profile'],'legacy_sep')
            self.assertEqual(ctrl['application'],name)
            self.assertEqual(ctrl['total_slots'],str(n))
            self.assertEqual(ctrl['start_slot'],str(start))
            self.assertEqual(ctrl['slot_count_source'],'Status[0x01]')
            self.assertEqual(status['status_profile'],'legacy_mixed')
            self.assertTrue(status['diagnostics_valid'])
            self.assertEqual(status['data_validation']['header_checksum'],'valid')
            self.assertEqual(status['data_validation']['status_checksum'],'valid')
            self.assertFalse(status['unknown_slots'])
            self.assertFalse(status['bp_type_fault_slots'])
            self.assertEqual(len(status['slot_observations']),n)
            self.assertIn(f'slot {start}: SAS/SATA Drive Installed (80)',status['slot_status'])
        page=app.render_backplane_registers(rows)
        self.assertIn('SAS/SATA</b>slot 0-7',page)
        self.assertIn('SAS/SATA</b>slot 8-9',page)
        self.assertIn('SEP Type</b>SEP 8S100',page)
        self.assertNotIn('Unknown',page)

    def test_legacy_identity_requires_apid_and_matching_silicon(self):
        for app_id,(name,_,_,profile) in LEGACY_IDS.items():
            ctrl,status=legacy_capture(app_id)
            for reverse in (False,True):
                candidate=ctrl.copy()
                if reverse:candidate[4:8]=candidate[4:8][::-1]
                rows=parse(candidate,status)
                self.assertEqual(rows[0]['decode_profile'],'legacy_sep')
                self.assertEqual(rows[0]['application'],name)
                self.assertEqual(rows[1]['status_profile'],profile)
                self.assertTrue(rows[1]['diagnostics_valid'])
            ctrl[4:8]=[0]*4
            rows=parse(ctrl,status,'v1_v3')
            self.assertNotEqual(rows[0]['decode_profile'],'legacy_sep')
            self.assertFalse(rows[1]['diagnostics_valid'])
            self.assertFalse(rows[1]['fault_slots'])

    def test_group_id_and_status_count_ignore_reserved_modern_offsets(self):
        ctrl,status=legacy_capture('64',(0x80,0x81),configuration=3)
        ctrl[23:30]=[0xFA,0xE0,0xD1,0xBF,0xC2,0x5A,0x01]
        rows=parse(ctrl,status,'v1_v3')
        self.assertEqual(rows[0]['total_slots'],'2')
        self.assertEqual(rows[0]['start_slot'],'8')
        self.assertEqual(rows[0]['u3_mode'],'')
        self.assertEqual(rows[1]['drive_presence'],'8 SAS/SATA; 9 NVMe Drive')
        analysis=app.analyze_backplanes(report(rows))
        device=analysis['devices'][0]
        self.assertIsNone(device['backplane_total_slots'])
        self.assertIsNone(device['starting_hfc'])
        self.assertIsNone(device['reverse_bay_numbering'])
        self.assertEqual(device['firmware']['development_flag'],'not collected')

    def test_per_sep_counts_do_not_create_modern_hfc_or_total_conflicts(self):
        r=report(app.parse_sep_info(NEW29))
        analysis=app.analyze_backplanes(r)
        self.assertEqual([d['slot_count'] for d in analysis['devices']],[8,2])
        self.assertTrue(all(d['range_valid'] for d in analysis['devices']))
        self.assertFalse(any('mapping is inconsistent' in c['title'] for c in analysis['checks']))
        self.assertIn('Rev 1.08',json.dumps(analysis['devices'][0]['evidence']))

    def test_legacy_mixed_80_81_83_and_type_faults_use_the_old_table(self):
        for app_id in ('61','63','64','65'):
            for value,field in ((0x80,'drive_presence'),(0x81,'drive_presence'),(0x83,'empty_slots'),
                                (0x84,'bp_type_fault_slots'),(0x85,'bp_type_fault_slots'),(0x86,'bp_type_fault_slots'),
                                (0xA0,'fail_slots'),(0xA1,'fail_slots')):
                rows=parse(*legacy_capture(app_id,(value,)))
                self.assertTrue(rows[1]['diagnostics_valid'])
                self.assertTrue(rows[1][field])
            for flags in range(0,0x40,8):
                rows=parse(*legacy_capture(app_id,(0x84|flags,),configuration=0xA0))
                self.assertEqual(rows[1]['bp_type_fault_slots'],'0')
                self.assertEqual(bool(rows[1]['fail_slots']),bool(flags&0x20))
                self.assertIn('BP type fault indication',json.dumps(app.run_automated_checks(report(rows))))
        rows=parse(*legacy_capture('62',(0x81,)))
        self.assertFalse(rows[1]['diagnostics_valid'])

    def test_invalid_checksum_power_identity_and_initialization_suppress_faults(self):
        cases=[]
        for kwargs in ({'communication':0x80},{'enabled':0xB0},{'configuration':0}):
            cases.append(legacy_capture('64',(0x84,),**kwargs))
        for target in ('header','payload','identity','valid'):
            ctrl,status=legacy_capture('64',(0x84,))
            if target=='header':status[2]^=1
            if target=='payload':status[4]^=1
            if target=='identity':ctrl[0]=0
            if target=='valid':
                status[4]&=~0x80;status[7]=(-sum(status[3:7]))&255
            cases.append((ctrl,status))
        for ctrl,status in cases:
            rows=parse(ctrl,status,'v1_v3')
            self.assertFalse(rows[1].get('bp_type_fault_slots'))
            self.assertFalse(any('BP type fault indication' in c['title'] for c in app.run_automated_checks(report(rows))))

    def test_legacy_c4_and_modern_80_do_not_borrow_each_others_table(self):
        old=parse(*legacy_capture('63',(0xC4,)))
        self.assertFalse(old[1]['diagnostics_valid'])
        self.assertFalse(old[1]['bp_type_fault_slots'])
        self.assertTrue(old[1]['slot_observations'][0]['limitations'])
        modern=parse(*capture('BB',(0x80,)))
        self.assertEqual(modern[1]['status_profile'],'anybay')
        self.assertFalse(modern[1]['diagnostics_valid'])

    def test_legacy_capacity_and_duplicate_snapshots_are_unverified(self):
        rows=parse(*legacy_capture('64',(0x80,)*3))
        self.assertFalse(rows[1]['diagnostics_valid'])
        self.assertIn('exceeds',json.dumps(rows[1]))
        rows=app.parse_sep_info(NEW29+'\n'+NEW29)
        self.assertTrue(all(not r['diagnostics_valid'] for r in rows if r['register_type']=='status'))

    def test_marker_four_refreshes_old_report_without_touching_history(self):
        stored=report(app.parse_sep_info(NEW29));stored['format']='v1_v3'
        stored['backplane_details_version']=4;stored['backplane_analysis']={'schema':2}
        for row in stored['sep_info']:
            row['application_id']='';row['slot_status']='Unknown';row['total_slots']='0'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/stored['id'];folder.mkdir();path=folder/'report.json'
            path.write_text(json.dumps(stored));before=path.read_bytes()
            with patch.object(app,'REPORT_DIR',root):
                updated=app.enrich_nic_report(copy.deepcopy(stored))
                self.assertEqual(updated['backplane_details_version'],6)
                self.assertEqual(updated['sep_info'][0]['total_slots'],'8')
                self.assertEqual(updated['sep_info'][2]['total_slots'],'2')
                self.assertIn('legacy_mixed',json.dumps(app.compact_report_for_ai(updated)))
                self.assertNotIn('Drive status code is not recognized',app.render_report(updated))
                self.assertNotIn('BP type fault indication',json.dumps(app.check_backplane_health_tool(updated)))
                self.assertEqual(before,path.read_bytes())


if __name__=='__main__':
    unittest.main()
