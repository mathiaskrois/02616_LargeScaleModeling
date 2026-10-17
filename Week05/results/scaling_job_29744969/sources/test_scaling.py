"""Acceptance checks for the scaling grid, placement and analysis."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from run_experiments import FIELDS, allocation
from run_scaling import read_config, measurements, placement
from analyse_scaling import analyse, validate

HERE = Path(__file__).resolve().parent


class ScalingTest(unittest.TestCase):
    def fixture(self, directory):
        config = read_config()
        directory.mkdir(parents=True)
        (directory / 'experiments.yaml').write_text(json.dumps(config))
        (directory / 'metadata.json').write_text(json.dumps(dict(status='measurements_complete')))
        rows = [dict(row, runtime_seconds=300 / row['ranks'] + row['repetition'], exit_status=0,
                     stdout_log='x.out', stderr_log='x.err') for row in measurements(config)]
        with (directory / 'measurements.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
        return config, rows

    def test_grid_and_placement(self):
        config = read_config(); rows = measurements(config)
        self.assertEqual(len(rows), 90)
        self.assertEqual(rows, measurements(config))
        self.assertEqual(sum(r['experiment'] == 'scaling' for r in rows), 42)
        self.assertEqual(sum(r['experiment'] == 'nodes' for r in rows), 48)
        self.assertEqual([placement(p, 8) for p in (1, 2, 4, 8, 16, 32, 64)],
                         [(1, 1), (1, 2), (1, 4), (1, 8), (2, 8), (4, 8), (8, 8)])
        for row in rows:
            self.assertEqual(row['nodes'] * row['ranks_per_host'], row['ranks'])
            self.assertLessEqual(row['ranks_per_host'], 8)
            if row['experiment'] == 'scaling': self.assertEqual(row['width'], 3000)
            else: self.assertEqual(row['ranks'], 8); self.assertIn(row['width'], (300, 3000))
        with self.assertRaises(ValueError): placement(20, 8)
        hosts = ' '.join(f'n{i} 8' for i in range(8))
        self.assertEqual(len(allocation({'LSB_MCPU_HOSTS': hosts}, config)), 8)
        with self.assertRaises(ValueError): allocation({'LSB_MCPU_HOSTS': 'n0 8 n1 8'}, config)

    def test_analysis_outputs(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            directory = Path(temporary) / 'results'
            config, rows = self.fixture(directory)
            self.assertEqual(len(analyse(directory)), 4)
            summary = (directory / 'SUMMARY.md').read_text()
            self.assertIn('Strong scaling', summary)
            self.assertIn('| Nonblocking static | 64 | 8 |', summary)
            with (directory / 'measurements.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows[:-1])
            with self.assertRaises(ValueError): validate(directory)


if __name__ == '__main__': unittest.main()
