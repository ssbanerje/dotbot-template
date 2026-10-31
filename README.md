# dotbot-template

Template files using the [`jinja2`](https://jinja.palletsprojects.com/en/stable/) templating engine for [`dotbot`](https://github.com/anishathalye/dotbot).

## Prerequisites

This plugin requires [`dotbot`](https://github.com/anishathalye/dotbot) (Python 3.7+; `.toml` parameter files require Python 3.11+).

## Installation

1. Add the plugin as a submodule:
   ```bash
   git submodule add https://github.com/ssbanerje/dotbot-template.git
   git submodule update --init --recursive
   ```
2. Load the plugin in either of the ways supported by modern Dotbot:
   - **In your Dotbot YAML config** (`v1.23+`):
     ```yaml
     - plugins:
         - dotbot-template
     ```
   - **Or via the CLI** in your `install` script:
     ```bash
     dotbot --plugin dotbot-template -c install.conf.yaml
     ```

## Usage

Add the `template` directive to your Dotbot configuration file. Both Dotbot's mapping syntax (`target: { ... }`) and list syntax (`- target: { ... }`) are supported:

```yaml
- template:
    ~/.gitconfig:
      source_file: gitconfig
      params:
        NAME: John Doe
        EMAIL: jd@jd.com
        GITHUB_USERNAME: jd
        SIGNING_KEY: DEADBEEF
        SMTP_SERVER: smtp.gmail.com
        SMTP_PORT: 587
        SMTP_ENCRYPTION: tls
        __UNAME__:
          CREDENTIAL_HELPER:
            Darwin: osxkeychain
            Linux: cache --timeout 36000
```

### External & Layered Parameter Files

Parameters can also be loaded from external `.yaml`, `.yml`, `.json`, or `.toml` files (relative paths are resolved against Dotbot's base directory; `~` and `$ENV_VAR` references are expanded).

Single file shorthand:

```yaml
- template:
    ~/.gitconfig:
      source_file: gitconfig
      params: ./git_params.yaml
```

Layered parameter files combined with inline overrides (later entries override earlier ones, and inline `params` win):

```yaml
- template:
    ~/.gitconfig:
      source_file: gitconfig
      params_file:
        - ./git_params.yaml
        - ./overrides.json
      params:
        SMTP_ENCRYPTION: smtps
```

### Example Template

```ini
[core]
  excludesfile = {{HOME_DIR}}/.global_gitignore

[user]
  name = {{NAME}}
  email = {{EMAIL}}
  signingkey = {{SIGNING_KEY}}

[sendmail]
  smtpserver = {{SMTP_SERVER}}
  smtpserverport = {{SMTP_PORT}}
  smtpencryption = {{SMTP_ENCRYPTION}}
  smtpuser = {{EMAIL}}
  from = {{EMAIL}}

[github]
  user = {{GITHUB_USERNAME}}

[credential]
  helper = {{CREDENTIAL_HELPER}}
```

## Options & Behavior

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `source_file` | `str` | *(required)* | Path to the Jinja2 template file (resolved relative to Dotbot's base directory). |
| `params_file` | `str \| list[str]` | `None` | One or more `.yaml`, `.yml`, `.json`, or `.toml` mapping files merged in order. |
| `params` | `dict \| str` | `None` | Inline parameter mapping (merged on top of `params_file`), or a shorthand single parameter file path. |
| `strict` | `bool` | `true` | Uses Jinja2's `StrictUndefined` so missing template variables fail safely without truncating existing files. Set `strict: false` (or use `{{ VAR \| default('') }}` in templates) to allow undefined variables. |

- **Built-in parameters**: `HOME_DIR` is automatically set to the expanded home directory (`~`).
- **Platform-specific parameters (`__UNAME__`)**: Keys inside `__UNAME__` resolve using Python's `platform.system()` (e.g., `Linux`, `Darwin`, `Windows`) as each parameter layer is loaded, so later flat or `__UNAME__` overrides take precedence cleanly.
- **Dotbot `defaults` support**: Shared options (e.g., `strict: false` or a common `params_file`) can be configured via `- defaults: { template: { ... } }`.
- **Idempotency & `--dry-run`**: Re-running Dotbot skips writing targets whose UTF-8 content already matches the rendered template. Running `dotbot --dry-run` validates parameters and renders templates in memory while reporting `Would render template ...` without modifying files on disk.

See the [Jinja template designer documentation](https://jinja.palletsprojects.com/en/stable/templates/) for full template syntax details.
