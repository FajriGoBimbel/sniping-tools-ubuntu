# Snipper — Screenshot & Anotasi untuk Ubuntu

Python + GTK4 + libadwaita, canvas Cairo, capture lewat XDG Desktop Portal (Wayland & X11).

## Menjalankan

Setelah diinstal, pakai perintah `snipper`. Dari source tanpa install, pakai `./snipper-run`. Opsinya sama:

```bash
./snipper-run              # jendela launcher (Area / Layar penuh / Jendela + delay)
./snipper-run --area       # langsung capture area
./snipper-run --full       # layar penuh (semua layar; --monitor 2 = layar ke-2)
./snipper-run --window     # capture jendela (dialog GNOME)
./snipper-run --area --delay 5
./snipper-run --open gambar.png
./snipper-run --background # tetap aktif dengan ikon tray
```

Dependensi (sudah ada di Ubuntu desktop 22.04/24.04):
`sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1`

## Cara install

### Cara tercepat — dari APT repository (tanpa download manual)

Ganti `<username>` dengan akun/organisasi GitHub tempat repo ini dipublikasikan
(lihat [Publikasi APT repository](#publikasi-apt-repository)).

```bash
curl -fsSL https://<username>.github.io/sniping-tools/install.sh | sudo sh
```

Perintah itu menambahkan repository Snipper beserta kunci tanda tangannya, lalu menjalankan `apt install snipper`.
Setelah itu, Snipper dikelola apt seperti aplikasi lain:

```bash
sudo apt install snipper                  # pasang ulang di kemudian hari
sudo apt update && sudo apt upgrade       # update ke versi terbaru
sudo apt remove snipper                   # uninstall
```

Kalau hanya ingin menambahkan repository dan install sendiri dengan apt:

```bash
curl -fsSL https://<username>.github.io/sniping-tools/install.sh | sudo sh -s -- --setup-only
sudo apt install snipper
```

Cara manual tanpa script:

```bash
sudo curl -fsSLo /usr/share/keyrings/snipper-archive-keyring.gpg https://<username>.github.io/sniping-tools/snipper-archive-keyring.gpg
sudo curl -fsSLo /etc/apt/sources.list.d/snipper.sources https://<username>.github.io/sniping-tools/snipper.sources
sudo apt update && sudo apt install snipper
```

> `apt` tidak bisa langsung menginstall dari sebuah link. Karena itu, repository perlu ditambahkan **sekali** di awal.
> Setelahnya cukup `sudo apt install snipper` atau `sudo apt upgrade`.

### Cara lain (dari source)

Pilih **salah satu** cara di bawah. Paket `.deb` direkomendasikan untuk penggunaan sehari-hari.
Jangan pasang `.deb` dan `install.sh` bersamaan, karena ikon Snipper akan muncul dua kali di menu.

Semua perintah dijalankan dari folder proyek:

```bash
cd sniping-tools
```

### Opsi A — Paket `.deb` (direkomendasikan, butuh sudo)

1. Build paketnya:

   ```bash
   ./packaging/deb/build-deb.sh
   # hasil: dist/snipper_0.1.0_all.deb
   ```

2. Install. Dependensinya ikut dipasang otomatis oleh apt:

   ```bash
   sudo apt install ./dist/snipper_0.1.0_all.deb
   ```

3. Cek hasilnya:

   ```bash
   snipper --version     # Snipper 0.1.0
   ```

Untuk **update** setelah kode berubah, build ulang lalu pasang ulang:

```bash
./packaging/deb/build-deb.sh && sudo apt install --reinstall ./dist/snipper_0.1.0_all.deb
```

Untuk **uninstall**:

```bash
snipper --remove-shortcuts   # opsional: kembalikan shortcut Print Screen bawaan GNOME
sudo apt remove snipper
```

### Opsi B — Per user, tanpa sudo

1. Pastikan dependensinya ada (biasanya sudah terpasang di Ubuntu desktop):

   ```bash
   sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
   ```

2. Install ke `~/.local`:

   ```bash
   ./install.sh
   ```

   Hasilnya ada di `~/.local/bin/snipper`, dan Snipper muncul di menu aplikasi.
   Jalankan `./install.sh` lagi untuk update.

Untuk **uninstall**: `./install.sh --uninstall`

### Opsi C — Flatpak

Butuh `flatpak-builder` serta runtime `org.gnome.Platform//47` dan `org.gnome.Sdk//47`:

```bash
flatpak-builder --user --install --force-clean build-dir packaging/flatpak/com.wahanacreative.Snipper.yml
flatpak run com.wahanacreative.Snipper
```

Catatan: versi Flatpak tidak bisa memasang shortcut global sendiri (lihat [Catatan](#catatan)).

### Setelah install

1. **Beri izin screenshot (sekali saja).** Buka **Snipper** dari menu aplikasi, klik **Izinkan**, lalu pilih *Allow* di dialog GNOME.
   Tanpa izin ini, setiap capture lewat dialog screenshot GNOME dulu. Dialog itu juga menyalin gambar mentah ke clipboard.
   Izin terikat ke app id `com.wahanacreative.Snipper`, jadi hanya tersimpan bila Snipper sudah diinstal (opsi A atau B).

2. **Pasang shortcut Print Screen (opsional):**

   ```bash
   snipper --install-shortcuts   # Print = area, Shift+Print = layar penuh, Alt+Print = jendela
   snipper --remove-shortcuts    # kembalikan shortcut screenshot bawaan GNOME
   ```

   Shortcut juga bisa diubah dan dipasang dari **Preferensi → Shortcut global**.

3. **Ikon tray (opsional):** aktifkan **Preferensi → Jalankan saat login**, atau jalankan `snipper --background`.
   Ikon tray butuh ekstensi AppIndicator, yang sudah aktif secara default di Ubuntu.

### Bila ada masalah

Jalankan `snipper` dari terminal agar pesan error terlihat, atau lihat log:

```bash
journalctl --user --since "-10min" | grep -i snipper
```

## Publikasi APT repository

Untuk maintainer. Cukup dilakukan sekali; setelah itu setiap push ke `main` otomatis mem-build `.deb`,
menandatangani repository, dan mempublikasikannya ke GitHub Pages (`.github/workflows/apt-repo.yml`).

1. **Buat repo GitHub** bernama `sniping-tools`, lalu push proyek ini ke branch `main`.
2. **Simpan kunci penanda tangan sebagai secret.** Buka *Settings → Secrets and variables → Actions → New repository secret*.
   Beri nama `APT_GPG_PRIVATE_KEY`, lalu tempel seluruh isi `~/.local/share/snipper-apt/private-key.asc`.
   Setelah tersimpan, hapus file itu (`rm ~/.local/share/snipper-apt/private-key.asc`).
   Kuncinya tetap ada di `~/.local/share/snipper-apt/gnupg`, jadi bisa diekspor ulang bila perlu.
3. **Aktifkan Pages.** Buka *Settings → Pages → Source*, lalu pilih **GitHub Actions**.
4. **Jalankan workflow** *APT repository* (push ke `main` atau *Run workflow*).
   Repository akan tersedia di `https://<username>.github.io/sniping-tools/`.

Untuk **merilis versi baru**, naikkan `VERSION` di `snipper/settings.py`, lalu push.
`apt upgrade` hanya mengambil versi yang nomornya lebih tinggi.

Info kunci penanda tangan:

- Nama: *Snipper APT Repository*, ed25519
- Fingerprint: `31188C05ECC8ADD12BA5307BEE358CFA0A2CD2EA`
- Kunci publik: `packaging/apt/snipper-archive-keyring.asc`
- **Jangan pernah commit kunci privat.**

Untuk memakai domain sendiri, isi variabel repository `APT_REPO_URL` (mis. `https://apt.wahanacreative.com`).

Build dan uji repository secara lokal:

```bash
./packaging/deb/build-deb.sh
GNUPGHOME=~/.local/share/snipper-apt/gnupg APT_SIGNING_KEY=31188C05ECC8ADD12BA5307BEE358CFA0A2CD2EA \
  REPO_URL=http://127.0.0.1:8000 python3 packaging/apt/build-repo.py --out public
python3 -m http.server 8000 -d public
```

## Fitur vs PRD

| Fitur | Prioritas | Status |
| --- | --- | --- |
| Capture area (drag, ukuran piksel tampil) | P0 | ✅ overlay per monitor, klik = 1 layar penuh, Esc = batal |
| Capture layar penuh (satu / semua layar) | P0 | ✅ `--monitor N` atau Preferensi |
| Capture jendela | P1 | ✅ lewat dialog GNOME (Wayland tidak mengizinkan app memilih jendela lain) |
| Delay 3/5/10 detik | P1 | ✅ |
| Include kursor | P2 | ⚠️ hanya lewat toggle "Show pointer" di dialog GNOME (capture jendela) |
| Rectangle (outline/isi), Panah, Teks (ukuran, warna, bold) | P0 | ✅ |
| Undo/Redo tanpa batas (Ctrl+Z / Ctrl+Shift+Z) | P0 | ✅ |
| Crop (non-destruktif, bisa di-undo) | P0 | ✅ |
| Ellipse & garis, Highlighter, Blur/pixelate | P1 | ✅ |
| Nomor langkah otomatis, Pensil bebas | P2 | ✅ |
| Pemilih warna, ketebalan, zoom | — | ✅ Ctrl+scroll, Ctrl±, Ctrl+0 (fit), Ctrl+1 (100%) |
| Simpan PNG/JPG ke `~/Pictures/Screenshots`, nama otomatis tanggal-jam | — | ✅ Ctrl+S, Ctrl+Shift+S |
| Salin ke clipboard | — | ✅ Ctrl+C |
| Shortcut global bisa diubah | — | ✅ custom keybinding GNOME |
| Ikon tray | — | ✅ StatusNotifierItem (butuh ekstensi AppIndicator, default di Ubuntu) |
| HiDPI & multi-monitor | — | ✅ |
| Lokal, tanpa akun/internet | — | ✅ |

Setiap anotasi tetap berupa objek yang bisa dipilih, digeser, di-resize, diubah warnanya, atau dihapus sampai diekspor.

## Cara pakai editor

| Tombol | Aksi |
| --- | --- |
| V R E L A T H B N P C | Pilih, Kotak, Elips, Garis, Panah, Teks, Highlighter, Blur, Nomor, Pensil, Crop |
| Shift saat menggambar | kotak/lingkaran sama sisi, garis/panah per 45° |
| Delete | hapus objek terpilih; panah keyboard = geser 1px (Shift = 10px) |
| Dobel-klik teks | edit teks (dengan tool Teks: klik sekali) |
| Enter / Shift+Enter / Esc | selesai teks / baris baru / batal |

Dengan tool gambar aktif, objek yang baru dibuat tetap terpilih: tarik handle untuk resize, tarik badannya untuk menggeser.
Mengubah warna/ketebalan/font saat ada objek terpilih langsung mengubah objek itu.

## Struktur

```
snipper/
  app.py       Application, CLI, alur capture, launcher, tray
  capture.py   XDG Desktop Portal + fallback CLI (gnome-screenshot/maim/scrot/grim/import), peta monitor
  selector.py  overlay pemilihan area
  editor.py    jendela editor (toolbar, simpan, salin, zoom)
  canvas.py    canvas Cairo interaktif (gambar, pilih, geser, resize, crop)
  shapes.py    objek anotasi
  document.py  gambar dasar + objek + crop + undo/redo + ekspor
  shortcuts.py shortcut global GNOME
  tray.py      ikon tray (StatusNotifierItem + dbusmenu)
  prefs.py     preferensi
data/          .desktop, metainfo, ikon
packaging/     build .deb dan manifest Flatpak
tests/         python3 tests/test_document.py ; python3 tests/test_canvas.py (butuh sesi grafis)
```

## Catatan

- Di Wayland isi clipboard ikut hilang bila aplikasi pemiliknya keluar; karena itu Snipper tetap berjalan di latar
  (maks. 30 menit) setelah Ctrl+C sampai clipboard diganti aplikasi lain.
- Di Flatpak, shortcut global via gsettings tidak bisa ditulis ke host; pasang shortcut dari versi `.deb`/`install.sh`
  atau atur manual di Settings → Keyboard → Custom Shortcuts dengan perintah `flatpak run com.wahanacreative.Snipper --area`.
- Kompatibel dengan GTK 4.6 / libadwaita 1.1 (Ubuntu 22.04): API baru (FileDialog, ColorDialog, AlertDialog,
  PreferencesDialog) dipakai bila tersedia, dengan fallback ke API lama.
