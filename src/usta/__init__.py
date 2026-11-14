"""Usta."""

from usta import compat as _compat

# Güvenlik: Windows'ta programlar bulunduğu klasörden (çalışma alanı) çalıştırılamasın. Her giriş noktasında
# (terminal, arka plan, portal, testler) paket yüklenir yüklenmez geçerli olsun diye burada.
_compat.harden_exe_search()
