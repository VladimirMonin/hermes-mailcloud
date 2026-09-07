# Third-Party Notices — Hermes MailCloud 0.1.0a0

This notice ledger covers the `hermes-mailcloud` 0.1.0a0 distribution. It is a
compliance record, not legal advice. The project is MIT-licensed under
[`LICENSE`](LICENSE).

## Locked Python runtime ledger

The following is the exact runtime dependency ledger from committed `uv.lock`.
`resolver-only` means that the dependency is selected by the Python package
resolver and is not vendored into this repository. The CI release gate evaluates
environment markers in this ledger and in
`uv export --locked --no-dev --no-emit-project --no-hashes`, then requires both
maps to equal the clean installed runtime map.

<!-- hmc-runtime-ledger:start -->
```json
[
  {"name": "annotated-doc", "version": "0.0.4"},
  {"name": "colorama", "version": "0.4.6", "marker": "sys_platform == 'win32'"},
  {"name": "markdown-it-py", "version": "4.2.0"},
  {"name": "mdurl", "version": "0.1.2"},
  {"name": "pygments", "version": "2.20.0"},
  {"name": "rich", "version": "14.3.4"},
  {"name": "shellingham", "version": "1.5.4"},
  {"name": "typer", "version": "0.26.8"}
]
```
<!-- hmc-runtime-ledger:end -->

| Resolver-only component | Exact version / marker | SPDX license | Pinned license source |
|---|---:|---|---|
| [annotated-doc](https://pypi.org/project/annotated-doc/0.0.4/) | `0.0.4` | MIT | [upstream LICENSE](https://github.com/fastapi/annotated-doc/blob/0.0.4/LICENSE) |
| [colorama](https://pypi.org/project/colorama/0.4.6/) | `0.4.6`; Windows only | BSD-3-Clause | [upstream LICENSE.txt](https://github.com/tartley/colorama/blob/0.4.6/LICENSE.txt) |
| [markdown-it-py](https://pypi.org/project/markdown-it-py/4.2.0/) | `4.2.0` | MIT | [upstream LICENSE](https://github.com/executablebooks/markdown-it-py/blob/v4.2.0/LICENSE) |
| [mdurl](https://pypi.org/project/mdurl/0.1.2/) | `0.1.2` | MIT | [upstream LICENSE](https://github.com/executablebooks/mdurl/blob/0.1.2/LICENSE) |
| [Pygments](https://pypi.org/project/Pygments/2.20.0/) | `2.20.0` | BSD-2-Clause | [upstream LICENSE](https://github.com/pygments/pygments/blob/2.20.0/LICENSE) |
| [Rich](https://pypi.org/project/rich/14.3.4/) | `14.3.4` | MIT | [upstream LICENSE](https://github.com/Textualize/rich/blob/v14.3.4/LICENSE) |
| [Shellingham](https://pypi.org/project/shellingham/1.5.4/) | `1.5.4` | ISC | [upstream LICENSE](https://github.com/sarugaku/shellingham/blob/1.5.4/LICENSE) |
| [Typer](https://pypi.org/project/typer/0.26.8/) | `0.26.8` | MIT | [upstream LICENSE](https://github.com/fastapi/typer/blob/0.26.8/LICENSE) |

Typer 0.26.8 vendors Click source. It is not a separate resolver package in the
ledger, but its bundled [Click `LICENSE.txt`](https://github.com/fastapi/typer/blob/0.26.8/typer/_click/LICENSE.txt)
is BSD-3-Clause and remains an applicable notice for the Typer wheel.

MIT, BSD-2-Clause, BSD-3-Clause, and ISC permit commercial use and contain no
royalty obligation. Their material redistribution duties differ: retain the
copyright and license/disclaimer text for MIT and ISC; retain the copyright,
conditions, and disclaimer for both BSD licenses; and do not use contributor
names to endorse a derived product under BSD-3-Clause. This project preserves
these notices in this ledger and must update it before adding, removing, or
vendoring a runtime dependency.

## External runtime boundary

[`rclone` v1.74.4](https://github.com/rclone/rclone/tree/v1.74.4) is MIT-licensed
([COPYING](https://github.com/rclone/rclone/blob/v1.74.4/COPYING)) and is invoked
only as a separately installed external subprocess. It is not a Python resolver
dependency, vendored source tree, or bundled executable in this distribution.

## Research-only sources

The following projects may be consulted as research references only. Their code
is not shipped by `hermes-mailcloud` and they are not runtime dependencies:

| Project | License | Allowed role |
|---|---|---|
| [`scharfff/mailrucloud`](https://github.com/scharfff/mailrucloud) | MIT | WebDAV-oriented behavioral research; preserve notices before copying any material. |
| [`kireevmp/mailru-cloud-api`](https://github.com/kireevmp/mailru-cloud-api) | MIT | Reverse-engineered API research; preserve notices before copying any material. |
| [`mad-gooze/PyMailCloud`](https://github.com/mad-gooze/PyMailCloud) | GPL-2.0 | Historical research only; its GPL-2.0 code is not shipped, vendored, or adapted here. |

Version 0.1 uses the external rclone subprocess boundary and does not fork or
vendor a third-party Mail.ru client. A future decision to bundle rclone, copy
third-party implementation code, add a private API backend, or add a GPL
dependency requires a separate license review and an updated ledger.
