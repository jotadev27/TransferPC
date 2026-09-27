Name:           transferpc
Version:        1.0
Release:        1%{?dist}
Summary:        Verified local file transfers
License:        MIT
Packager:       jotadev27
BuildArch:      noarch
Source0:        %{name}-%{version}.tar.gz
Requires:       python3 >= 3.10
Requires:       python3-pyside6 >= 6.6
Requires:       hicolor-icon-theme

%description
TransferPC is a local desktop utility for copying and moving files with
progress reporting and destination integrity verification.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_bindir}
install -m 0755 packaging/fedora/transferpc %{buildroot}%{_bindir}/transferpc
install -d %{buildroot}%{_libexecdir}/transferpc/transferpc
install -m 0644 packaging/fedora/launch.py %{buildroot}%{_libexecdir}/transferpc/launch.py
install -m 0644 transferpc/*.py %{buildroot}%{_libexecdir}/transferpc/transferpc/
install -d %{buildroot}%{_libexecdir}/transferpc/assets
install -m 0644 assets/*.svg %{buildroot}%{_libexecdir}/transferpc/assets/
install -d %{buildroot}%{_datadir}/applications
install -m 0644 packaging/fedora/transferpc.desktop %{buildroot}%{_datadir}/applications/transferpc.desktop
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -m 0644 assets/transferpc.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/transferpc.svg
for size in 32 48 64 128 256; do
  install -d %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps
  install -m 0644 assets/icons/${size}x${size}/transferpc.png %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/transferpc.png
done

%files
%license LICENSE
%doc THIRD_PARTY_NOTICES.md
%{_bindir}/transferpc
%{_libexecdir}/transferpc
%{_datadir}/applications/transferpc.desktop
%{_datadir}/icons/hicolor/scalable/apps/transferpc.svg
%{_datadir}/icons/hicolor/32x32/apps/transferpc.png
%{_datadir}/icons/hicolor/48x48/apps/transferpc.png
%{_datadir}/icons/hicolor/64x64/apps/transferpc.png
%{_datadir}/icons/hicolor/128x128/apps/transferpc.png
%{_datadir}/icons/hicolor/256x256/apps/transferpc.png

%changelog
* Sat Sep 26 2026 TransferPC - 1.0-1
- Package the MIT-licensed TransferPC 1.0 release.
