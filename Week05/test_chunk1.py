"""Check the restricted three-row replacement and its provenance."""
import json
from pathlib import Path
import unittest

from retest_chunk1 import OLD, read_rows, replacement_rows, target, validate_retest
from plot_experiments import validated_medians
from publish_results import update_chunk1_readme


class Chunk1Test(unittest.TestCase):
    def setUp(self):
        self.old=read_rows(OLD/'measurements.csv')
        self.new=[dict(r,runtime_seconds=str(2+int(r['repetition'])),stdout_log='logs/new.out',stderr_log='logs/new.err') for r in self.old if target(r)]

    def test_only_target_rows_replaced(self):
        result=replacement_rows(self.old,self.new,'new','revision')
        self.assertEqual(len(result),240)
        self.assertEqual(sum(r['source_job_id']=='new' for r in result),3)
        for old,new in zip(self.old,result):
            if not target(old):
                for key in old:
                    if key not in ('stdout_log','stderr_log'): self.assertEqual(old[key],new[key])
        points=validated_medians(result,json.loads((OLD/'experiments.yaml').read_text()))
        point=next(p for p in points if target(p))
        self.assertEqual(point['median_seconds'],4)

    def test_incomplete_failed_duplicate_and_wrong_targets_rejected(self):
        for rows in (self.new[:-1],self.new+[self.new[0]],
                [dict(r,exit_status=1) for r in self.new],
                [dict(r,chunk_size=3) for r in self.new]):
            with self.assertRaises(ValueError): validate_retest(rows,self.old)

    def test_readme_preserves_other_results(self):
        original='# Project\n<!-- followup:start -->\nFollow-up figures\n<!-- followup:end -->\n![Runtime versus chunk size](Week05/results/job_29611697/figures/chunk_size.png)\n'
        updated=update_chunk1_readme(original,Path('chunk1_job_test'),{'job_id':'test'})
        self.assertIn('Follow-up figures',updated)
        self.assertIn('labels it purple',updated)
        self.assertIn('chunk1_job_test/figures/chunk_size.png',updated)
        self.assertEqual(update_chunk1_readme(updated,Path('chunk1_job_test'),{'job_id':'test'}),updated)


if __name__=='__main__': unittest.main()
