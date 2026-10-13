"""Acceptance checks for the follow-up grid, diagnostics, plots and publication."""
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from run_experiments import FIELDS, allocation
from run_followup import read_config, measurements
from plot_experiments import validated_medians
from analyse_followup import analyse, validate
from publish_results import publish, update_readme

HERE=Path(__file__).resolve().parent


class FollowupTest(unittest.TestCase):
    def fixture(self,directory):
        config=read_config()
        directory.mkdir(parents=True)
        (directory/'profiles').mkdir()
        (directory/'experiments.yaml').write_text(json.dumps(config))
        (directory/'metadata.json').write_text(json.dumps(dict(status='complete',job_id='fixture',cpu_model='fixture CPU')))
        rows=[]
        for index,row in enumerate(measurements(config)):
            row=dict(row,runtime_seconds={1:1,2:9,3:5,4:3,5:7}[row['repetition']],
                exit_status=0,stdout_log='sample.out',stderr_log='sample.err',profile_log='')
            if row['implementation'] in ('static_blocking','static_blocking_interleaved'):
                row['profile_log']=f'profiles/run_{index}.json'
                mode='original' if row['implementation']=='static_blocking' else 'interleaved'
                records=[dict(rank=rank,mode=mode,rows=375,compute_seconds=1.,send_seconds=2.,
                    receive_seconds=3.,algorithm_seconds=6.,final_barrier_seconds=.1) for rank in range(8)]
                (directory/row['profile_log']).write_text(json.dumps(records))
            rows.append(row)
        with (directory/'measurements.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS+['profile_log']);writer.writeheader();writer.writerows(rows)
        return config,rows

    def test_grid_and_allocation(self):
        config=read_config();rows=measurements(config)
        self.assertEqual(len(rows),175)
        self.assertEqual(rows,measurements(config))
        self.assertEqual(sum(r['experiment']=='threshold' for r in rows),125)
        self.assertEqual(sum(r['experiment']=='one_vs_two' for r in rows),50)
        for row in rows:
            self.assertEqual((row['ranks'],row['width'],row['height']),(8,3000,3000))
            self.assertEqual(row['ranks_per_host']*row['nodes'],8)
            self.assertIn(row['chunk_size'],[8,9,10,11,12])
            if row['experiment']=='threshold': self.assertEqual(row['nodes'],2)
            else: self.assertEqual(row['chunk_size'],10)
        self.assertEqual(dict(allocation({'LSB_MCPU_HOSTS':'n0 8 n1 8'},config)),{'n0':8,'n1':8})
        with self.assertRaises(ValueError): allocation({'LSB_MCPU_HOSTS':'n0 16'},config)

    def test_known_medians_and_reject_incomplete_failed_profiles(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            directory=Path(temporary)/'results'
            config,rows=self.fixture(directory)
            self.assertEqual(len(validate(directory)[2]),35)
            self.assertTrue(all(p['median_seconds']==5 for p in validated_medians(rows,config)))
            for bad in (rows[:-1],[dict(r,exit_status=1) if i==0 else r for i,r in enumerate(rows)],rows+[rows[0]]):
                with self.assertRaises(ValueError): validated_medians(bad,config)
            next((directory/'profiles').iterdir()).unlink()
            with self.assertRaises(FileNotFoundError): validate(directory)

    def test_plots_report_and_readme(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            directory=Path(temporary)/'results';config,rows=self.fixture(directory)
            paths=analyse(directory)
            self.assertEqual(len(paths),6)
            self.assertTrue(all(p.stat().st_size>0 for p in paths))
            self.assertIn('Communication diagnostics',(directory/'SUMMARY.md').read_text())
            metadata=json.loads((directory/'metadata.json').read_text())
            original='# Project\n\n<!-- latest-benchmark:start -->\nHistorical plots\n<!-- latest-benchmark:end -->\n'
            updated=update_readme(original,directory,metadata,config)
            self.assertIn('Historical plots',updated)
            self.assertIn('175 successful',updated)
            self.assertEqual(update_readme(updated,directory,metadata,config),updated)

    def test_publish_to_local_git_remote_without_network(self):
        # Exercise the real credential setup, clone, copy, README, commit and push path.
        # A local bare remote makes this deterministic and avoids GitHub mutations.
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            root=Path(temporary);remote=root/'remote.git';repo=root/'repo';repo.mkdir()
            def git(*args,cwd=repo):
                return subprocess.run(['git',*args],cwd=cwd,check=True,text=True,capture_output=True).stdout
            git('init','--bare','--initial-branch=main',str(remote))
            git('init','--initial-branch=main')
            git('config','user.name','Test');git('config','user.email','test@example.invalid')
            (repo/'README.md').write_text('# Project\n\nExisting documentation.\n')
            git('add','README.md');git('commit','-m','Initial');git('remote','add','origin',str(remote));git('push','origin','main')
            directory=repo/'Week05/results/followup_job_fixture'
            config,rows=self.fixture(directory)
            (directory/'figures').mkdir()
            for name in ('threshold','one_vs_two','rank_timings'):
                for suffix in ('png','pdf'): (directory/'figures'/f'{name}.{suffix}').write_bytes(b'fixture')
            (directory/'SUMMARY.md').write_text('Verified fixture summary')
            with patch('publish_results.__file__',str(repo/'Week05/publish_results.py')):
                publish(directory)
            git('fetch','origin','main')
            readme=git('show','origin/main:README.md')
            self.assertIn('175 successful',readme)
            self.assertIn('Existing documentation',readme)
            self.assertEqual(git('show','origin/main:Week05/results/followup_job_fixture/SUMMARY.md'),'Verified fixture summary')


if __name__=='__main__': unittest.main()
