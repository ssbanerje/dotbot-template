#!/usr/bin/env python

from collections.abc import Mapping
import json
import os
import platform
import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple

import dotbot

try:
    from dotbot.util.common import normslash as _normslash
except ImportError:
    def _normslash(path: str) -> str:
        if sys.platform == 'win32':
            return path.replace('/', '\\')
        return path


def _expand_path(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(_normslash(path)))


def _inject() -> None:
    root_dir = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.join(root_dir, 'lib', 'markupsafe', 'src'))
    sys.path.insert(0, os.path.join(root_dir, 'lib', 'jinja', 'src'))


_inject()
from jinja2 import Environment, FileSystemLoader, StrictUndefined, Undefined  # noqa: E402


class Template(dotbot.Plugin):
    supports_dry_run = True

    _directive = 'template'

    def can_handle(self, directive: str) -> bool:
        return directive == self._directive

    def handle(self, directive: str, data: Any) -> bool:
        if directive != self._directive:
            msg = f'Template cannot handle directive {directive}'
            raise ValueError(msg)

        defaults = self._get_defaults()
        if defaults is None:
            return False

        try:
            targets = list(self._iter_targets(data))
        except (TypeError, ValueError) as exc:
            self._log.error(f'Invalid template directive configuration: {exc}')
            return False

        success = True
        for target, raw_opts in targets:
            success &= self._process_target(target, defaults, raw_opts)

        if success:
            self._log.info('All templates have been set up')
        else:
            self._log.error('Some templates were not successfully set up')
        return success

    def _get_defaults(self) -> Optional[Dict[str, Any]]:
        raw_defaults = self._context.defaults().get(self._directive, {})
        if raw_defaults is None:
            return {}
        if not isinstance(raw_defaults, Mapping):
            self._log.error(
                f'defaults.{self._directive} must be a mapping, got {type(raw_defaults).__name__}'
            )
            return None
        return dict(raw_defaults)

    @staticmethod
    def _iter_targets(data: Any) -> Iterator[Tuple[str, Any]]:
        if isinstance(data, Mapping):
            for target, opts in data.items():
                if not isinstance(target, str):
                    raise TypeError(
                        f'Template target path must be a string, got {type(target).__name__}'
                    )
                yield target, opts
            return

        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, Mapping) or len(entry) != 1:
                    raise ValueError(
                        'Each template list entry must be a single-key mapping'
                    )
                target, opts = next(iter(entry.items()))
                if not isinstance(target, str):
                    raise TypeError(
                        f'Template target path must be a string, got {type(target).__name__}'
                    )
                yield target, opts
            return

        raise TypeError(
            f'Template directive data must be a list or mapping, got {type(data).__name__}'
        )

    def _process_target(
        self, target: str, defaults: Mapping[str, Any], raw_opts: Any
    ) -> bool:
        try:
            if not isinstance(raw_opts, Mapping):
                raise TypeError(
                    f'Options for template {target} must be a mapping, got {type(raw_opts).__name__}'
                )
            opts: Dict[str, Any] = {**defaults, **raw_opts}
            if 'source_file' not in opts or not isinstance(opts['source_file'], str):
                raise ValueError('source_file must be provided as a path string')

            strict = opts.get('strict', True)
            if not isinstance(strict, bool):
                raise TypeError(
                    f'strict must be a boolean, got {type(strict).__name__}'
                )

            resolved_target = os.path.abspath(_expand_path(target))
            params = self._resolve_params(
                params_file=opts.get('params_file'),
                params=opts.get('params'),
            )
            self._render_template(
                opts['source_file'],
                params,
                resolved_target,
                display_target=target,
                strict=strict,
            )
        except Exception as exc:  # noqa: BLE001
            self._log.error(f'Could not render {target}: {exc}')
            return False
        return True

    def _is_dry_run(self) -> bool:
        dry_run_fn = getattr(self._context, 'dry_run', None)
        return bool(dry_run_fn()) if callable(dry_run_fn) else False

    def _log_action(self, message: str) -> None:
        action_fn = getattr(self._log, 'action', self._log.info)
        action_fn(message)

    def _resolve_params(
        self, params_file: Any = None, params: Any = None
    ) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for path in self._normalize_params_files(params_file):
            resolved.update(self._apply_uname(self._load_params_file(path)))

        if isinstance(params, str):
            resolved.update(self._apply_uname(self._load_params_file(params)))
        elif isinstance(params, Mapping):
            resolved.update(self._apply_uname(dict(params)))
        elif params is not None:
            raise TypeError(
                f'params must be a mapping or file path string, got {type(params).__name__}'
            )

        resolved['HOME_DIR'] = os.path.expanduser('~')
        return resolved

    @staticmethod
    def _normalize_params_files(params_file: Any) -> List[str]:
        if params_file is None:
            return []
        if isinstance(params_file, str):
            return [params_file]
        if isinstance(params_file, (list, tuple)):
            for item in params_file:
                if not isinstance(item, str):
                    raise TypeError(
                        f'params_file entries must be path strings, got {type(item).__name__}'
                    )
            return list(params_file)
        raise TypeError(
            'params_file must be a path string or list of path strings, '
            f'got {type(params_file).__name__}'
        )

    def _load_params_file(self, file_path: str) -> Dict[str, Any]:
        expanded = _expand_path(file_path)
        if not os.path.isabs(expanded):
            expanded = os.path.join(self._context.base_directory(), expanded)
        resolved_path = os.path.abspath(expanded)

        if not os.path.isfile(resolved_path):
            raise FileNotFoundError(f'Could not find params file: {file_path}')

        _, ext = os.path.splitext(resolved_path)
        ext = ext.lower()
        data: Any
        if ext == '.json':
            with open(resolved_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        elif ext in ('.yaml', '.yml'):
            try:
                import yaml
            except ImportError as exc:
                raise RuntimeError(
                    'PyYAML is required to load YAML params files'
                ) from exc
            with open(resolved_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            if data is None:
                data = {}
        elif ext == '.toml':
            try:
                import tomllib
            except ImportError as exc:
                raise RuntimeError(
                    'TOML params files require Python 3.11+ (tomllib)'
                ) from exc
            with open(resolved_path, 'rb') as f:
                data = tomllib.load(f)
        else:
            raise ValueError(
                f'Unsupported params file extension {ext!r} for {file_path} '
                '(supported: .yaml, .yml, .json, .toml)'
            )

        if not isinstance(data, Mapping):
            raise ValueError(
                f'Params file {file_path} must contain a top-level mapping, '
                f'got {type(data).__name__}'
            )
        return dict(data)

    @staticmethod
    def _apply_uname(params: Mapping[str, Any]) -> Dict[str, Any]:
        parsed = dict(params)
        if '__UNAME__' in parsed:
            uname_map = parsed.pop('__UNAME__')
            if not isinstance(uname_map, Mapping):
                raise ValueError('__UNAME__ must be a mapping')
            uname = platform.system()
            for key, per_os in uname_map.items():
                if not isinstance(per_os, Mapping) or uname not in per_os:
                    raise KeyError(
                        f'Unsupported platform {uname!r} for template param {key!r}'
                    )
                parsed[key] = per_os[uname]
        return parsed

    @staticmethod
    def _target_matches(target: str, expected: str) -> bool:
        if os.path.islink(target) or not os.path.isfile(target):
            return False
        try:
            with open(target, 'r', encoding='utf-8') as existing_file:
                return existing_file.read() == expected
        except (OSError, UnicodeDecodeError):
            return False

    def _render_template(
        self,
        template_file: str,
        params: Mapping[str, Any],
        target: str,
        *,
        display_target: str,
        strict: bool = True,
    ) -> None:
        cwd = self._context.base_directory()
        template_path = os.path.abspath(
            os.path.join(cwd, _expand_path(template_file))
        )
        template_dir = os.path.dirname(template_path)
        jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            keep_trailing_newline=True,
            undefined=StrictUndefined if strict else Undefined,
        )
        template = jinja_env.get_template(os.path.basename(template_path))
        rendered = template.render(params)

        if self._target_matches(target, rendered):
            self._log.info(f'Template target {display_target} is up to date')
            return

        if self._is_dry_run():
            self._log_action(f'Would render template {display_target}')
            return

        self._log_action(f'Rendering template {display_target}')
        parent_dir = os.path.dirname(os.path.abspath(target))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as target_file:
            target_file.write(rendered)
