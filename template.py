#!/usr/bin/env python
# -*- coding: utf-8 -*-

from collections.abc import Mapping
import json
import os
import platform
import sys

import dotbot


def _inject():
    root_dir = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.join(root_dir, 'lib', 'markupsafe', 'src'))
    sys.path.insert(0, os.path.join(root_dir, 'lib', 'jinja', 'src'))


_inject()
from jinja2 import Environment, FileSystemLoader, StrictUndefined, Undefined  # noqa: E402


class Template(dotbot.Plugin):
    _directive = 'template'

    def can_handle(self, directive):
        return directive == self._directive

    def handle(self, directive, data):
        if directive != self._directive:
            raise ValueError('Cannot handle this directive %s' % directive)

        for temp in data:
            target, opts = next(iter(temp.items()))
            self._log.info('Rendering template %s' % target)
            try:
                resolved_target = os.path.expanduser(target)
                strict = opts.get('strict', True)
                if not isinstance(strict, bool):
                    raise TypeError(
                        'strict must be a boolean, got %s' % type(strict).__name__
                    )
                params = self._resolve_params(
                    params_file=opts.get('params_file'),
                    params=opts.get('params'),
                )
                self._render_template(
                    opts['source_file'], params, resolved_target, strict=strict
                )
            except Exception as exc:
                self._log.error('Could not render %s: %s' % (target, exc))
                return False
        return True

    def _resolve_params(self, params_file=None, params=None):
        resolved = {}
        for path in self._normalize_params_files(params_file):
            resolved.update(self._apply_uname(self._load_params_file(path)))

        if isinstance(params, str):
            resolved.update(self._apply_uname(self._load_params_file(params)))
        elif isinstance(params, Mapping):
            resolved.update(self._apply_uname(dict(params)))
        elif params is not None:
            raise TypeError(
                'params must be a mapping or file path string, got %s'
                % type(params).__name__
            )

        resolved['HOME_DIR'] = os.path.expanduser('~')
        return resolved

    @staticmethod
    def _normalize_params_files(params_file):
        if params_file is None:
            return []
        if isinstance(params_file, str):
            return [params_file]
        if isinstance(params_file, (list, tuple)):
            for item in params_file:
                if not isinstance(item, str):
                    raise TypeError(
                        'params_file entries must be path strings, got %s'
                        % type(item).__name__
                    )
            return list(params_file)
        raise TypeError(
            'params_file must be a path string or list of path strings, got %s'
            % type(params_file).__name__
        )

    def _load_params_file(self, file_path):
        expanded = os.path.expanduser(file_path)
        if not os.path.isabs(expanded):
            expanded = os.path.join(self._context.base_directory(), expanded)
        resolved_path = os.path.abspath(expanded)

        if not os.path.isfile(resolved_path):
            raise FileNotFoundError('Could not find params file: %s' % file_path)

        _, ext = os.path.splitext(resolved_path)
        ext = ext.lower()
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
                'Unsupported params file extension %r for %s '
                '(supported: .yaml, .yml, .json, .toml)' % (ext, file_path)
            )

        if not isinstance(data, Mapping):
            raise ValueError(
                'Params file %s must contain a top-level mapping, got %s'
                % (file_path, type(data).__name__)
            )
        return dict(data)

    @staticmethod
    def _apply_uname(params):
        parsed = dict(params)
        if '__UNAME__' in parsed:
            uname_map = parsed.pop('__UNAME__')
            if not isinstance(uname_map, Mapping):
                raise ValueError('__UNAME__ must be a mapping')
            uname = platform.system()
            for key, per_os in uname_map.items():
                if not isinstance(per_os, Mapping) or uname not in per_os:
                    raise KeyError(
                        'Unsupported platform %r for template param %r' % (uname, key)
                    )
                parsed[key] = per_os[uname]
        return parsed

    def _render_template(self, template_file, params, target, strict=True):
        cwd = self._context.base_directory()
        template_path = os.path.abspath(
            os.path.join(cwd, os.path.expanduser(template_file))
        )
        template_dir = os.path.dirname(template_path)
        jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            keep_trailing_newline=True,
            undefined=StrictUndefined if strict else Undefined,
        )
        template = jinja_env.get_template(os.path.basename(template_path))
        rendered = template.render(params)

        parent_dir = os.path.dirname(os.path.abspath(target))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as target_file:
            target_file.write(rendered)
