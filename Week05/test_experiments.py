"""Acceptance tests for experiment design, placement guards and saved analysis."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_experiments import (FIELDS, allocation, check_probe, estimated_seconds,
                             measurements, mpi_command, read_config, run, timed_command)
from plot_experiments import plot_results, validated_medians


class ExperimentsTest(unittest.TestCase):
    def setUp(self):
        self.config = read_config()
        self.rows = [dict(row, runtime_seconds={1: 9, 2: 1, 3: 5}[row['repetition']],
                          exit_status=0, stdout_log='sample.out', stderr_log='sample.err')
                     for row in measurements(self.config)]

    def test_grid_and_reproducible_rounds(self):
        self.assertEqual(len(self.rows), 240)
        self.assertEqual(measurements(self.config), measurements(self.config))
        expected_counts = {'nodes': 36, 'chunk_size': 84, 'image_area': 120}
        for experiment, count in expected_counts.items():
            subset = [r for r in self.rows if r['experiment'] == experiment]
            self.assertEqual(len(subset), count)
            for row in subset:
                self.assertEqual(row['ranks'], 8)
                self.assertEqual(row['ranks_per_host'] * row['nodes'], 8)
                if experiment != 'nodes':
                    self.assertEqual(row['nodes'], 2)
                if experiment != 'chunk_size':
                    self.assertEqual(row['chunk_size'], 10)
                if experiment != 'image_area':
                    self.assertEqual((row['width'], row['height']), (3000, 3000))
        self.assertEqual(sorted({r['chunk_size'] for r in self.rows if r['experiment'] == 'chunk_size'}),
                         [3, 11, 23, 46, 93, 187, 375])
        self.assertEqual(sorted({r['width'] for r in self.rows if r['experiment'] == 'image_area'}),
                         [1000, 2211, 2963, 3559, 4069, 4522, 4933, 5312, 5667, 6000])
        self.assertEqual(self.config['defaults']['iterations'], 100)
        self.assertEqual(self.config['defaults']['xlim'], '-2.2:0.75')
        self.assertEqual(self.config['defaults']['ylim'], '-1.3:1.3')

    def test_allocation_validation(self):
        hosts = [f'n{i}' for i in range(8)]
        env = {'LSB_MCPU_HOSTS': ' '.join(f'{h} 4' for h in hosts)}
        self.assertEqual(list(allocation(env, self.config)), hosts)
        self.assertEqual(list(allocation({'LSB_HOSTS': ' '.join(h for h in hosts for _ in range(4))}, self.config)), hosts)
        for bad in [{}, {'LSB_MCPU_HOSTS': 'n0 32'}, {'LSB_MCPU_HOSTS': 'n0'}]:
            with self.assertRaises(ValueError):
                allocation(bad, self.config)

    def test_all_placement_guards(self):
        for nodes in [2, 4, 8]:
            hosts = [f'n{i}' for i in range(nodes)]
            records = [dict(rank=i, host=hosts[i // (8 // nodes)], cpu_model='Intel E5-2660 v3',
                            affinity=[i % (8 // nodes)], physical_cores=[['0', str(i % (8 // nodes))]])
                       for i in range(8)]
            check_probe(records, hosts, 8 // nodes, 'E5-2660 v3')
            command = mpi_command('hosts.txt', dict(ranks=8, ranks_per_host=8 // nodes), 'probe.py', [])
            self.assertIn(f'ppr:{8 // nodes}:node', command)
            self.assertIn('--bind-to', command)
            self.assertEqual(command[command.index('--rank-by') + 1], 'slot')
            for field, value in [('host', 'wrong'), ('cpu_model', 'wrong'), ('physical_cores', [])]:
                bad = [dict(r) for r in records]
                bad[0][field] = value
                with self.assertRaises(ValueError):
                    check_probe(bad, hosts, 8 // nodes, 'E5-2660 v3')

    def test_any_model_is_accepted_but_mixed_models_are_rejected(self):
        hosts = [f'n{i}' for i in range(8)]
        records = [dict(rank=i, host=host, cpu_model='Intel Xeon Gold 6226R',
                        affinity=[0], physical_cores=[['0', '0']])
                   for i, host in enumerate(hosts)]
        self.assertIsNone(self.config['cluster']['model'])
        self.assertIsNone(self.config['cluster']['cpu_model_contains'])
        self.assertEqual(check_probe(records, hosts, 1), 'Intel Xeon Gold 6226R')
        mixed = [dict(r) for r in records]
        mixed[-1]['cpu_model'] = 'AMD EPYC 9354'
        with self.assertRaisesRegex(ValueError, 'same CPU model'):
            check_probe(mixed, hosts, 1)
        with self.assertRaisesRegex(ValueError, 'changed between placement probes'):
            check_probe(records, hosts, 1, expected_model='AMD EPYC 9354')

    def test_known_medians_and_rejections(self):
        points = validated_medians(self.rows, self.config)
        self.assertEqual(len(points), 80)
        self.assertTrue(all(p['median_seconds'] == 5 for p in points))
        cases = [self.rows[:-1], self.rows + [self.rows[0]],
                 [dict(r, exit_status=1) if i == 0 else r for i, r in enumerate(self.rows)],
                 [dict(r, runtime_seconds=float('nan')) if i == 0 else r for i, r in enumerate(self.rows)],
                 [dict(r, ranks=4) if i == 0 else r for i, r in enumerate(self.rows)]]
        for rows in cases:
            with self.assertRaises(ValueError):
                validated_medians(rows, self.config)

    def test_pilot_estimate_has_allowance(self):
        pilots = [dict(implementation=impl, width=side, runtime_seconds=1 if side == 100 else 10)
                  for impl in self.config['implementations'] for side in self.config['pilot']['sides']]
        expected = sum(max(1, 1 + 9 * (row['actual_area'] - 10_000) / (9_000_000 - 10_000)) for row in self.rows) * 2
        self.assertAlmostEqual(estimated_seconds(self.config, pilots), expected)

    def test_historical_grid_and_results_still_validate(self):
        root = Path(__file__).resolve().parent / 'results' / 'job_29611697'
        with (root / 'measurements.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        old_config = read_config(root / 'experiments.yaml')
        points = validated_medians(rows, old_config)
        self.assertEqual(len(points), 80)
        self.assertEqual(old_config['defaults']['width'], 1000)
        self.assertEqual(max(r['width'] for r in points), 2000)

    def test_launcher_failure_and_timeout_are_logged(self):
        with tempfile.TemporaryDirectory() as name:
            out, err = Path(name) / 'out', Path(name) / 'err'
            duration, status = timed_command(['/nonexistent-mpi-launcher'], out, err, 1)
            self.assertEqual(status, 127)
            self.assertGreater(duration, 0)
            self.assertTrue(err.read_text())
            process = unittest.mock.Mock()
            import subprocess
            process.wait.side_effect = [subprocess.TimeoutExpired('mpirun', 1), 0]
            process.pid = 12345
            with patch('run_experiments.subprocess.Popen', return_value=process), patch('run_experiments.os.killpg') as kill:
                _, status = timed_command(['mpirun'], out, err, 1)
                self.assertEqual(status, 124)
                kill.assert_called_once()
                self.assertIn('budget exceeded', err.read_text())

    def test_runner_persists_failure_and_stops(self):
        calls = []
        def fake_command(command, out, err, timeout):
            calls.append(command)
            err.write_text('')
            if 'mpi_probe.py' in command[-1]:
                nodes = int(Path(command[command.index('--hostfile') + 1]).stem.split('_')[1])
                per_host = 8 // nodes
                records = [dict(rank=i, host=f'n{i // per_host}', cpu_model='E5-2660 v3',
                                affinity=[i % per_host], physical_cores=[['0', str(i % per_host)]])
                           for i in range(8)]
                out.write_text(json.dumps(records))
            else:
                out.write_text('sample output')
            return 0.01, (2 if len(calls) == 12 else 0)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / 'results'
            env = dict(LSB_JOBID='test', LSB_MCPU_HOSTS=' '.join(f'n{i} 4' for i in range(8)))
            with patch.dict(os.environ, env), patch('run_experiments.timed_command', side_effect=fake_command), patch('run_experiments.importlib.metadata.version', return_value='test'):
                with self.assertRaisesRegex(RuntimeError, 'Measurement failed'):
                    run(self.config, root)
            self.assertEqual(len(calls), 12)  # 3 probes, 8 pilots, first measurement.
            with (root / 'measurements.csv').open() as stream:
                saved = list(csv.DictReader(stream))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]['exit_status'], '2')
            self.assertTrue((root / saved[0]['stdout_log']).exists())
            metadata = json.loads((root / 'metadata.json').read_text())
            self.assertEqual(metadata['status'], 'failed')
            self.assertEqual(len(metadata['pilots']), 8)
            self.assertEqual(len(metadata['probes']), 3)

    def test_three_figures_from_saved_sample(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'experiments.yaml').write_text(json.dumps(self.config))
            with (root / 'measurements.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(self.rows)
            paths = plot_results(root)
            self.assertEqual({p.name for p in paths},
                             {f'{name}.{ext}' for name in ['nodes', 'chunk_size', 'image_area'] for ext in ['png', 'pdf']})
            self.assertTrue(all(p.stat().st_size > 0 for p in paths))


if __name__ == '__main__':
    unittest.main()
