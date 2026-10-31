import json
import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


# Allow running tests standalone without dotbot installed globally.
class _MockPlugin:
    supports_dry_run = False

    def __init__(self, context):
        self._context = context
        self._log = logging.getLogger('test.template')


if 'dotbot' not in sys.modules:
    try:
        import dotbot  # noqa: F401
    except ImportError:
        _mock_dotbot = MagicMock()
        _mock_dotbot.Plugin = _MockPlugin
        sys.modules['dotbot'] = _mock_dotbot
        sys.modules['dotbot.util'] = MagicMock()
        sys.modules['dotbot.util.common'] = MagicMock(
            normslash=lambda path: path.replace('/', '\\')
            if sys.platform == 'win32'
            else path
        )

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from template import Template  # noqa: E402

try:
    import yaml as _real_yaml
except ImportError:
    _real_yaml = None


def _make_plugin(base_dir, defaults=None, dry_run=False):
    context = MagicMock()
    context.base_directory.return_value = base_dir
    context.defaults.return_value = defaults if defaults is not None else {}
    context.dry_run.return_value = dry_run
    plugin = Template(context)
    plugin._log = MagicMock()
    return plugin


class TestDirectiveHandling(unittest.TestCase):
    def test_can_handle(self):
        plugin = _make_plugin('/tmp')
        self.assertTrue(plugin.can_handle('template'))
        self.assertFalse(plugin.can_handle('link'))
        self.assertTrue(plugin.supports_dry_run)

    def test_invalid_directive_raises(self):
        plugin = _make_plugin('/tmp')
        with self.assertRaises(ValueError):
            plugin.handle('link', [])

    def test_invalid_data_types_return_false(self):
        plugin = _make_plugin('/tmp')
        self.assertFalse(plugin.handle('template', 'not-a-list-or-dict'))
        self.assertFalse(plugin.handle('template', ['not-a-mapping']))
        self.assertFalse(plugin.handle('template', [{'a': {}, 'b': {}}]))
        self.assertFalse(plugin.handle('template', {123: {}}))

    def test_invalid_defaults_type_returns_false(self):
        plugin = _make_plugin('/tmp', defaults={'template': 'invalid'})
        self.assertFalse(plugin.handle('template', {}))


