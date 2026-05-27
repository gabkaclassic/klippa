"""klippad — Python-демон менеджера буфера обмена klippa.

Содержит всю логику: хранилище истории (store), конфиг (config),
шифрование (crypto), персистентность (db), миниатюры (thumbs) и
D-Bus-сервис (service). Слой gi изолирован в service/thumbs/__main__,
чтобы ядро (store/config/crypto/db) покрывалось unit-тестами.
"""

__version__ = "0.1.3"
