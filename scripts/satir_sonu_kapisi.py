# -*- coding: utf-8 -*-
"""Bir commit'in SAHTE olup olmadigini soyler: butun dosya satir sonu cevrilmis mi.

NEDEN VAR (2026-09-21)
----------------------
Bu depoda tekrarlayan ve pahali bir hata sinifi var: bir dosyanin KUCUK bir
parcasi degistirilmek istenirken dosyanin TAMAMI farkli satir sonuyla
yeniden yaziliyor. Sonuc, 3 satirlik bir degisiklik icin 400 satirlik bir
diff. Gercek degisiklik o gurultunun icinde kayboluyor, inceleme imkansiz
hale geliyor, ve birkac kez yanlislikla commit'lendi.

Tek bir oturumda UC KEZ olustu (kayitlar_sayfasi.dart, channel_editor_page.dart,
packages/ffmpeg.cmake). Not almak engellemedi; hata yazma aninda oluyor,
not ise oturum basinda okunuyor.

YONTEM
------
Basit ve kesin: ayni diff'i iki kez olc.
  - normal:            git diff --cached --numstat
  - CR yok sayarak:    git diff --cached --numstat --ignore-cr-at-eol

Bir dosyada normal olcum buyuk, CR yok sayilan olcum sifir ise, o dosyada
ICERIK HIC DEGISMEMIS demektir; yalnizca satir sonlari cevrilmistir. Bu her
zaman kazadir ve reddedilir.

Icerik degisikligi ile birlikte satir sonu da cevrilmisse (normal olcum
buyuk, CR yok sayilan olcum kucuk ama sifir degil) yine uyarilir, cunku
incelemeyi ayni sekilde bozar.

KULLANIM
--------
    python scripts/satir_sonu_kapisi.py          # staged degisiklikleri dener
    python scripts/satir_sonu_kapisi.py --kur    # git pre-commit kancasi kurar

Kanca kurulduktan sonra hatirlamaya gerek kalmaz; kapi kendi calisir.
"""
import os
import subprocess
import sys

# Bu orandan fazlasi satir sonu gurultusuyse sorun var.
GURULTU_ESIGI = 5  # gercek degisiklik basina izin verilen gurultulu satir


def numstat(ekstra):
    cikti = subprocess.run(
        ['git', 'diff', '--cached', '--numstat'] + ekstra,
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    sonuc = {}
    for satir in cikti.stdout.splitlines():
        parca = satir.split('\t')
        if len(parca) != 3:
            continue
        ekle, sil, ad = parca
        if ekle == '-' or sil == '-':   # ikili dosya
            continue
        sonuc[ad] = int(ekle) + int(sil)
    return sonuc


def kur():
    kok = subprocess.run(['git', 'rev-parse', '--git-dir'],
                         capture_output=True, text=True).stdout.strip()
    if not kok:
        print('git deposu degil')
        return 1
    yol = os.path.join(kok, 'hooks', 'pre-commit')
    govde = (
        '#!/bin/sh\n'
        '# Satir sonu kapisi: bkz. scripts/satir_sonu_kapisi.py\n'
        'python scripts/satir_sonu_kapisi.py || exit 1\n'
    )
    if os.path.exists(yol):
        mevcut = open(yol, encoding='utf-8', errors='replace').read()
        if 'satir_sonu_kapisi' in mevcut:
            print('kanca zaten kurulu: %s' % yol)
            return 0
        print('UYARI: pre-commit zaten var ve baska bir sey yapiyor: %s' % yol)
        print('Elle ekle:  python scripts/satir_sonu_kapisi.py || exit 1')
        return 1
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, 'w', encoding='utf-8', newline='\n') as f:
        f.write(govde)
    os.chmod(yol, 0o755)
    print('kanca kuruldu: %s' % yol)
    return 0


def main():
    if '--kur' in sys.argv:
        return kur()

    ham = numstat([])
    temiz = numstat(['--ignore-cr-at-eol'])
    if not ham:
        return 0

    olu = []       # icerik HIC degismemis, yalniz satir sonu
    gurultulu = []  # icerik degismis ama satir sonu da cevrilmis
    for ad, n in sorted(ham.items()):
        t = temiz.get(ad, 0)
        if t == 0 and n > 0:
            olu.append((ad, n))
        elif t > 0 and n - t > max(GURULTU_ESIGI, t * GURULTU_ESIGI):
            gurultulu.append((ad, n, t))

    if not olu and not gurultulu:
        return 0

    print('')
    print('COMMIT DURDU: satir sonu cevrilmesi var.')
    print('')
    for ad, n in olu:
        print('  %s' % ad)
        print('    %d satir degismis gorunuyor ama ICERIK AYNI.' % n)
        print('    Tamami satir sonu cevrilmesi. Bu her zaman kazadir.')
    for ad, n, t in gurultulu:
        print('  %s' % ad)
        print('    gercek degisiklik %d satir, toplam diff %d satir.' % (t, n))
        print('    Aradaki %d satir satir sonu gurultusu.' % (n - t))
    print('')
    print('Care: dosyayi deponun kullandigi satir sonuna geri cevir.')
    print('  git show HEAD:<dosya> | file -     # depo ne kullaniyor')
    print('  git diff --cached --ignore-cr-at-eol --stat <dosya>')
    print('')
    print('Bilerek yapiyorsan:  git commit --no-verify')
    return 1


if __name__ == '__main__':
    sys.exit(main())
