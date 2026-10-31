#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import platform
import sys

import dotbot


def _inject():
    root_dir = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.join(root_dir, 'lib', 'markupsafe', 'src'))
    sys.path.insert(0, os.path.join(root_dir, 'lib', 'jinja', 'src'))


_inject()
from jinja2 import Environment, FileSystemLoader  # noqa: E402


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
                params = self._parse_params(opts.get('params', {}))
                self._render_template(opts['source_file'], params, resolved_target)
            except Exception as exc:
                self._log.error('Could not render %s: %s' % (target, exc))
                return False
        return True

    def _parse_params(self, params):
        parsed = dict(params)
        parsed['HOME_DIR'] = os.path.expanduser('~')
        if '__UNAME__' in parsed:
            uname_map = parsed.pop('__UNAME__')
            uname = platform.system()
            for key, per_os in uname_map.items():
                if uname not in per_os:
                    raise KeyError(
                        'Unsupported platform %r for template param %r' % (uname, key)
                    )
                parsed[key] = per_os[uname]
        return parsed

    def _render_template(self, template_file, params, target):
        cwd = self._context.base_directory()
        template_path = os.path.abspath(os.path.join(cwd, template_file))
        template_dir = os.path.dirname(template_path)
        jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            keep_trailing_newline=True,
        )
        template = jinja_env.get_template(os.path.basename(template_path))
        parent_dir = os.path.dirname(os.path.abspath(target))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as target_file:
            target_file.write(template.render(params))
