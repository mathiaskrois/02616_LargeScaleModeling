"""Verify the heavier two-version grid, statistics, reports and source control."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from run_followup import read_config,measurements
from run_experiments import FIELDS,allocation
from plot_experiments import validated_medians
from analyse_heavy_chunks import analyse
from publish_results import validate,update_readme

HERE=Path(__file__).resolve().parent


class HeavyChunksTest(unittest.TestCase):
    def test_grid_and_legacy_source(self):
        config=read_config(HERE/'heavy_chunks.yaml');rows=measurements(config)
        self.assertTrue(all(chunk==1 for width,height,chunk in config['preflight']['correctness_cases']))
        self.assertEqual(len(rows),10);self.assertEqual(rows,measurements(config))
        self.assertEqual({r['chunk_size'] for r in rows},{1})
        self.assertEqual(len({r['implementation'] for r in rows}),2)
        for row in rows:self.assertEqual((row['nodes'],row['ranks'],row['ranks_per_host'],row['width'],row['height']),(2,8,4,3000,3000))
        self.assertEqual(dict(allocation({'LSB_MCPU_HOSTS':'n0 4 n1 4'},config)),{'n0':4,'n1':4})
        self.assertEqual((HERE/'Mandelbrot_blocking_static_legacy.py').read_bytes(),
                         (HERE/'results/job_29618553/sources/Mandelbrot_blocking_static.py').read_bytes())
        self.assertNotEqual((HERE/'Mandelbrot_blocking_static.py').read_bytes(),(HERE/'Mandelbrot_blocking_static_legacy.py').read_bytes())

    def test_medians_rejections_and_completed_report(self):
        config=read_config(HERE/'heavy_chunks.yaml')
        rows=[dict(row,runtime_seconds={1:1,2:9,3:5,4:3,5:7}[row['repetition']],exit_status=0,stdout_log='a.out',stderr_log='a.err',profile_log='') for row in measurements(config)]
        self.assertTrue(all(p['median_seconds']==5 for p in validated_medians(rows,config)))
        for bad in (rows[:-1],rows+[rows[0]],[dict(r,exit_status=1) for r in rows]):
            with self.assertRaises(ValueError):validated_medians(bad,config)
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            directory=Path(temporary);(directory/'experiments.yaml').write_text(json.dumps(config));(directory/'metadata.json').write_text(json.dumps(dict(status='measurements_complete',job_id='fixture',cpu_model='fixture')))
            with (directory/'measurements.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=FIELDS+['profile_log']);writer.writeheader();writer.writerows(rows)
            analyse(directory)
            self.assertEqual(validate(directory)[2],2)
            self.assertTrue((directory/'figures/chunk_size_comparison.png').stat().st_size>0)
            report=(directory/'SUMMARY.md').read_text();self.assertIn('expected chunk size 1',report);self.assertIn('3000×3000',report)
            metadata=json.loads((directory/'metadata.json').read_text())
            original='# Project\n<!-- heavy-chunks:start -->\nPending\n<!-- heavy-chunks:end -->\nHistorical plots\n'
            updated=update_readme(original,directory,metadata,config)
            self.assertIn('Historical plots',updated);self.assertIn('10 successful',updated)
            self.assertEqual(update_readme(updated,directory,metadata,config),updated)
            (directory/'figures/chunk_size_comparison.pdf').unlink()
            with self.assertRaises(ValueError):validate(directory)


if __name__=='__main__':unittest.main()
