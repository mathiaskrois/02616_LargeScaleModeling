"""Check image equality guards, full-grid coverage and the five-version overview."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
import runpy
import sys
from unittest.mock import patch
import numpy as np

from run_experiments import read_config
from verify_and_benchmark import cases,compare_images,validate_saved,report,FIELDS,TITLES,serial_calculation_namespace
from publish_results import validate,update_readme

HERE=Path(__file__).resolve().parent


class FiveVersionsTest(unittest.TestCase):
    def test_full_grid_and_exact_chunk_checks(self):
        config=read_config();grid=cases(config)
        self.assertEqual(len(grid),18)
        self.assertTrue(all((side,side,10) in grid for side in config['experiments']['image_area']['sides']))
        self.assertTrue(all((3000,3000,chunk) in grid for chunk in config['experiments']['chunk_size']['values']))
        reference=np.arange(53*47,dtype=np.float64).reshape(53,47)
        self.assertEqual(compare_images(reference.copy(),reference,10)[0],6)
        bad=reference.copy();bad[52,46]+=1
        with self.assertRaises(ValueError):compare_images(bad,reference,10)
        with self.assertRaises(ValueError):compare_images(reference.T,reference,10)
        with self.assertRaises(ValueError):compare_images(reference.astype(np.float32),reference,10)

    def test_serial_calculation_prefix_matches_complete_original(self):
        import matplotlib
        matplotlib.use('Agg')
        with patch.object(sys, 'argv', ['Mandelbrot.py','3','9x11','-2.2:0.75','-1.3:1.3']):
            prefix=serial_calculation_namespace(HERE/'Mandelbrot.py')['image']
        with patch.object(sys, 'argv', ['Mandelbrot.py','3','9x11','-2.2:0.75','-1.3:1.3']), patch('matplotlib.pyplot.savefig'), patch('matplotlib.pyplot.show'):
            full=runpy.run_path(str(HERE/'Mandelbrot.py'),run_name='__main__')['image']
        self.assertTrue(np.array_equal(prefix,full))

    def test_report_rejects_missing_or_wrong_results(self):
        heavy=read_config();parallel=heavy['implementations']
        config=dict(suite='five_versions',heavy_config=heavy,parallel_implementations=parallel,
                    defaults=dict(heavy['defaults'],repetitions=3),parent_job_id='parent',output=dict(csv='measurements.csv'))
        evidence=[dict(implementation=impl,width=w,height=h,chunk_size=c,chunk_checks=(w+c-1)//c,np_array_equal=True,exit_status=0)
                  for impl in parallel for w,h,c in cases(heavy)]
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            directory=Path(temporary);(directory/'experiments.yaml').write_text(json.dumps(config))
            metadata=dict(status='measurements_complete',job_id='fixture',cpu_model='fixture',correctness=evidence)
            (directory/'metadata.json').write_text(json.dumps(metadata))
            rows=[dict(implementation=impl,repetition=rep,ranks=1 if impl=='serial_reference' else 8,
                width=3000,height=3000,chunk_size=10,runtime_seconds={1:3,2:1,3:2}[rep]*(8 if impl=='serial_reference' else 1),
                exit_status=0,np_array_equal=True,chunk_checks=300,image_sha256='fixture',stdout_log='out',stderr_log='err')
                for impl in TITLES for rep in (1,2,3)]
            def save_rows(samples):
                with (directory/'measurements.csv').open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows(samples)
            save_rows(rows);self.assertEqual(len(validate_saved(directory)[2]),15)
            report(directory);self.assertEqual(validate(directory)[2],5)
            summary=(directory/'SUMMARY.md').read_text();self.assertIn('72',summary);self.assertIn('8.00×',summary)
            metadata=json.loads((directory/'metadata.json').read_text())
            original='# Project\n<!-- latest-benchmark:start -->\nExisting full-suite plots\n<!-- latest-benchmark:end -->\n'
            updated=update_readme(original,directory,metadata,config)
            self.assertIn('Existing full-suite plots',updated);self.assertIn('Original Mandelbrot.py',updated)
            self.assertEqual(update_readme(updated,directory,metadata,config),updated)
            save_rows(rows[:-1])
            with self.assertRaises(ValueError):validate_saved(directory)
            save_rows([dict(r,np_array_equal=False) if i==0 else r for i,r in enumerate(rows)])
            with self.assertRaises(ValueError):validate_saved(directory)
            save_rows(rows);metadata['correctness'][0]['np_array_equal']=False
            (directory/'metadata.json').write_text(json.dumps(metadata))
            with self.assertRaises(ValueError):validate_saved(directory)


if __name__=='__main__':unittest.main()