class TestInlineAndSyntaxRendering(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_dir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, rel_path, content):
        full = os.path.join(self.base_dir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
        return full

    def test_list_and_mapping_syntax_with_parent_dir_creation(self):
        self._write('src.j2', 'hello {{ NAME }} from {{ HOME_DIR }}\n')
        target_a = os.path.join(self.base_dir, 'nested', 'a.txt')
        target_b = os.path.join(self.base_dir, 'nested', 'b.txt')
        plugin = _make_plugin(self.base_dir)

        self.assertTrue(
            plugin.handle(
                'template',
                [
                    {
                        target_a: {
                            'source_file': 'src.j2',
                            'params': {'NAME': 'Alice'},
                        }
                    }
                ],
            )
        )
        self.assertTrue(
            plugin.handle(
                'template',
                {
                    target_b: {
                        'source_file': 'src.j2',
                        'params': {'NAME': 'Bob'},
                    }
                },
            )
        )

        with open(target_a, 'r', encoding='utf-8') as f:
            content_a = f.read()
        with open(target_b, 'r', encoding='utf-8') as f:
            content_b = f.read()

        home = os.path.expanduser('~')
        self.assertEqual(content_a, f'hello Alice from {home}\n')
        self.assertEqual(content_b, f'hello Bob from {home}\n')

    def test_structured_params_and_defaults_merging(self):
        self._write(
            'loop.j2',
            '{% for item in ITEMS %}{{ item }}{% if not loop.last %},{% endif %}{% endfor %}\n',
        )
        target = os.path.join(self.base_dir, 'out.txt')
        plugin = _make_plugin(
            self.base_dir,
            defaults={'template': {'source_file': 'loop.j2'}},
        )
        self.assertTrue(
            plugin.handle(
                'template',
                {target: {'params': {'ITEMS': ['x', 'y', 'z']}}},
            )
        )
        with open(target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'x,y,z\n')

    def test_env_var_expansion_in_paths(self):
        tpl_dir = os.path.join(self.base_dir, 'templates')
        out_dir = os.path.join(self.base_dir, 'output')
        self._write('templates/env.j2', 'val={{ KEY }}\n')
        self._write('templates/params.json', json.dumps({'KEY': 'expanded'}))
        plugin = _make_plugin(self.base_dir)

        with patch.dict(
            os.environ, {'TPL_SRC': tpl_dir, 'TPL_OUT': out_dir}, clear=False
        ):
            self.assertTrue(
                plugin.handle(
                    'template',
                    {
                        '$TPL_OUT/result.conf': {
                            'source_file': '$TPL_SRC/env.j2',
                            'params_file': '$TPL_SRC/params.json',
                        }
                    },
                )
            )

        with open(os.path.join(out_dir, 'result.conf'), 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'val=expanded\n')


class TestPlatformUname(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_dir = self._tmpdir.name
        with open(
            os.path.join(self.base_dir, 'os.j2'), 'w', encoding='utf-8'
        ) as f:
            f.write('helper={{ HELPER }}\n')

    def tearDown(self):
        self._tmpdir.cleanup()

    @patch('platform.system', return_value='Darwin')
    def test_uname_resolves_darwin(self, _mock_sys):
        target = os.path.join(self.base_dir, 'out')
        plugin = _make_plugin(self.base_dir)
        ok = plugin.handle(
            'template',
            {
                target: {
                    'source_file': 'os.j2',
                    'params': {
                        '__UNAME__': {
                            'HELPER': {'Darwin': 'osxkeychain', 'Linux': 'cache'}
                        }
                    },
                }
            },
        )
        self.assertTrue(ok)
        with open(target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'helper=osxkeychain\n')

    @patch('platform.system', return_value='Windows')
    def test_uname_unsupported_platform_fails(self, _mock_sys):
        target = os.path.join(self.base_dir, 'out')
        plugin = _make_plugin(self.base_dir)
        ok = plugin.handle(
            'template',
            {
                target: {
                    'source_file': 'os.j2',
                    'params': {'__UNAME__': {'HELPER': {'Linux': 'cache'}}},
                }
            },
        )
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(target))


class TestExternalParamsFiles(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_dir = self._tmpdir.name
        self._other_cwd = tempfile.TemporaryDirectory()
        with open(
            os.path.join(self.base_dir, 'cfg.j2'), 'w', encoding='utf-8'
        ) as f:
            f.write('a={{ A }} b={{ B }} c={{ C }}\n')

    def tearDown(self):
        self._other_cwd.cleanup()
        self._tmpdir.cleanup()

    def _write(self, rel_path, content):
        full = os.path.join(self.base_dir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
        return full

    def test_json_and_toml_relative_to_base_directory(self):
        self._write('base.toml', 'A = "from_toml"\nB = "base_b"\nC = "base_c"\n')
        self._write('override.json', json.dumps({'B': 'from_json'}))
        target = os.path.join(self.base_dir, 'rendered.txt')
        plugin = _make_plugin(self.base_dir)

        prev_cwd = os.getcwd()
        try:
            os.chdir(self._other_cwd.name)
            ok = plugin.handle(
                'template',
                {
                    target: {
                        'source_file': 'cfg.j2',
                        'params_file': ['./base.toml', './override.json'],
                        'params': {'C': 'from_inline'},
                    }
                },
            )
        finally:
            os.chdir(prev_cwd)

        self.assertTrue(ok)
        with open(target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'a=from_toml b=from_json c=from_inline\n')

    @patch('platform.system', return_value='Linux')
    def test_layer_precedence_with_uname_override(self, _mock_sys):
        self._write(
            'base.json',
            json.dumps(
                {
                    'A': '1',
                    'C': '3',
                    '__UNAME__': {'B': {'Linux': 'linux_default', 'Darwin': 'mac'}},
                }
            ),
        )
        self._write('local.json', json.dumps({'B': 'flat_override'}))
        target = os.path.join(self.base_dir, 'out.txt')
        plugin = _make_plugin(self.base_dir)

        self.assertTrue(
            plugin.handle(
                'template',
                {
                    target: {
                        'source_file': 'cfg.j2',
                        'params_file': ['base.json', 'local.json'],
                    }
                },
            )
        )
        with open(target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'a=1 b=flat_override c=3\n')

    def test_params_shorthand_string(self):
        self._write('single.json', json.dumps({'A': 'x', 'B': 'y', 'C': 'z'}))
        target = os.path.join(self.base_dir, 'out.txt')
        plugin = _make_plugin(self.base_dir)
        self.assertTrue(
            plugin.handle(
                'template',
                {target: {'source_file': 'cfg.j2', 'params': 'single.json'}},
            )
        )
        with open(target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'a=x b=y c=z\n')

    @unittest.skipIf(_real_yaml is None, 'PyYAML not in PYTHONPATH')
    def test_yaml_and_empty_yaml_files(self):
        self._write('params.yaml', 'A: yaml_a\nB: yaml_b\nC: yaml_c\n')
        self._write('empty.yml', '')
        target = os.path.join(self.base_dir, 'out.txt')
        plugin = _make_plugin(self.base_dir)
        self.assertTrue(
            plugin.handle(
                'template',
                {
                    target: {
                        'source_file': 'cfg.j2',
                        'params_file': ['params.yaml', 'empty.yml'],
                    }
                },
            )
        )
        with open(target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'a=yaml_a b=yaml_b c=yaml_c\n')

    def test_yaml_loader_with_mock_module(self):
        self._write('mocked.yaml', 'ignored: true\n')
        target = os.path.join(self.base_dir, 'out.txt')
        plugin = _make_plugin(self.base_dir)
        fake_yaml = MagicMock()
        fake_yaml.safe_load.return_value = {'A': 'm1', 'B': 'm2', 'C': 'm3'}
        with patch.dict(sys.modules, {'yaml': fake_yaml}):
            self.assertTrue(
                plugin.handle(
                    'template',
                    {target: {'source_file': 'cfg.j2', 'params': 'mocked.yaml'}},
                )
            )
        with open(target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'a=m1 b=m2 c=m3\n')

    def test_validation_errors_on_bad_files(self):
        self._write('bad.txt', 'hello')
        self._write('list.json', '[1, 2, 3]')
        target = os.path.join(self.base_dir, 'out.txt')
        plugin = _make_plugin(self.base_dir)

        # Missing file
        self.assertFalse(
            plugin.handle(
                'template',
                {target: {'source_file': 'cfg.j2', 'params_file': 'missing.json'}},
            )
        )
        # Unsupported extension
        self.assertFalse(
            plugin.handle(
                'template',
                {target: {'source_file': 'cfg.j2', 'params_file': 'bad.txt'}},
            )
        )
        # Non-mapping top-level value
        self.assertFalse(
            plugin.handle(
                'template',
                {target: {'source_file': 'cfg.j2', 'params_file': 'list.json'}},
            )
        )
        # Invalid params type
        self.assertFalse(
            plugin.handle(
                'template',
                {target: {'source_file': 'cfg.j2', 'params': 42}},
            )
        )
        # Invalid params_file element type
        self.assertFalse(
            plugin.handle(
                'template',
                {target: {'source_file': 'cfg.j2', 'params_file': [123]}},
            )
        )


class TestStrictnessDryRunAndIdempotency(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_dir = self._tmpdir.name
        with open(
            os.path.join(self.base_dir, 'strict.j2'), 'w', encoding='utf-8'
        ) as f:
            f.write('req={{ REQ }} opt={{ OPT }}\n')
        with open(
            os.path.join(self.base_dir, 'filter.j2'), 'w', encoding='utf-8'
        ) as f:
            f.write("req={{ REQ }} opt={{ OPT | default('fallback') }}\n")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_strict_undefined_default_preserves_existing_target(self):
        target = os.path.join(self.base_dir, 'existing.conf')
        with open(target, 'w', encoding='utf-8') as f:
            f.write('precious-original-content\n')

        plugin = _make_plugin(self.base_dir)
        ok = plugin.handle(
            'template',
            {target: {'source_file': 'strict.j2', 'params': {'REQ': 'yes'}}},
        )
        self.assertFalse(ok)
        with open(target, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'precious-original-content\n')

    def test_strict_false_and_default_filter_succeed(self):
        target_lenient = os.path.join(self.base_dir, 'lenient.conf')
        target_filtered = os.path.join(self.base_dir, 'filtered.conf')
        plugin = _make_plugin(self.base_dir)

        self.assertTrue(
            plugin.handle(
                'template',
                {
                    target_lenient: {
                        'source_file': 'strict.j2',
                        'strict': False,
                        'params': {'REQ': 'yes'},
                    },
                    target_filtered: {
                        'source_file': 'filter.j2',
                        'params': {'REQ': 'yes'},
                    },
                },
            )
        )
        with open(target_lenient, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'req=yes opt=\n')
        with open(target_filtered, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), 'req=yes opt=fallback\n')

    def test_dry_run_validates_without_writing(self):
        target = os.path.join(self.base_dir, 'dry.conf')
        plugin = _make_plugin(self.base_dir, dry_run=True)

        # Valid render in dry-run logs action but leaves disk untouched
        self.assertTrue(
            plugin.handle(
                'template',
                {
                    target: {
                        'source_file': 'strict.j2',
                        'params': {'REQ': '1', 'OPT': '2'},
                    }
                },
            )
        )
        self.assertFalse(os.path.exists(target))
        plugin._log.action.assert_called_once_with(f'Would render template {target}')

        # Undefined variable is STILL caught during dry-run
        self.assertFalse(
            plugin.handle(
                'template',
                {target: {'source_file': 'strict.j2', 'params': {'REQ': '1'}}},
            )
        )

    def test_idempotent_rerun_skips_write_and_logs_info(self):
        target = os.path.join(self.base_dir, 'idem.conf')
        directive = {
            target: {
                'source_file': 'strict.j2',
                'params': {'REQ': '1', 'OPT': '2'},
            }
        }

        plugin1 = _make_plugin(self.base_dir)
        self.assertTrue(plugin1.handle('template', directive))
        plugin1._log.action.assert_called_once_with(f'Rendering template {target}')

        os.utime(target, (1_000_000_000, 1_000_000_000))
        mtime_before = os.path.getmtime(target)

        plugin2 = _make_plugin(self.base_dir)
        self.assertTrue(plugin2.handle('template', directive))
        plugin2._log.action.assert_not_called()
        plugin2._log.info.assert_any_call(f'Template target {target} is up to date')
        self.assertEqual(os.path.getmtime(target), mtime_before)

    def test_multi_target_continues_after_failure(self):
        bad_target = os.path.join(self.base_dir, 'bad.conf')
        good_target = os.path.join(self.base_dir, 'good.conf')
        plugin = _make_plugin(self.base_dir)

        ok = plugin.handle(
            'template',
            [
                {bad_target: {'source_file': 'strict.j2', 'params': {'REQ': 'only'}}},
                {
                    good_target: {
                        'source_file': 'strict.j2',
                        'params': {'REQ': 'ok', 'OPT': 'ok'},
                    }
                },
            ],
        )
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(bad_target))
        self.assertTrue(os.path.isfile(good_target))


if __name__ == '__main__':
    unittest.main()
