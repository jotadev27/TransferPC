# Third-party notices

TransferPC source code and the application folder icon are covered by the
[MIT license](LICENSE). Dependencies retain their own licenses.

- The bundled refresh icon is from [SVG Repo](https://www.svgrepo.com/svg/164354/refresh-arrow), distributed under CC0.
- PySide6, Shiboken6 and Qt are used under their applicable open-source licenses, including LGPL v3. The RPM uses distribution-managed libraries. The portable, DEB and pacman packages ship shared libraries that can be replaced in their `_internal/` directory (installed packages use `/opt/transferpc/_internal/`). Reverse engineering for debugging modifications to LGPL libraries is permitted.
- Python is distributed under the Python Software Foundation license and its included notices.
- PyInstaller's bootloader uses GPL with a distribution exception; that exception permits distributing this application under MIT.

The bundled packages include license texts under `licenses/` beside the executable.
The corresponding upstream source projects are
[Qt](https://code.qt.io/), [PySide and Shiboken](https://code.qt.io/cgit/pyside/pyside-setup.git/),
[CPython](https://github.com/python/cpython), and
[PyInstaller](https://github.com/pyinstaller/pyinstaller).
Fedora source packages for the exact distribution builds are available from
[Fedora Koji](https://koji.fedoraproject.org/koji/).
