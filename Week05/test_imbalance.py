"""Acceptance checks for the imbalance grid, profile validation and analysis."""
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from run_experiments import FIELDS, allocation
from run_imbalance import read_config, measurements, profile_records
from analyse_imbalance import analyse, validate

HERE = Path(__file__).resolve().parent


def static_profile(width, chunk):
    rows = [0] * 8
    for index, start in enumerate(range(0, width, chunk)):
        rows[index % 8] += min(chunk, width - start)
    return [dict(rank=r, mode='interleaved', rows=rows[r], compute_seconds=1. + r, send_seconds=.1,
                 receive_seconds=.1, algorithm_seconds=9., final_barrier_seconds=.1) for r in range(8)]


def dynamic_profile(width, chunk):
    starts = list(range(0, width, chunk))
    records = [dict(rank=r, mode='dynamic', rows=0, chunks=0, chunk_starts=[], compute_seconds=0.,
                    send_seconds=.1, receive_seconds=.1, algorithm_seconds=9., final_barrier_seconds=.1)
               for r in range(8)]
    for index, start in enumerate(starts):
        worker = records[1 + index % 7]
        worker['rows'] += min(chunk, width - start); worker['chunks'] += 1
        worker['chunk_starts'].append(start); worker['compute_seconds'] += 1.
    return records


class ImbalanceTest(unittest.TestCase):
    def fixture(self, directory):
        config = read_config()
        directory.mkdir(parents=True); (directory / 'profiles').mkdir()
        (directory / 'experiments.yaml').write_text(json.dumps(config))
        (directory / 'metadata.json').write_text(json.dumps(dict(status='measurements_complete')))
        rows = []
        for index, row in enumerate(measurements(config)):
            path = f'profiles/run_{index}.json'
            make = static_profile if row['implementation'] == 'static_blocking' else dynamic_profile
            (directory / path).write_text(json.dumps(make(row['width'], row['chunk_size'])))
            rows.append(dict(row, runtime_seconds=40 + row['repetition'], exit_status=0,
                             stdout_log='x.out', stderr_log='x.err', profile_log=path))
        with (directory / 'measurements.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS + ['profile_log']); writer.writeheader(); writer.writerows(rows)
        return config, rows

    def test_grid_and_allocation(self):
        config = read_config(); rows = measurements(config)
        self.assertEqual(len(rows), 36)
        self.assertEqual(rows, measurements(config))
        self.assertEqual({r['chunk_size'] for r in rows}, {3, 10, 46, 93, 187, 375})
        for row in rows:
            self.assertEqual((row['ranks'], row['nodes'], row['ranks_per_host'], row['width']), (8, 2, 4, 3000))
        self.assertEqual(dict(allocation({'LSB_MCPU_HOSTS': 'n0 4 n1 4'}, config)), {'n0': 4, 'n1': 4})
        with self.assertRaises(ValueError): allocation({'LSB_MCPU_HOSTS': 'n0 8'}, config)

    def test_profile_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'p.json'
            path.write_text(json.dumps(dynamic_profile(3000, 46)))
            self.assertEqual(sum(r['chunks'] for r in profile_records(path, 'dynamic_blocking', 3000, 46)),
                             math.ceil(3000 / 46))
            bad = dynamic_profile(3000, 46); bad[0]['rows'] = 5
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError): profile_records(path, 'dynamic_blocking', 3000, 46)
            path.write_text(json.dumps(static_profile(3000, 46)))
            with self.assertRaises(ValueError): profile_records(path, 'dynamic_blocking', 3000, 46)
            profile_records(path, 'static_blocking', 3000, 46)

    def test_analysis_outputs(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            directory = Path(temporary) / 'results'
            config, rows = self.fixture(directory)
            paths = analyse(directory)
            self.assertEqual(len(paths), 4)
            self.assertTrue(all(p.stat().st_size > 0 for p in paths))
            summary = (directory / 'SUMMARY.md').read_text()
            self.assertIn('Dynamic scheduler: median chunks computed per worker', summary)
            self.assertEqual(json.loads((directory / 'metadata.json').read_text())['status'], 'complete')
            (directory / rows[0]['profile_log']).unlink()
            with self.assertRaises(FileNotFoundError): validate(directory)


if __name__ == '__main__': unittest.main()
